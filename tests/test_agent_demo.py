"""The v0.6 trace viewer must be generated from the committed traces, offline and injection-safe."""
from pathlib import Path
import json
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "demo" / "index.html"
NEEDED = [ROOT / "reports" / "v06" / "summary.json", ROOT / "reports" / "v06" / "traces" / "dev" / "dm_dynamic.json",
          ROOT / "reports" / "v06" / "traces" / "dev" / "heavy_agent.json"]


@unittest.skipUnless(all(p.exists() for p in NEEDED), "v0.6 traces not recorded")
class DemoPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from turnwise_lab.agent import demo
        cls.demo = demo
        cls.html = demo.render()

    def test_committed_page_is_generated_from_committed_traces(self):
        self.assertEqual(PAGE.read_text(encoding="utf-8"), self.html)

    def test_offline_and_no_html_injection(self):
        script = self.html.split("<script>", 1)[1]
        for banned in ("fetch(", "XMLHttpRequest", "innerHTML", "eval(", "document.write"):
            self.assertNotIn(banned, script)
        self.assertIsNone(re.search(r"<script[^>]+src=", self.html))
        data = self.html.split('<script type="application/json" id="data">', 1)[1].split("</script>", 1)[0]
        self.assertNotIn("<", data)

    def test_page_states_provenance_and_what_did_not_run(self):
        d = self.demo.page_data()
        self.assertIn("recorded_at_utc", d["provenance"]["dm_dynamic"])
        self.assertIn("Recorded, then replayed", self.html)
        self.assertTrue(d["not_run"])
        self.assertIn("C-investigation", [s["id"] for s in d["scenarios"]])


if __name__ == "__main__":
    unittest.main()
