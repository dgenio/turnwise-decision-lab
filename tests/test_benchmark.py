import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from turnwise_lab.benchmark import run_benchmark,render_markdown,simple_rule
from turnwise_lab.learning import TinyMultinomialNB

class TrainedBenchmarkTests(unittest.TestCase):
    def test_fit_requires_nonempty_and_predict_requires_fit(self):
        n=TinyMultinomialNB()
        with self.assertRaises(RuntimeError):n.predict('abc')
        with self.assertRaises(ValueError):n.fit([])

    def test_classifier_is_genuinely_learned_not_fixtures(self):
        m=TinyMultinomialNB().fit([{'text':'launch run flow validation','label':'flow'},
                                   {'text':'synthesize diagnosis interpretation','label':'llm'}])
        self.assertEqual(m.predict('validation flow').route,'flow')
        self.assertEqual(m.predict('diagnosis interpretation').route,'llm')
        self.assertAlmostEqual(sum(m.predict('anything').probabilities.values()),1,places=8)

    def test_deterministic_replay(self):
        a=run_benchmark();b=run_benchmark()
        # Elapsed CPU microtimes intentionally vary; only verify measured outputs.
        for arm_a,arm_b in zip(a['arms'],b['arms']):
            for unstable in ['local_policy_latency_ms_p50','local_policy_latency_ms_p95']:
                arm_a.pop(unstable,None)
                arm_b.pop(unstable,None)
        self.assertEqual(a,b)

    def test_train_test_are_disjoint_and_stable(self):
        out=run_benchmark()
        self.assertEqual(out['train']['count'],60)
        self.assertEqual(out['test']['count'],40)
        self.assertEqual(len(out['train']['sha256']),64)
        self.assertEqual(len(out['arms']),3)
        self.assertEqual([a['classifier_calls'] for a in out['arms']],[0,40,23])
        self.assertEqual([a['classifier_selected_routes'] for a in out['arms']],[0,40,2])
        self.assertTrue(all(arm['cost_usd'] is None for arm in out['arms']))
        self.assertTrue(all(arm['e2e_task_success'] is None for arm in out['arms']))
        self.assertIn('No hosted decision model or LLM',render_markdown(out))

    def test_cannot_leak_test_data_into_train(self):
        root=Path(__file__).resolve().parents[1]
        a=root/'fixtures/route_train.jsonl'; b=root/'fixtures/route_test.jsonl'
        with TemporaryDirectory() as tmp:
            p=Path(tmp)/'bad.jsonl'
            p.write_bytes(a.read_bytes()+b.read_bytes())
            with self.assertRaises(ValueError):run_benchmark(p,b)

    def test_risk_rule_can_make_false_positives(self):
        # Valid read request, not necessarily an authorized write.
        self.assertEqual(simple_rule({'text':'Look for the latest update'}),'hold')

    def test_invalid_threshold_rejected(self):
        with self.assertRaises(ValueError):run_benchmark(threshold=2)

if __name__=='__main__':unittest.main()
