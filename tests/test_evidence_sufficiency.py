"""Prospective regression tests for the minimum-evidence FINISH gate.

These use freshly constructed synthetic requests and tool observations;
historical held-out fixtures, labels, scores and trace archives are untouched.
"""
import copy
import unittest

from turnwise_lab.agent.contracts import Decision, Observation
from turnwise_lab.agent.host import Host
from turnwise_lab.agent.loop import execute_user_turn
from turnwise_lab.agent.providers import PendingGenerator, RuleContextSelector, ScriptedDecider
from turnwise_lab.agent.world import IncidentWorld


def read(target, service, *, step=0):
    world = IncidentWorld()
    facts = world.handlers()[target]({"service": service})["facts"]
    return Observation(step, f"r{step}", "call_workflow" if target == "run_smoke_checks" else "call_tool",
                       target, {"service": service}, "ok", facts=facts)


def tool(target, service):
    return Decision("call_tool", target, {"service": service})


class MinimumEvidenceGateTests(unittest.TestCase):
    def setUp(self):
        self.host = Host(IncidentWorld())

    def check(self, request, observations):
        return self.host.validate(Decision("finish"), observations, user_text=request)

    def test_simple_explicit_lookup_can_finish(self):
        result = self.check("Current payments health status?", [read("get_service_health", "payments")])
        self.assertTrue(result.ok)
        self.assertEqual(result.sufficiency["present"], ("health:payments",))
        self.assertEqual(result.sufficiency["missing"], ())

    def test_successful_irrelevant_tool_does_not_justify_finish(self):
        result = self.check("What is the checkout error rate?", [read("get_service_health", "checkout")])
        self.assertFalse(result.ok)
        self.assertEqual(result.sufficiency["missing"], ("errors:checkout",))

    def test_wrong_service_not_a_valid_referent(self):
        result = self.check("Show search health", [read("get_service_health", "checkout")])
        self.assertFalse(result.ok)
        self.assertEqual(result.sufficiency["missing"], ("health:search",))

    def test_causal_investigation_requires_three_complementary_facts(self):
        question = "Could the recent checkout release explain the increase in errors?"
        metrics = read("get_error_metrics", "checkout")
        deploy = read("get_deployment_history", "checkout", step=1)
        health = read("get_service_health", "checkout", step=2)
        first = self.check(question, [metrics])
        self.assertFalse(first.ok)
        self.assertEqual(first.sufficiency["missing"], ("deploys:checkout", "health:checkout"))
        second = self.check(question, [metrics, deploy])
        self.assertFalse(second.ok)
        self.assertEqual(second.sufficiency["missing"], ("health:checkout",))
        self.assertTrue(self.check(question, [metrics, deploy, health]).ok)

    def test_successful_retry_does_not_compensate_for_missing_investigation_evidence(self):
        question = "Why did checkout errors spike?"
        failed = Observation(0, "r0", "call_tool", "get_error_metrics", {"service": "checkout"},
                             "error", reason="timeout")
        metrics = read("get_error_metrics", "checkout", step=1)
        result = self.check(question, [failed, metrics])
        self.assertFalse(result.ok)
        self.assertIn("deploys:checkout", result.sufficiency["missing"])
        self.assertIn("health:checkout", result.sufficiency["missing"])

    def test_compound_request_requires_each_services_evidence(self):
        result = self.check("What is the status of checkout and search?",
                            [read("get_service_health", "checkout")])
        self.assertFalse(result.ok)
        self.assertEqual(result.sufficiency["missing"], ("health:search",))
        self.assertTrue(self.check("What is the status of checkout and search?",
                                   [read("get_service_health", "checkout"),
                                    read("get_service_health", "search", step=1)]).ok)

    def test_ambiguous_referent_and_unknown_intent_fail_closed(self):
        self.assertFalse(self.check("And what about it?", [read("get_service_health", "checkout")]).ok)
        v = self.check("How is checkout doing?", [read("get_service_health", "checkout")])
        self.assertFalse(v.ok)
        self.assertEqual(v.sufficiency["missing"], ("intent:unclassified",))

    def test_action_request_not_silently_recast_as_read_completion(self):
        v = self.check("Rollback checkout", [read("get_deployment_history", "checkout")])
        self.assertFalse(v.ok)
        self.assertEqual(v.sufficiency["intent"], "action")
        self.assertIn("action_intent:pending", v.sufficiency["missing"])

    def test_forged_payload_service_does_not_count(self):
        o = read("get_service_health", "checkout")
        o.facts["health:checkout"]["service"] = "search"
        v = self.check("checkout status?", [o])
        self.assertFalse(v.ok)
        self.assertEqual(v.sufficiency["missing"], ("health:checkout",))

    def test_conflicting_successful_observations_block_finish(self):
        first = read("get_service_health", "checkout")
        second = copy.deepcopy(first)
        second.step_index = 1
        second.facts["health:checkout"]["status"] = "healthy"
        v = self.check("checkout status?", [first, second])
        self.assertFalse(v.ok)
        self.assertEqual(v.sufficiency["conflicts"], ("health:checkout",))

    def test_loop_rejects_premature_finish_then_recovers_with_new_evidence(self):
        policy = ScriptedDecider([tool("get_error_metrics", "checkout"), Decision("finish"),
                                  tool("get_deployment_history", "checkout"),
                                  tool("get_service_health", "checkout"), Decision("finish")])
        host = Host(IncidentWorld())
        trace = execute_user_turn("Why did checkout errors rise?", host=host, decider=policy,
                                  context=RuleContextSelector("minimal"), generator=PendingGenerator(),
                                  turn_id="PROSPECTIVE")
        self.assertEqual(trace.steps[1]["validation"]["status"], "rejected")
        self.assertIn("deploys:checkout", trace.steps[1]["validation"]["sufficiency"]["missing"])
        self.assertEqual(trace.final["kind"], "verified")
        self.assertEqual(host.world.write_ledger, [])

    def test_new_gate_never_reads_evaluation_gold(self):
        from pathlib import Path
        path = Path(__file__).resolve().parents[1] / "turnwise_lab" / "agent" / "sufficiency.py"
        code = path.read_text(encoding="utf-8")
        for prohibited in ("expect.required_facts", "required_facts", "gold[", "gold."):
            self.assertNotIn(prohibited, code)


if __name__ == "__main__":
    unittest.main()
