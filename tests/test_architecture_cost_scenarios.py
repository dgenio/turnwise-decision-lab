"""The four-scenario cost aggregate and #85's pre-declared falsifier (stdlib only).

These tests pin the *rule* and the arithmetic of the aggregate on hand-made rows. They do not pin which
architecture comes out cheaper; that is what the report computes. The end-to-end run over the four demo
scenarios needs the pinned SDKs and lives in ``tests/test_architecture_cost_accounting.py``.
"""
from __future__ import annotations

import unittest

from examples.architecture.cost_accounting import CACHE_READS, CACHE_READS_AND_WRITES, NO_CACHING
from examples.architecture.cost_structure import (BATCHED, FALSIFIER_RULE, FALSIFIER_THRESHOLD_PCT,
                                                  REALISTIC_STABLE_PREFIX_TOKENS, aggregate_costs, falsifier_verdict)
from examples.architecture.incident_env import TASKS


def row(stable, assumption, minimum, b_vs_a_batched):
    return {"stable_prefix_tokens": stable, "assumption": assumption, "min_cacheable_tokens": minimum,
            "b_vs_a_batched_pct": b_vs_a_batched}


def deciding(values):
    """The four rows the rule decides on, in report order, with the given B vs A' percentages."""
    keys = [(s, a) for s in REALISTIC_STABLE_PREFIX_TOKENS for a in (CACHE_READS, CACHE_READS_AND_WRITES)]
    return [row(s, a, 1024, v) for (s, a), v in zip(keys, values)]


class FalsifierRuleTests(unittest.TestCase):
    def test_the_rule_is_the_one_issue_85_declared(self):
        self.assertEqual(FALSIFIER_THRESHOLD_PCT, -15.0)
        self.assertEqual(REALISTIC_STABLE_PREFIX_TOKENS, (5_000, 20_000))
        for needle in ("at least 15% below A'", "four demo scenarios", "before the four-scenario numbers were computed",
                       "No-caching rows are reported but do not decide"):
            self.assertIn(needle, FALSIFIER_RULE)
        self.assertEqual(len(TASKS), 4)

    def test_falsified_only_when_every_deciding_row_is_at_or_below_the_threshold(self):
        self.assertEqual(falsifier_verdict(deciding([-15.0, -20.0, -30.0, -16.0]))["verdict"], "FALSIFIED")
        self.assertEqual(falsifier_verdict(deciding([-14.9, 2.0, 10.0, 0.0]))["verdict"], "CONSISTENT")
        self.assertEqual(falsifier_verdict(deciding([-20.0, -20.0, -20.0, -10.0]))["verdict"], "MIXED")

    def test_no_caching_rows_and_prefix_free_rows_never_decide(self):
        rows = deciding([5.0, 5.0, 5.0, 5.0]) + [row(20_000, NO_CACHING, None, -90.0), row(0, CACHE_READS, 1024, -90.0),
                                                 row(5_000, CACHE_READS, 0, -90.0)]
        verdict = falsifier_verdict(rows)
        self.assertEqual(verdict["verdict"], "CONSISTENT")
        self.assertEqual(len(verdict["deciding_rows"]), 4)

    def test_an_unknown_value_makes_the_verdict_not_evaluable_never_a_pass(self):
        self.assertEqual(falsifier_verdict(deciding([-30.0, None, -30.0, -30.0]))["verdict"], "NOT EVALUABLE")
        self.assertEqual(falsifier_verdict([row(0, NO_CACHING, None, -50.0)])["verdict"], "NOT EVALUABLE")


class AggregateTests(unittest.TestCase):
    @staticmethod
    def report(usd_rows):
        rows = [{"stable_prefix_tokens": s, "assumption": a, "min_cacheable_tokens": m, "usd": usd,
                 "b_vs_a_batched_pct": None} for (s, a, m), usd in usd_rows]
        return {"frameworks": {"fw": {"costs": rows}}}

    def test_each_arm_is_summed_row_by_row_and_percentages_are_recomputed_from_the_sums(self):
        key = (5_000, CACHE_READS, 1024)
        reports = {"one": self.report([(key, {"A": 4.0, BATCHED: 2.0, "B": 3.0})]),
                   "two": self.report([(key, {"A": 1.0, BATCHED: 1.0, "B": 0.0})])}
        (agg,) = aggregate_costs(reports, "fw")
        self.assertEqual(agg["usd"], {"A": 5.0, BATCHED: 3.0, "B": 3.0})
        self.assertEqual(agg["b_vs_a_batched_pct"], 0.0)
        self.assertEqual(agg["b_vs_a_pct"], -40.0)
        self.assertEqual(set(agg["per_scenario_b_vs_a_batched_pct"]), {"one", "two"})

    def test_an_unknown_cost_in_any_scenario_stays_unknown_in_the_sum(self):
        key = (0, NO_CACHING, None)
        reports = {"one": self.report([(key, {"A": 1.0, BATCHED: 1.0, "B": None})]),
                   "two": self.report([(key, {"A": 1.0, BATCHED: 1.0, "B": 1.0})])}
        (agg,) = aggregate_costs(reports, "fw")
        self.assertIsNone(agg["usd"]["B"])
        self.assertIsNone(agg["b_vs_a_batched_pct"])

    def test_rows_that_do_not_line_up_are_refused(self):
        reports = {"one": self.report([((0, NO_CACHING, None), {"A": 1.0, BATCHED: 1.0, "B": 1.0})]),
                   "two": self.report([((5_000, NO_CACHING, None), {"A": 1.0, BATCHED: 1.0, "B": 1.0})])}
        with self.assertRaises(ValueError):
            aggregate_costs(reports, "fw")


if __name__ == "__main__":
    unittest.main()
