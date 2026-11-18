"""Prospective host-contract regression tests (synthetic, no model or network).

These are developer-authored fixtures, not independent held-out evidence.
They do not alter, rerun, or re-grade frozen v0.6 traces.
"""
from __future__ import annotations

from datetime import datetime, timezone
import unittest

from turnwise_lab.agent.contracts import Decision, Observation
from turnwise_lab.agent.host import Host, Limits
from turnwise_lab.agent.loop import execute_user_turn
from turnwise_lab.agent.providers import PendingGenerator, RuleContextSelector, ScriptedDecider
from turnwise_lab.agent.world import IncidentWorld


def read(name: str, service: str) -> Decision:
    return Decision("call_tool", name, {"service": service})


def receipt(service: str, status: str = "degraded", *,
            target: str = "get_service_health", arguments: dict | None = None) -> Observation:
    return Observation(
        0, "synthetic/c1", "call_tool", target, arguments or {"service": service}, "ok",
        facts={f"health:{service}": {"service": service, "status": status,
                                     "observed_at": "2026-11-01T11:40:00Z"}},
    )


def drive(text: str, steps: list[Decision], *, limits: Limits | None = None,
          variant: str = "baseline", conversation: list[dict] | None = None):
    host = Host(IncidentWorld(variant), limits=limits)
    trace = execute_user_turn(
        text, host=host, decider=ScriptedDecider(steps),
        context=RuleContextSelector("minimal"), generator=PendingGenerator(),
        turn_id="EVIDENCE-NEW", conversation=conversation,
    )
    return trace, host


class EvidenceGateTests(unittest.TestCase):
    def test_single_fact_health_lookup_finishes_without_model(self):
        trace, _ = drive("How healthy is payments?", [
            read("get_service_health", "payments"), Decision("finish")])
        self.assertEqual(trace.final["kind"], "verified")
        self.assertIn("health:payments", trace.final["text"])
        self.assertEqual(trace.totals["generation_calls"], {"light": 0, "heavy": 0})
        self.assertTrue(trace.steps[-1]["validation"]["evidence"]["sufficient"])

    def test_partial_causal_investigation_cannot_finish(self):
        trace, _ = drive("Why have auth errors increased?", [
            read("get_error_metrics", "auth"), Decision("finish"), Decision("abstain")])
        self.assertEqual(trace.steps[1]["validation"]["status"], "rejected")
        self.assertEqual(trace.final["kind"], "abstain")
        report = trace.steps[1]["validation"]["evidence"]
        self.assertIn("deploys:auth", report["missing"])
        self.assertIn("health:auth", report["missing"])
        self.assertIn("config:auth", report["missing"])
        self.assertFalse(report["sufficient"])

    def test_complementary_evidence_can_finish_as_facts_not_causal_claim(self):
        trace, _ = drive("Why did payments errors spike?", [
            read("get_error_metrics", "payments"),
            read("get_deployment_history", "payments"),
            read("get_config_diff", "payments"),
            read("get_service_health", "payments"),
            Decision("finish"),
        ])
        self.assertEqual(trace.final["kind"], "verified")
        self.assertIn("no causal inference established", trace.final["text"])
        for family in ("health", "errors", "deploys", "config"):
            self.assertIn(f"{family}:payments", trace.final["text"])
        self.assertEqual(len(trace.steps[-1]["validation"]["evidence"]["verified"]), 4)

    def test_comparison_does_not_accept_one_services_receipt_for_another(self):
        trace, _ = drive("Compare the health of auth and payments", [
            read("get_service_health", "auth"), Decision("finish"), Decision("abstain")])
        self.assertEqual(trace.steps[1]["validation"]["status"], "rejected")
        self.assertIn("health:payments", trace.steps[1]["validation"]["evidence"]["missing"])

    def test_comparison_can_finish_with_two_independent_receipts(self):
        trace, _ = drive("Compare auth and payments health", [
            read("get_service_health", "auth"), read("get_service_health", "payments"), Decision("finish")])
        self.assertEqual(trace.final["kind"], "verified")
        self.assertIn("health:auth", trace.final["text"])
        self.assertIn("health:payments", trace.final["text"])

    def test_wrong_referent_never_inherits_last_tool_call(self):
        trace, _ = drive("Is checkout healthy?", [
            read("get_service_health", "auth"), Decision("finish"), Decision("abstain")])
        self.assertEqual(trace.steps[1]["validation"]["status"], "rejected")
        self.assertIn("health:checkout", trace.steps[1]["validation"]["evidence"]["missing"])

    def test_ambiguous_pronoun_does_not_reuse_last_service(self):
        previous = [{"role": "user", "content": "Compare checkout with auth."}]
        trace, _ = drive("And their status?", [
            read("get_service_health", "checkout"), Decision("finish"), Decision("abstain")],
            conversation=previous)
        self.assertIn("referent_ambiguous", trace.steps[1]["validation"]["evidence"]["problems"])

    def test_unique_previous_user_referent_can_be_resolved(self):
        previous = [{"role": "user", "content": "Investigate payments"}]
        trace, _ = drive("And the current status?", [
            read("get_service_health", "payments"), Decision("finish")],
            conversation=previous)
        self.assertEqual(trace.final["kind"], "verified")

    def test_action_intent_is_not_erased_by_read_completion(self):
        trace, _ = drive("Page the auth on-call, after checking health.", [
            read("get_service_health", "auth"), Decision("finish"), Decision("abstain")])
        self.assertIn("unsafe_or_unsupported_intent", trace.steps[1]["validation"]["reason"])
        self.assertNotEqual(trace.final["kind"], "verified")

    def test_unknown_intent_fails_closed(self):
        trace, _ = drive("Tell me something about checkout", [
            read("get_service_health", "checkout"), Decision("finish"), Decision("abstain")])
        self.assertEqual(trace.steps[1]["validation"]["status"], "rejected")
        self.assertIn("unsafe_or_unsupported_intent:unclassified", trace.steps[1]["validation"]["reason"])

    def test_mismatched_source_and_arguments_cannot_satisfy_fact(self):
        host = Host(IncidentWorld())
        forged = receipt("checkout", target="get_service_owner")
        validation = host.validate(Decision("finish"), [forged], user_message="checkout status?")
        self.assertFalse(validation.ok)
        self.assertIn("provenance_mismatch:health:checkout", validation.evidence["problems"])

    def test_same_key_conflicting_successful_receipts_fail_closed(self):
        host = Host(IncidentWorld())
        validation = host.validate(Decision("finish"),
                                   [receipt("checkout", "healthy"), receipt("checkout", "degraded")],
                                   user_message="checkout health?")
        self.assertFalse(validation.ok)
        self.assertIn("conflicting_observations:health:checkout", validation.evidence["problems"])

    def test_stale_observation_requires_explicit_incident_clock(self):
        reference = datetime(2026, 11, 18, tzinfo=timezone.utc)
        host = Host(IncidentWorld(), limits=Limits(evidence_reference_time=reference))
        validation = host.validate(Decision("finish"), [receipt("checkout")],
                                   user_message="What's checkout's current status?")
        self.assertFalse(validation.ok)
        self.assertIn("stale:health:checkout", validation.evidence["problems"])
        self.assertTrue(validation.evidence["clock_checked"])

    def test_historical_replay_does_not_assume_wall_clock(self):
        trace, _ = drive("What is checkout's current status?", [
            read("get_service_health", "checkout"), Decision("finish")])
        self.assertEqual(trace.final["kind"], "verified")
        self.assertFalse(trace.steps[-1]["validation"]["evidence"]["clock_checked"])

    def test_current_fact_without_timestamp_is_not_proven_fresh(self):
        reference = datetime(2026, 11, 18, tzinfo=timezone.utc)
        host = Host(IncidentWorld(), limits=Limits(evidence_reference_time=reference))
        obs = host.execute(read("get_error_metrics", "checkout"), step_index=0,
                           call_id="evidence/c1", user_text="checkout error rates")
        validation = host.validate(Decision("finish"), [obs],
                                   user_message="Latest checkout error rate?")
        self.assertFalse(validation.ok)
        self.assertIn("freshness_unverifiable:errors:checkout", validation.evidence["problems"])

    def test_retry_success_cannot_replace_missing_complementary_evidence(self):
        trace, _ = drive("Why are checkout errors elevated?", [
            read("get_error_metrics", "checkout"), read("get_error_metrics", "checkout"),
            Decision("finish"), Decision("abstain")], variant="metrics_flaky")
        self.assertEqual([o["status"] for o in trace.observations[:2]], ["error", "ok"])
        self.assertEqual(trace.steps[2]["validation"]["status"], "rejected")
        self.assertIn("deploys:checkout", trace.steps[2]["validation"]["evidence"]["missing"])

    def test_rendering_rejects_insufficient_assessment(self):
        host = Host(IncidentWorld())
        with self.assertRaises(ValueError):
            host.render_verified([receipt("auth")], evidence={"sufficient": False, "verified": []})


if __name__ == "__main__":
    unittest.main()
