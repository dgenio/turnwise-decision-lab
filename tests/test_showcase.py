"""Validate that the public exhibit is generated from the same live planner implementation."""
from __future__ import annotations

import json
from pathlib import Path
import unittest

from turnwise_lab.showcase import ROOT, SHOWCASE, make_exhibit, page, text_report


class ShowcaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = json.loads(SHOWCASE.read_text(encoding="utf-8"))
        cls.data = make_exhibit(cls.rows)

    def test_expected_four_paths_and_hold(self):
        self.assertEqual([x["plan"]["path"] for x in self.data["cases"]],
                         ["direct", "flow", "tool", "llm", "hold", "llm"])

    def test_verified_answer_never_calls_classifier(self):
        p = self.data["cases"][0]["plan"]
        self.assertFalse(p["decision_model_called"])
        self.assertIsNone(self.data["cases"][0]["decider_received"])
        self.assertIsNotNone(p["deterministic_answer"])

    def test_unapproved_publication_stays_on_hold(self):
        p = self.data["cases"][4]["plan"]
        self.assertTrue(p["approval_required"])
        self.assertEqual(p["capability_id"], "publish_api_incident")
        self.assertEqual(p["context_pack"], [])

    def test_relevant_context_is_bounded_and_excludes_noise(self):
        x = self.data["cases"][3]
        self.assertEqual(x["plan"]["context_ids"],
                         ["service-errors", "api-change", "deployment-window"])
        self.assertLessEqual(x["selected_source_chars"], 320)
        self.assertNotIn("office-menu", x["plan"]["context_ids"])

    def test_classification_state_is_bounded_and_has_no_source_bodies(self):
        for x in self.data["cases"]:
            if x["decider_received"]:
                preview = json.dumps(x["decider_received"])
                for source in next(row for row in self.rows if row["id"] == x["id"]).get("sources", []):
                    self.assertNotIn(source["body"], preview)

    def test_html_self_contained_and_reproducible(self):
        html = page(self.data)
        self.assertIn("One Turn.", html)
        self.assertIn("status page", html)
        self.assertNotIn("fetch(", html)
        self.assertNotIn("https://", html)
        self.assertEqual(page(self.data), html)
        self.assertEqual((ROOT / "demo" / "index.html").read_text(encoding="utf-8"), html)

    def test_json_evidence_generated_with_matching_content(self):
        expected = json.dumps(self.data, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        self.assertEqual((ROOT / "demo" / "showcase.json").read_text(encoding="utf-8"), expected)

    def test_text_does_not_pretend_measured_benefit(self):
        report = text_report(self.data)
        self.assertIn("NOT decision-model quality", report)
        self.assertIn("RULES", report)

    def test_no_duplicate_fixture_ids(self):
        with self.assertRaises(ValueError):
            make_exhibit(self.rows + [self.rows[0]])


if __name__ == "__main__":
    unittest.main()
