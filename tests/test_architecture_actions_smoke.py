"""Guard the ordering of the one-shot boundary and the public evidence projection."""
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WorkflowTests(unittest.TestCase):
    def test_single_dispatch_and_create_only_reservation(self):
        workflow = (ROOT / ".github/workflows/paid-smoke.yml").read_text()
        self.assertIn("on: workflow_dispatch\n", workflow)
        self.assertEqual(workflow.count("github.run_attempt == '1'"), 3)
        self.assertIn("github.actor == 'dgenio'", workflow)
        self.assertIn("github.ref == 'refs/heads/main'", workflow)
        self.assertIn("needs: validate", workflow)
        self.assertIn("needs: reserve", workflow)
        self.assertIn('gh api --method POST "$api/refs"', workflow)
        self.assertNotIn("--method PATCH", workflow)
        self.assertIn("ref=refs/tags/turnwise-paid-gpt-6-1-sol-001", workflow)
        self.assertEqual(workflow.count("--provider openai"), 1)
        self.assertNotIn("upload-artifact", workflow)

    @unittest.skipUnless(importlib.util.find_spec("httpx2"), "needs pinned framework dependencies")
    def test_summary_ignores_private_content_and_marks_missing_evidence(self):
        from examples.architecture.actions_summary import summarize
        from examples.architecture.provider import REAL_SOURCE, DOUBLE_SOURCE
        with self.assertRaises(ValueError):
            summarize({"source": DOUBLE_SOURCE})
        secret = "PRIVATE-CONTENT"
        rec = dict(framework="openai-agents", architecture="turnwise", verdict="INTERRUPTED",
                   provider_requests=[dict(status=None, response={}, usage={})],
                   termination={"status": secret, "answer": secret}, error=secret,
                   tool_calls=[dict(tool=secret, status=secret)], typed_outcomes=[],
                   checks=[dict(check=secret, detail=secret, result="inconclusive")])
        rows = summarize({"source": REAL_SOURCE, "configs": [rec]})
        self.assertEqual(len(rows), 4)
        self.assertNotIn(secret, json.dumps(rows))
        self.assertIsNone(rows[1]["reported_tokens"])
        self.assertEqual(rows[1]["admitted_requests"], 1)
        self.assertTrue(all(r["verdict"] == "INCONCLUSIVE" for r in rows))
