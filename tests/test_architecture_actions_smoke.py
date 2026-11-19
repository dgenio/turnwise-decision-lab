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
        self.assertIn('gh api "$api/ref/tags/turnwise-paid-gpt-6-1-sol-001"', workflow)
        self.assertIn("ref=refs/tags/turnwise-paid-gpt-6-1-sol-002", workflow)
        self.assertEqual(workflow.count("--provider openai"), 1)
        self.assertEqual(workflow.count("uses: actions/upload-artifact@"), 1)
        upload = workflow.split("uses: actions/upload-artifact@", 1)[1].split("      - name:", 1)[0]
        self.assertEqual([line.strip() for line in upload.splitlines() if line.strip().startswith("path:")],
                         ["path: ${{ runner.temp }}/turnwise-summary.json"])

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

    @unittest.skipUnless(importlib.util.find_spec("httpx2"), "needs pinned framework dependencies")
    def test_summary_preserves_only_known_error_codes_and_labels_skipped_arms(self):
        import httpx2
        from examples.architecture.actions_summary import summarize
        from examples.architecture.provider import REAL_SOURCE, summarize_response

        for code, expected in (("insufficient_quota", "insufficient_quota"), ("private-data", "unknown")):
            response, usage = summarize_response(httpx2.Response(
                429, json={"error": {"code": code, "message": "private-data"}}))
            rec = dict(framework="openai-agents", architecture="conventional", verdict="INCONCLUSIVE",
                       provider_requests=[dict(status=429, response=response, usage=usage)])
            rows = summarize(dict(source=REAL_SOURCE, configs=[rec], stop_reason="provider_http_429"))
            self.assertEqual(rows[0]["provider_error_codes"], [expected])
            self.assertNotIn("private-data", json.dumps(rows))
            self.assertTrue(all(r["termination"] == "not_started_after_http_429" for r in rows[1:]))
