"""Contract tests using synthetic data, not historical study traces."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from turnwise_lab.parity import audit


EXAMPLE = Path(__file__).parents[1] / "fixtures" / "benchmark-parity-example.json"


class ParityTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        self.a, self.b = self.data["arms"]

    def fail_reason(self, needle):
        report = audit(self.data)
        self.assertFalse(report["structural_parity_passed"])
        self.assertTrue(any(needle in x for x in report["blockers"]), report)

    def test_equal_access_with_different_policy_cost_is_structurally_valid(self):
        report = audit(self.data)
        self.assertTrue(report["structural_parity_passed"], report)
        self.assertEqual(report["arm_summaries"]["decision_controlled"]["recorded_events"]["decision"], 1)
        self.assertIsNone(report["arm_summaries"]["heavy_only"]["billed_usd_if_complete"])

    def test_mismatched_permissions_are_never_waivable(self):
        self.b["permissions"] = ["write"]
        self.data["declared_treatments"] = [{"field": "permissions", "reason": "not permitted"}]
        self.fail_reason("non-negotiable parity mismatch in permissions")

    def test_differing_implicit_retrieval_requires_predeclaration(self):
        self.b["document_access_mode"] = "implicit_retrieval"
        self.fail_reason("document_access_mode differs without a declared treatment")
        self.data["declared_treatments"] = [{"field": "document_access_mode", "reason": "document selection ablation"}]
        report = audit(self.data)
        self.assertTrue(report["structural_parity_passed"], report)
        self.assertTrue(report["declared_treatments"])

    def test_unreceipted_document_in_generation_prompt_is_blocked(self):
        self.b["events"][-1]["prompt_source_ids"].append("rb-timeouts")
        self.fail_reason("model saw sources without earlier retrieval/tool/initial-context receipt")

    def test_prior_retrieval_receipt_allows_document_in_prompt(self):
        self.b["events"].insert(2, {"kind": "retrieval", "source_ids": ["rb-timeouts"],
                                     "duration_ms": 3, "billed_usd": None})
        self.b["declared_event_counts"]["retrieval"] = 1
        self.b["events"][-1]["prompt_source_ids"].append("rb-timeouts")
        self.assertTrue(audit(self.data)["structural_parity_passed"])

    def test_unknown_source_is_blocked(self):
        self.b["events"][1]["source_ids"] = ["confidential-other-service"]
        self.fail_reason("unknown/unavailable source ids")

    def test_unmeasured_decision_compute_is_blocked(self):
        del self.b["events"][0]["duration_ms"]
        self.fail_reason("finite nonnegative duration_ms required")

    def test_receipt_count_is_checked(self):
        self.b["declared_event_counts"]["decision"] = 2
        self.fail_reason("decision receipt count 1 != declared 2")

    def test_equivalent_step_count_is_not_assumed(self):
        self.b["max_tool_calls"] = 2
        self.fail_reason("non-negotiable parity mismatch in max_tool_calls")

    def test_cannot_claim_zero_provider_bills_from_unknown_cost(self):
        for e in self.b["events"]:
            e["billed_usd"] = None
        self.assertIsNone(audit(self.data)["arm_summaries"]["decision_controlled"]["billed_usd_if_complete"])


if __name__ == "__main__":
    unittest.main()
