import json
import unittest
from pathlib import Path

from scripts.render_local_demo import render
from turnwise_lab.live_demo import run_demo

ROOT=Path(__file__).resolve().parents[1]

class LiveHTMLTests(unittest.TestCase):
    def test_live_html_is_generated_from_actual_receipts(self):
        self.assertEqual((ROOT/'demo/local-run.html').read_text(encoding='utf-8'),render(run_demo()))
        self.assertIn('generation required',render(run_demo()))
        self.assertIn('approval required',render(run_demo()))

    def test_demo_receipts_mirror_report(self):
        expected=json.dumps(run_demo(),indent=2,sort_keys=True,ensure_ascii=False)+'\n'
        self.assertEqual((ROOT/'demo/live-local-run.json').read_text(encoding='utf-8'),expected)
        self.assertEqual((ROOT/'reports/live-local-run.json').read_text(encoding='utf-8'),expected)

if __name__=='__main__':unittest.main()
