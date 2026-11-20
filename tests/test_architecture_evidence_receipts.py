"""Developer regressions for host-owned FINISH evidence shape (not benchmark evidence).

Source: #37/#11 mechanism review. The recorded v0.6/v0.7 studies remain immutable.
"""
from __future__ import annotations

import copy
import unittest
from dataclasses import replace

from examples.architecture.incident_env import IncidentHost
from examples.architecture.turnwise_core import Decision, ModelOutcome, Op, TurnwiseRuntime


QUESTION = "Could the latest checkout deployment explain the increase in errors?"


def investigated_host() -> IncidentHost:
    host = IncidentHost(QUESTION)
    for tool in ("error_trend", "recent_deploys"):
        receipt = host.execute(tool, {"service": "checkout"}, proposed_by="turnwise_policy")
        assert receipt.executed
    return host


class ReceiptContentGateTests(unittest.TestCase):
    def test_two_correct_independent_receipts_are_sufficient_structurally(self):
        host = investigated_host()
        self.assertEqual(host.missing_evidence(("r1", "r2")), ())

    def test_an_executed_receipt_with_wrong_service_fact_is_not_evidence(self):
        host = investigated_host()
        r = host.receipts[0]
        host.receipts[0] = replace(r, facts={"trend:payments": r.facts["trend:checkout"]})
        self.assertIn("symptom:checkout (malformed source payload)",
                      host.missing_evidence(("r1", "r2")))

    def test_an_executed_receipt_with_empty_or_wrong_shape_does_not_count(self):
        for payload in ({}, {"trend:checkout": {}},
                        {"trend:checkout": {"error_rate_before_pct": 1.0}}):
            with self.subTest(payload=payload):
                host = investigated_host()
                host.receipts[0] = replace(host.receipts[0], facts=payload)
                self.assertIn("symptom:checkout (malformed source payload)",
                              host.missing_evidence(("r1", "r2")))

    def test_tool_role_cannot_be_forged_by_a_fact_key(self):
        host = IncidentHost(QUESTION)
        r = host.execute("recent_deploys", {"service": "checkout"},
                         proposed_by="turnwise_policy")
        self.assertTrue(r.executed)
        host.receipts[0] = replace(r, facts={
            "trend:checkout": {"error_rate_before_pct": 0.1, "error_rate_after_pct": 4.0}})
        self.assertIn("symptom:checkout", host.missing_evidence(("r1",)))

    def test_conflicting_read_receipts_fail_even_when_only_one_is_cited(self):
        host = investigated_host()
        second = host.execute("error_trend", {"service": "checkout"},
                              proposed_by="turnwise_policy")
        changed = copy.deepcopy(second.facts)
        changed["trend:checkout"]["error_rate_after_pct"] += 1.0
        host.receipts[-1] = replace(second, facts=changed)
        self.assertIn("conflicting symptom:checkout",
                      host.missing_evidence(("r1", "r2")))
        self.assertIn("conflicting symptom:checkout",
                      host.missing_evidence(("r2", "r3")))

    def test_identical_repeated_receipts_are_not_a_conflict(self):
        host = investigated_host()
        host.execute("error_trend", {"service": "checkout"},
                     proposed_by="turnwise_policy")
        self.assertEqual(host.missing_evidence(("r1", "r2")), ())

    def test_valid_empty_deployment_list_is_not_malformed(self):
        host = IncidentHost("Could the latest auth deployment explain the increase in errors?")
        symptoms = host.execute("error_trend", {"service": "auth"},
                                proposed_by="turnwise_policy")
        changes = host.execute("recent_deploys", {"service": "auth"},
                               proposed_by="turnwise_policy")
        self.assertTrue(symptoms.executed and changes.executed)
        self.assertEqual(changes.facts["deploys:auth"]["deploys"], [])
        self.assertEqual(host.missing_evidence(("r1", "r2")), ())

    def test_runtime_rejects_finish_when_cited_receipt_has_invalid_payload(self):
        host = investigated_host()
        host.receipts[0] = replace(host.receipts[0], facts={"trend:checkout": {}})
        runtime = TurnwiseRuntime(host, policy=object(), model=object())
        runtime.outcomes.append(ModelOutcome(
            "m1", "heavy_model", "answer_candidate", "The deploy caused it.",
            cited=("r1", "r2"), shown=("r1", "r2")))
        ok, why = runtime.host_validates(
            Decision(Op.FINISH, "check host evidence", candidate="m1"), 3)
        self.assertFalse(ok)
        self.assertIn("symptom:checkout", why)


if __name__ == "__main__":
    unittest.main()
