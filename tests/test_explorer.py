"""The public page must be generated from the committed report, offline and injection-safe."""
import json
from pathlib import Path
import re
import unittest

from turnwise_lab import explorer

ROOT = Path(__file__).resolve().parents[1]


class ExplorerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = json.loads((ROOT / "reports" / "arena.json").read_text(encoding="utf-8"))
        cls.html = explorer.render(cls.report)

    def test_committed_page_is_generated_from_committed_report(self):
        self.assertEqual((ROOT / "demo" / "index.html").read_text(encoding="utf-8"), self.html)

    def test_headline_numbers_come_from_the_report(self):
        h = explorer.headline(self.report)
        arms = {a["id"]: a["summary"] for a in self.report["arms"]}
        self.assertEqual(h["joint_silent"], arms["joint_router"]["outcomes"]["silent_miss"])
        self.assertEqual(h["executed"], 0)
        self.assertIn(f"{h['oracle_zero_pct']}%", self.html)
        self.assertIn(f"{h['executed']} / {h['forged']}", self.html)
        self.assertNotIn("{{", self.html)

    def test_page_is_offline_and_never_injects_html(self):
        script = self.html.split('<script>', 1)[1]
        for banned in ("fetch(", "XMLHttpRequest", "innerHTML", "eval(", "document.write"):
            self.assertNotIn(banned, script)
        self.assertIsNone(re.search(r"<script[^>]+src=", self.html))
        self.assertIsNone(re.search(r"<link[^>]+stylesheet", self.html))

    def test_embedded_data_cannot_close_the_script_tag(self):
        hostile = json.loads(json.dumps(self.report))
        hostile["turns"][0]["text"] = "</script><script>alert(1)</script>"
        html = explorer.render(hostile)
        data = html.split('<script type="application/json" id="data">', 1)[1].split("</script>", 1)[0]
        self.assertNotIn("<", data)
        self.assertIn("alert(1)", json.dumps(json.loads(data)))

    def test_every_turn_and_arm_is_on_the_page(self):
        data = explorer.page_data(self.report)
        self.assertEqual(len(data["turns"]), self.report["inputs"]["turns"])
        self.assertEqual({a["id"] for a in data["arms"]}, set(explorer.SHORT))
        self.assertTrue(all(len(t["r"]) == len(data["arms"]) for t in data["turns"]))


if __name__ == "__main__":
    unittest.main()
