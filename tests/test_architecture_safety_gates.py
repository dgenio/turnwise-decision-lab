"""Prospective offline host-boundary regressions for the canonical architecture demo.

These are new mechanism tests, not frozen v0.6/v0.7 evaluation tasks or proof
of model quality. No provider calls, benchmark labels or third-party data.
"""
from __future__ import annotations

import unittest

from examples.architecture.incident_env import IncidentHost, requested_writes
from examples.architecture.policies import TriagePolicy
from examples.architecture.turnwise_core import (
    Decision, ModelOutcome, Op, TurnwiseRuntime, parse_outcome,
)


def check_finish(task: str, tool_reads, *, cited=None):
    host = IncidentHost(task)
    receipts = [host.execute(tool, {"service": service}, proposed_by="turnwise_policy")
                for tool, service in tool_reads]
    assert all(r.executed for r in receipts)
    visible = tuple(r.id for r in receipts)
    cited = visible if cited is None else tuple(cited)
    runtime = TurnwiseRuntime(host, TriagePolicy(), model=None)
    runtime.outcomes.append(ModelOutcome(
        "m1", "heavy_model", "answer_candidate", "A possible explanation.",
        cited=cited, shown=visible,
    ))
    ok, why = runtime.host_validates(Decision(Op.FINISH, "attempt", candidate="m1"), 1)
    return ok, why


class EvidenceRoleGateTests(unittest.TestCase):
    def test_causal_answer_needs_cited_symptom_and_change_for_same_service(self):
        q = "Could the latest checkout deployment explain the increase in errors?"
        self.assertEqual(check_finish(q, [("error_trend", "checkout")])[0], False)
        ok, why = check_finish(q, [("error_trend", "checkout")])
        self.assertIn("change:checkout", why)
        ok, why = check_finish(q, [
            ("error_trend", "checkout"), ("recent_deploys", "checkout"),
        ], cited=("r1",))
        self.assertFalse(ok)
        self.assertIn("change:checkout", why)
        ok, why = check_finish(q, [
            ("error_trend", "checkout"), ("recent_deploys", "checkout"),
        ])
        self.assertTrue(ok, why)

    def test_evidence_about_another_service_does_not_complete_a_causal_answer(self):
        ok, why = check_finish("Why did checkout errors rise?", [
            ("error_trend", "payments"), ("recent_deploys", "payments"),
        ])
        self.assertFalse(ok)
        self.assertIn("symptom:checkout", why)
        self.assertIn("change:checkout", why)

    def test_multi_service_investigation_requires_coverage_for_each_user_referent(self):
        ok, why = check_finish("Why are checkout and payments errors rising?", [
            ("error_trend", "checkout"), ("recent_deploys", "checkout"),
        ])
        self.assertFalse(ok)
        self.assertIn("symptom:payments", why)

    def test_status_answer_cannot_use_unrelated_change_evidence(self):
        q = "Is checkout healthy right now?"
        ok, why = check_finish(q, [("recent_deploys", "checkout")])
        self.assertFalse(ok)
        self.assertIn("current_state:checkout", why)
        self.assertTrue(check_finish(q, [("service_health", "checkout")])[0])

    def test_missing_referent_does_not_become_an_invented_service(self):
        ok, why = check_finish("Why did errors rise?", [
            ("error_trend", "checkout"), ("recent_deploys", "checkout"),
        ])
        self.assertFalse(ok)
        self.assertIn("unresolved service target", why)


class ActionAuthorityGateTests(unittest.TestCase):
    def test_later_withdrawals_revoke_earlier_write_request(self):
        for question in (
            "Roll back checkout. Actually no, don't.",
            "Roll back checkout. Never mind.",
            "Roll back checkout. Ignore my previous request.",
            "Roll back checkout. Ignore that instruction.",
            "Roll back checkout. Wait, don't.",
        ):
            with self.subTest(question=question):
                self.assertEqual(requested_writes(question), frozenset())

    def test_positive_request_and_question_remain_distinct(self):
        self.assertEqual(requested_writes("Please roll back the latest checkout deployment."),
                         {("rollback_deploy", "checkout")})
        self.assertEqual(requested_writes("Roll back checkout?"), frozenset())
        self.assertEqual(requested_writes("The assistant wrote: roll back checkout."), frozenset())

    def test_host_checks_target_even_if_controller_or_model_proposes_a_write(self):
        host = IncidentHost("Roll back checkout.")
        wrong = host.execute("rollback_deploy", {"service": "payments"}, proposed_by="llm")
        right = host.execute("rollback_deploy", {"service": "checkout"}, proposed_by="turnwise_policy")
        self.assertEqual((wrong.status, right.status), ("rejected", "held_for_approval"))
        self.assertEqual(host.write_ledger, [])

    def test_direct_and_generated_finish_cannot_silently_drop_requested_write(self):
        task = "Roll back checkout. What is the incident severity?"
        host = IncidentHost(task)
        runtime = TurnwiseRuntime(host, TriagePolicy(), model=None)
        ok, why = runtime.host_validates(Decision(Op.DIRECT, "skip action", target="severity"), 1)
        self.assertFalse(ok)
        self.assertIn("drop a user-requested action", why)

        read = host.execute("error_trend", {"service": "checkout"}, proposed_by="llm")
        runtime.outcomes.append(ModelOutcome(
            "m1", "heavy_model", "answer_candidate", "Done.",
            cited=(read.id,), shown=(read.id,),
        ))
        ok, why = runtime.host_validates(Decision(Op.FINISH, "skip action", candidate="m1"), 1)
        self.assertFalse(ok)
        self.assertIn("outstanding requested action", why)
        self.assertEqual(host.write_ledger, [])

    def test_approval_claim_must_match_an_actual_held_host_receipt(self):
        no_write = IncidentHost("Is checkout healthy?")
        runtime = TurnwiseRuntime(no_write, TriagePolicy(), model=None)
        claimed = Decision(Op.HOLD, "pretend approval",
                           message="rollback_deploy(checkout) awaits human approval.")
        ok, why = runtime.host_validates(claimed, 1)
        self.assertFalse(ok)
        self.assertIn("without any host-held action receipt", why)

        requested = IncidentHost("Roll back checkout.")
        held = requested.execute("rollback_deploy", {"service": "checkout"}, proposed_by="llm")
        self.assertEqual(held.status, "held_for_approval")
        runtime = TurnwiseRuntime(requested, TriagePolicy(), model=None)
        wrong = Decision(Op.HOLD, "retarget", message="rollback_deploy(payments) awaits human approval.")
        ok, why = runtime.host_validates(wrong, 1)
        self.assertFalse(ok)
        self.assertIn("no matching host-held service", why)
        right = Decision(Op.HOLD, "receipt-grounded",
                         message="rollback_deploy(checkout) awaits human approval. It has NOT been executed.")
        self.assertTrue(runtime.host_validates(right, 1)[0])
        self.assertEqual(requested.write_ledger, [])

    def test_malformed_model_proposal_never_becomes_an_executed_action(self):
        outcome = parse_outcome({
            "kind": "tool_proposal", "text": "do it",
            "tool": "rollback_deploy", "arguments_json": '["checkout"]',
            "cited_receipts": [],
        }, oid="m1", source="heavy_model", shown=())
        self.assertEqual(outcome.kind, "invalid")


if __name__ == "__main__":
    unittest.main()
