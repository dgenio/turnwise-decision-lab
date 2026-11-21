"""Cache-aware accounting and the batched-native arm (issue #85).

The first three classes are stdlib-only and run in the main CI job. The last one runs the real SDK provider
classes against the offline provider double and needs the pinned frameworks.

These tests pin *mechanisms*: unknown stays unknown, a request's reusable prefix is measured from what was
sent, the batched arm really batches, and every report says how its native arm issued tool calls. They do not
pin which architecture is cheaper: that depends on the billing assumption, which is the point of the report.
"""
from __future__ import annotations

import json
import os
import socket
import unittest
from unittest import mock

from examples.architecture.cost_accounting import (
    ASSUMPTIONS, BILLING_SCHEMA, CACHE_READS, CACHE_READS_AND_WRITES, NO_CACHING, PriceCard, RequestShape,
    billed_usd, billing_totals, billing_units, breakeven_cache_read_multiplier, canonical_request_text,
    shapes_from_exchanges, shared_prefix_len, structural_cost, structural_units)
from examples.architecture.incident_env import TASKS
from examples.architecture.simulated_model import SimulatedInvestigator

try:
    import agents  # noqa: F401
    import llama_index.core  # noqa: F401
    FRAMEWORKS_PRESENT = True
except ImportError:
    if os.environ.get("TURNWISE_REQUIRE_FRAMEWORKS") == "1":
        raise
    FRAMEWORKS_PRESENT = False

CARD = PriceCard(2.0, 0.1, 2.5, 10.0, source="test")
TOOLS = ["service_health", "error_trend", "recent_deploys", "validate_config", "search_docs", "rollback_deploy"]


class BillingUnitsTests(unittest.TestCase):
    def test_reported_usage_is_split_into_fresh_and_cache_read_and_writes_stay_unknown(self):
        units = billing_units({"input_tokens": 1000, "cached_input_tokens": 600, "output_tokens": 50,
                               "reasoning_tokens": 20})
        self.assertEqual(units, {"input_tokens_fresh": 400, "input_tokens_cache_read": 600,
                                 "input_tokens_cache_write": None, "output_tokens": 50, "reasoning_tokens": 20})

    def test_a_request_without_usage_is_unknown_not_zero(self):
        for missing in ({}, None):
            self.assertEqual(set(billing_units(missing).values()), {None})

    def test_invalid_counts_are_unknown(self):
        units = billing_units({"input_tokens": -5, "cached_input_tokens": True, "output_tokens": "12"})
        self.assertIsNone(units["input_tokens_fresh"])
        self.assertIsNone(units["input_tokens_cache_read"])
        self.assertIsNone(units["output_tokens"])

    def test_totals_are_unknown_as_soon_as_one_request_reported_nothing(self):
        ok = {"input_tokens": 100, "cached_input_tokens": 0, "output_tokens": 10, "reasoning_tokens": 0}
        complete = billing_totals([ok, ok], basis="provider-reported")
        self.assertEqual((complete["schema"], complete["basis"], complete["requests"]),
                         (BILLING_SCHEMA, "provider-reported", 2))
        self.assertEqual((complete["input_tokens_fresh"], complete["output_tokens"]), (200, 20))
        self.assertIsNone(complete["input_tokens_cache_write"])
        partial = billing_totals([ok, {}], basis="provider-reported")
        self.assertEqual(partial["requests_without_usage"], 1)
        self.assertIsNone(partial["input_tokens_fresh"])
        self.assertIsNone(partial["output_tokens"])
        self.assertIsNone(billed_usd(partial, CARD))

    def test_billed_cost_prices_each_unit_and_never_guesses(self):
        units = {"input_tokens_fresh": 400_000, "input_tokens_cache_read": 600_000, "input_tokens_cache_write": None,
                 "output_tokens": 50_000}
        self.assertAlmostEqual(billed_usd(units, CARD), 0.4 * 2.0 + 0.6 * 0.1 + 0.05 * 10.0)
        with_writes = dict(units, input_tokens_cache_write=100_000)  # a subset of the fresh input
        self.assertAlmostEqual(billed_usd(with_writes, CARD), 0.3 * 2.0 + 0.1 * 2.5 + 0.6 * 0.1 + 0.05 * 10.0)
        self.assertIsNone(billed_usd(dict(units, output_tokens=None), CARD))

    def test_price_card_rejects_nonsense(self):
        for bad in ((0, 0.1, 2.5, 10), (2, -1, 2.5, 10), (2, 0.1, float("inf"), 10), (2, 0.1, 2.5, True)):
            with self.assertRaises(ValueError):
                PriceCard(*bad)


class RequestShapeTests(unittest.TestCase):
    def test_canonical_text_ignores_key_order_and_transport_settings(self):
        a = {"model": "m1", "max_output_tokens": 10, "instructions": "be brief",
             "tools": [{"name": "t", "type": "function"}], "input": [{"role": "user", "content": "hi"}]}
        b = {"input": [{"content": "hi", "role": "user"}], "tools": [{"type": "function", "name": "t"}],
             "instructions": "be brief", "model": "m2", "temperature": 0}
        self.assertEqual(canonical_request_text(a), canonical_request_text(json.dumps(b).encode()))
        self.assertNotEqual(canonical_request_text(a), canonical_request_text(dict(a, instructions="be long")))

    def test_unparseable_content_shares_nothing(self):
        for content in (b"not json", b"[1, 2]", None):
            self.assertEqual(canonical_request_text(content), "")
        self.assertEqual(shared_prefix_len("", "anything"), 0)

    def test_an_appended_conversation_keeps_its_prefix_and_a_rewritten_one_does_not(self):
        first = {"instructions": "i", "input": [{"role": "user", "content": "task"}]}
        appended = {"instructions": "i", "input": first["input"] + [{"type": "function_call_output", "output": "r1"}]}
        rewritten = {"instructions": "i", "input": [{"role": "user", "content": "packet with r1"}]}
        one, two, three = (canonical_request_text(x) for x in (first, appended, rewritten))
        self.assertEqual(shared_prefix_len(one, two), len(one))
        self.assertLess(shared_prefix_len(one, three), len(one))

    def test_shapes_are_built_from_ledger_records(self):
        shapes = shapes_from_exchanges([
            {"structure": {"request_chars": 100, "shared_prefix_chars": 0}, "usage": {"input_tokens": 25,
             "output_tokens": 5}, "response": {"output": [{"type": "function_call"}, {"type": "function_call"}]}},
            {"structure": {}, "usage": {}, "response": {}}])
        self.assertEqual(shapes[0], RequestShape(100, 0, 25, 5, 2))
        self.assertEqual((shapes[1].input_tokens, shapes[1].tool_calls, shapes[1].shared_share), (None, 0, 0.0))


class StructuralEstimateTests(unittest.TestCase):
    # Two requests; the second repeats the first as an exact prefix (half of its text).
    SHAPES = [RequestShape(1000, 0, 1000, 100), RequestShape(2000, 1000, 2000, 100)]

    def test_shared_prefix_becomes_cache_reads(self):
        units = structural_units(self.SHAPES)
        self.assertEqual([(u["input_tokens_fresh"], u["input_tokens_cache_read"]) for u in units],
                         [(1000, 0), (1000, 1000)])

    def test_cost_under_each_assumption_by_hand(self):
        self.assertAlmostEqual(structural_cost(self.SHAPES, CARD, NO_CACHING), (3000 * 2.0 + 200 * 10.0) / 1e6)
        self.assertAlmostEqual(structural_cost(self.SHAPES, CARD, CACHE_READS),
                               (2000 * 2.0 + 1000 * 0.1 + 200 * 10.0) / 1e6)
        self.assertAlmostEqual(structural_cost(self.SHAPES, CARD, CACHE_READS_AND_WRITES),
                               (2000 * 2.5 + 1000 * 0.1 + 200 * 10.0) / 1e6)

    def test_a_prefix_below_the_minimum_cacheable_length_is_not_read_from_cache(self):
        self.assertAlmostEqual(structural_cost(self.SHAPES, CARD, CACHE_READS, min_cacheable_tokens=1500),
                               structural_cost(self.SHAPES, CARD, NO_CACHING))
        # ...and a prompt below the minimum pays no write premium either (request 1 is 1,000 tokens).
        self.assertAlmostEqual(
            structural_cost(self.SHAPES, CARD, CACHE_READS_AND_WRITES, min_cacheable_tokens=1500),
            (1000 * 2.0 + 2000 * 2.5 + 200 * 10.0) / 1e6)

    def test_a_stable_prefix_is_fresh_once_and_shared_afterwards(self):
        units = structural_units(self.SHAPES, stable_prefix_tokens=5000)
        self.assertEqual([(u["input_tokens_fresh"], u["input_tokens_cache_read"]) for u in units],
                         [(6000, 0), (1000, 6000)])

    def test_unknown_tokens_give_unknown_cost_and_unknown_assumptions_are_refused(self):
        self.assertIsNone(structural_cost([RequestShape(10, 0, None, 1)], CARD, NO_CACHING))
        with self.assertRaises(ValueError):
            structural_cost(self.SHAPES, CARD, "optimistic")
        self.assertEqual(len(ASSUMPTIONS), 3)

    def test_breakeven_multiplier_by_hand(self):
        # a: fresh 2000, read 1000. b: one request of 2600 fresh. Equal input cost when 2000 + 1000c = 2600.
        self.assertAlmostEqual(breakeven_cache_read_multiplier(self.SHAPES, [RequestShape(10, 0, 2600, 1)]), 0.6)


class BatchedNativeTurnTests(unittest.TestCase):
    ARGS = dict(instructions="", task=TASKS["investigate"], tool_results=[], tools=TOOLS)

    def test_the_default_investigator_still_asks_for_one_tool_per_turn(self):
        brain = SimulatedInvestigator()
        self.assertEqual(brain.native_turn(**self.ARGS), [brain.native_step(**self.ARGS)])

    def test_batch_reads_asks_for_every_missing_evidence_read_at_once_then_answers(self):
        brain = SimulatedInvestigator(batch_reads=True)
        turn = brain.native_turn(**self.ARGS)
        self.assertEqual([(a.kind, a.tool) for a in turn],
                         [("tool_call", t) for t in ("error_trend", "recent_deploys", "validate_config")])
        self.assertTrue(all(a.arguments == {"service": "checkout"} for a in turn))
        seen = [json.dumps({"tool": t, "status": "executed", "facts": {}}) for t in ("error_trend", "recent_deploys")]
        later = brain.native_turn(**dict(self.ARGS, tool_results=seen))
        self.assertEqual([a.tool for a in later], ["validate_config"])

    def test_writes_and_answers_are_never_batched(self):
        brain = SimulatedInvestigator(batch_reads=True)
        rollback = brain.native_turn(**dict(self.ARGS, task=TASKS["rollback"]))
        self.assertEqual([(a.kind, a.tool) for a in rollback], [("tool_call", "rollback_deploy")])
        fact = brain.native_turn(**dict(self.ARGS, task=TASKS["severity"]))
        self.assertEqual([a.kind for a in fact], ["answer"])


@unittest.skipUnless(FRAMEWORKS_PRESENT, "both optional agent SDKs are needed")
class CostStructureReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from examples.architecture import cost_structure

        def deny(*args, **kwargs):
            raise AssertionError("the cost-structure report attempted a network connection")

        cls.module = cost_structure
        with mock.patch.object(socket.socket, "connect", deny), mock.patch.object(socket.socket, "connect_ex", deny):
            cls.report = cost_structure.build_report()

    def arms(self, framework):
        return {a["arm"]: a for a in self.report["frameworks"][framework]["arms"]}

    def test_every_arm_ran_offline_and_passed_its_mechanism_checks(self):
        self.assertFalse(self.report["real_inference"])
        self.assertIn("SIMULATED", self.report["label"])
        for framework in self.module.FRAMEWORKS:
            arms = self.arms(framework)
            # Arm S (the shielded native agent, #88) exists for the OpenAI Agents SDK pair only.
            extra = ["S"] if framework in self.module.SHIELDED_FRAMEWORKS else []
            self.assertEqual(list(arms), ["A", "A'", "B"] + extra)
            self.assertEqual({a["verdict"] for a in arms.values()}, {"PASS"}, framework)

    def test_the_report_says_how_each_native_arm_issued_tool_calls_and_the_batched_arm_really_batches(self):
        for framework in self.module.FRAMEWORKS:
            arms = self.arms(framework)
            self.assertEqual(arms["A"]["max_tool_calls_per_response"], 1, framework)
            self.assertIn("sequential", arms["A"]["tool_call_batching"])
            self.assertGreaterEqual(arms["A'"]["max_tool_calls_per_response"], 2, framework)
            self.assertIn("batched", arms["A'"]["tool_call_batching"])
            self.assertLess(arms["A'"]["requests"], arms["A"]["requests"], framework)
            # Same evidence reached the host in both native arms: batching changes round trips, not the work.
            self.assertEqual(sorted(arms["A'"]["host_tool_calls"]), sorted(arms["A"]["host_tool_calls"]), framework)
            self.assertIn("only proposes", arms["B"]["tool_call_batching"])

    def test_an_appended_conversation_reuses_more_prefix_than_a_rebuilt_packet(self):
        for framework in self.module.FRAMEWORKS:
            arms = self.arms(framework)
            native_later = arms["A"]["shared_prefix_share"][1:]
            self.assertTrue(native_later and min(native_later) >= 0.7, (framework, native_later))
            turnwise_later = arms["B"]["shared_prefix_share"][1:]
            self.assertTrue(turnwise_later, framework)
            self.assertLess(max(turnwise_later), min(native_later), framework)

    def test_cost_rows_cover_every_assumption_and_never_report_a_guess_as_zero(self):
        for framework in self.module.FRAMEWORKS:
            rows = self.report["frameworks"][framework]["costs"]
            self.assertEqual({r["assumption"] for r in rows}, set(ASSUMPTIONS))
            for row in rows:
                extra = {"S"} if framework in self.module.SHIELDED_FRAMEWORKS else set()
                self.assertEqual(set(row["usd"]), {"A", "A'", "B"} | extra)
                self.assertTrue(all(v is not None and v > 0 for v in row["usd"].values()), row)
                self.assertEqual(row["min_cacheable_tokens"] is None, row["assumption"] == NO_CACHING)
            base = {r["assumption"]: r for r in rows
                    if r["stable_prefix_tokens"] == 0 and r["min_cacheable_tokens"] in (None, 0)}
            # Caching can only lower the cost of a run whose requests repeat their prefix.
            self.assertLess(base[CACHE_READS]["usd"]["A"], base[NO_CACHING]["usd"]["A"])

    def test_rendered_report_is_labelled_and_states_what_it_is_not(self):
        text = self.module.render(self.report)
        for needle in ("SIMULATED, structural", "NOT a cost measurement", "sequential (1 tool call per response)",
                       "batched (up to", "Nothing here measures answer quality, real cost or real latency."):
            self.assertIn(needle, text)

    def test_smoke_records_carry_billing_units_with_unknown_cache_writes(self):
        record = self.module.run_arm("openai-agents", "conventional", batch_reads=False, model="gpt-6.1-sol")
        billing = record["billing"]
        self.assertEqual((billing["schema"], billing["basis"]), (BILLING_SCHEMA, "synthetic: provider double"))
        self.assertIsNone(billing["input_tokens_cache_write"])
        self.assertEqual(billing["input_tokens_fresh"] + billing["input_tokens_cache_read"],
                         record["usage"]["input_tokens"])
        first, second = record["provider_requests"][:2]
        self.assertEqual(first["structure"]["shared_prefix_chars"], 0)
        self.assertGreater(second["structure"]["shared_prefix_chars"], 0)

    def test_the_default_provider_double_still_returns_one_call_with_its_historical_id(self):
        record = self.module.run_arm("openai-agents", "conventional", batch_reads=False, model="gpt-6.1-sol")
        outputs = [r["response"]["output"] for r in record["provider_requests"]]
        self.assertTrue(all(sum(o["type"] == "function_call" for o in out) <= 1 for out in outputs))


if __name__ == "__main__":
    unittest.main()
