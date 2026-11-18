"""Evidence-honesty regression tests: comparisons must never claim model accuracy."""
import json
import unittest
from pathlib import Path

from turnwise_lab.evaluate import run_replay, _simple_rules
from turnwise_lab.core import Request, Capability

DATA = json.loads((Path(__file__).parent.parent / 'fixtures' / 'scenarios.json').read_text())

class ReplayTests(unittest.TestCase):
    def test_declares_same_author_fixture_labels_as_nonindependent(self):
        results = run_replay(DATA)
        self.assertEqual(len(results['arms']), 3)
        self.assertIn('authored', results['dataset'])
        self.assertTrue(any('not unbiased' in s or 'not actual' in s or
                            'no classifier quality' in s for s in results['limitations']))
        arm_by_name = {x['arm']: x for x in results['arms']}
        self.assertEqual(arm_by_name['simple_host_rules']['route_contract_matches'], 8)
        self.assertEqual(arm_by_name['fixture_planner_contract_only']['route_contract_matches'], 8)
        self.assertEqual(arm_by_name['fixture_planner_contract_only']['classifier_calls'], 7)
        self.assertEqual(arm_by_name['simple_host_rules']['classifier_calls'], 0)

    def test_empty_or_duplicate_cases_are_rejected(self):
        for rows in ([], [DATA[0], DATA[0]]):
            with self.subTest(rows=len(rows)), self.assertRaises(ValueError):
                run_replay(rows)

    def test_simple_host_rule_never_treats_tool_write_as_approved(self):
        request = Request(text='Delete incident records', tools=(
            Capability('delete_incident_records', 'Delete incident records', side_effect=True),))
        p = _simple_rules(request)
        self.assertEqual(p.path, 'hold')
        self.assertTrue(p.approval_required)

    def test_replay_runs_with_no_api_account(self):
        run = run_replay(DATA)
        self.assertEqual(run['schema_version'], 'replay-v1')
        self.assertTrue(all(x['classifier_calls'] == 0 for x in run['arms']
                            if x['arm'] != 'fixture_planner_contract_only'))

if __name__ == '__main__':
    unittest.main()
