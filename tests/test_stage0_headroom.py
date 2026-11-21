"""The Stage 0 headroom script implements its frozen protocol (issue #86). Stdlib only, no external data.

These tests use tiny synthetic trajectories with hand-computed costs. They pin the definitions in
research/stage0_headroom/PROTOCOL.md: the token estimator, the task split, what counts as determinable, the
cache-aware cost model, what deleting or merging a turn does, the D0 rule thresholds and the order of the
decision rule. They say nothing about any real trajectory.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "research" / "stage0_headroom" / "headroom.py"
_SPEC = importlib.util.spec_from_file_location("stage0_headroom", _PATH)
h = importlib.util.module_from_spec(_SPEC)
sys.modules["stage0_headroom"] = h
_SPEC.loader.exec_module(h)

CARD = h.Card(fresh=2.0, cached=1.0, output=10.0, min_cacheable=0)


def call(name: str, arguments: dict, content: str | None = None) -> dict:
    return {"role": "assistant", "content": content,
            "tool_calls": [{"id": "c", "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}]}


def result(name: str, content: str) -> dict:
    return {"role": "tool", "name": name, "tool_call_id": "c", "content": content}


def record(messages: list[dict], *, task_id: int = 0, reward: float = 1.0) -> dict:
    return {"task_id": task_id, "reward": reward, "trial": 0, "info": {},
            "traj": [{"role": "system", "content": "s" * 40}] + messages}


def parse(messages: list[dict], **kwargs):
    # System prompt 40 characters = 10 tokens; 90 tokens of tool definitions: a 100-token stable prefix.
    return h.parse_trajectory(record(messages, **kwargs), "retail", "m", 90)


USER = {"role": "user", "content": ("order A1 please " + "x" * 40)[:40]}  # 10 tokens, mentions A1
LOOKUP = call("get_x", {"id": "A1"})  # name 5 chars -> 2 tokens; arguments 12 chars -> 3 tokens
REPLY = {"role": "assistant", "content": "r" * 80}  # 20 tokens


class DefinitionsTests(unittest.TestCase):
    def test_token_estimator_is_ceil_chars_over_four(self):
        self.assertEqual([h.tokens(x) for x in (None, "", "a", "abcd", "abcde")], [0, 0, 1, 1, 2])

    def test_split_is_by_task_and_stable(self):
        self.assertEqual(h.split_of("retail", 7), h.split_of("retail", 7))
        splits = {h.split_of(d, t) for d in h.DOMAINS for t in range(40)}
        self.assertEqual(splits, {"train", "eval"})

    def test_read_tools_are_named_by_prefix_only(self):
        self.assertTrue(all(h.is_read_tool(n) for n in ("get_order", "find_user", "list_all", "search_flights")))
        self.assertFalse(any(h.is_read_tool(n) for n in ("think", "calculate", "cancel_order", "transfer_to_human_agents",
                                                         None, "")))

    def test_determinable_needs_every_string_and_number_leaf_in_context(self):
        context = "my order is #w123 and the zip is 19122"
        self.assertTrue(h.determinable({"order_id": "#W123", "zip": 19122, "flags": [True, None]}, context))
        self.assertTrue(h.determinable({}, context))
        self.assertFalse(h.determinable({"order_id": "#W123", "reason": "no longer needed"}, context))
        self.assertTrue(h.determinable({"amount": 19122.0}, context))

    def test_assistant_text_and_the_system_prompt_are_never_a_source(self):
        told_by_assistant = parse([{"role": "user", "content": "hello"}, {"role": "assistant", "content": "is it B2?"},
                                   {"role": "user", "content": "yes"}, call("get_x", {"id": "B2"})])
        self.assertFalse(told_by_assistant.messages[-1].determinable)
        from_tool_result = parse([USER, LOOKUP, result("get_x", "linked order B2"), call("get_y", {"id": "b2"})])
        self.assertTrue(from_tool_result.messages[-1].determinable)

    def test_turn_keys_and_runs(self):
        traj = parse([USER, LOOKUP, result("get_x", "ok"), call("get_y", {"id": "A1"}), result("get_y", "ok"),
                      REPLY, USER, REPLY])
        turns = [m for m in traj.messages if m.is_model_turn]
        self.assertEqual([m.key for m in turns], ["START", "TOOL:get_x", "TOOL:get_y", "USER"])
        self.assertEqual([m.first_of_run for m in turns], [True, False, False, False])
        self.assertTrue(turns[1].determinable_before_run)


class CostModelTests(unittest.TestCase):
    def test_original_cost_by_hand(self):
        traj = parse([USER, LOOKUP, result("get_x", "y" * 40), REPLY])
        self.assertEqual(traj.prefix_tokens, 100)
        # Turn 1: input 110, nothing cached, output 5. Turn 2: input 125, reads 110, 15 fresh, output 20.
        self.assertAlmostEqual(h.cost(traj, CARD) * 1e6, (110 * 2 + 5 * 10) + (15 * 2 + 110 * 1 + 20 * 10))

    def test_a_deleted_turn_keeps_its_call_in_the_transcript_and_is_not_billed_as_output(self):
        traj = parse([USER, LOOKUP, result("get_x", "y" * 40), REPLY])
        # Only the reply is a model call: input 100 + 10 + 5 (the call) + 10 = 125, all fresh, output 20.
        self.assertAlmostEqual(h.cost(traj, CARD, deleted=frozenset({1})) * 1e6, 125 * 2 + 20 * 10)

    def test_narration_next_to_a_deleted_call_leaves_the_transcript(self):
        chatty = parse([USER, call("get_x", {"id": "A1"}, content="n" * 400), result("get_x", "y" * 40), REPLY])
        quiet = parse([USER, LOOKUP, result("get_x", "y" * 40), REPLY])
        self.assertGreater(h.cost(chatty, CARD), h.cost(quiet, CARD))
        self.assertAlmostEqual(h.cost(chatty, CARD, deleted=frozenset({1})), h.cost(quiet, CARD, deleted=frozenset({1})))

    def test_batching_moves_the_merged_call_into_the_first_turns_output(self):
        traj = parse([USER, LOOKUP, result("get_x", "y" * 40), call("get_y", {"id": "A1"}),
                      result("get_y", "z" * 40), REPLY])
        self.assertAlmostEqual(h.cost(traj, CARD) * 1e6, 270 + (15 * 2 + 110 + 5 * 10) + (15 * 2 + 125 + 20 * 10))
        merged = h.selections(traj, {})["batching"]
        self.assertEqual(merged, {3: 1})
        # First turn now outputs both calls (10 tokens); the reply reads 110 and has 30 fresh tokens.
        self.assertAlmostEqual(h.cost(traj, CARD, merged=merged) * 1e6, (110 * 2 + 10 * 10) + (30 * 2 + 110 + 20 * 10))

    def test_a_call_that_needs_the_previous_result_is_not_merged(self):
        traj = parse([USER, LOOKUP, result("get_x", "linked order B2"), call("get_y", {"id": "B2"}),
                      result("get_y", "ok"), REPLY])
        self.assertEqual(h.selections(traj, {})["batching"], {})

    def test_minimum_cacheable_length_and_cache_lapse_at_user_messages(self):
        traj = parse([USER, REPLY, USER, REPLY])
        warm = h.cost(traj, CARD)
        self.assertAlmostEqual(h.cost(traj, h.Card(2.0, 1.0, 10.0, min_cacheable=10_000)),
                               h.cost(traj, h.Card(2.0, 2.0, 10.0, min_cacheable=0)))
        lapsed = h.cost(traj, h.Card(2.0, 1.0, 10.0, 0, lapse_at_user=True))
        self.assertGreater(lapsed, warm)
        self.assertAlmostEqual(lapsed, h.cost(traj, h.Card(2.0, 2.0, 10.0, 0)))  # every turn follows a user message


class OracleTests(unittest.TestCase):
    def trajectories(self, n: int, follow: str = "get_y"):
        return [parse([USER, LOOKUP, result("get_x", "ok"), call(follow, {"id": "A1"}), result(follow, "ok"), REPLY],
                      task_id=i) for i in range(n)]

    def test_rules_need_support_share_and_a_read_tool(self):
        self.assertEqual(h.mine_rules(self.trajectories(h.RULE_MIN_SUPPORT - 1))["retail"], {})
        rules = h.mine_rules(self.trajectories(h.RULE_MIN_SUPPORT))["retail"]
        self.assertEqual(rules["START"]["tool"], "get_x")
        self.assertEqual(rules["TOOL:get_x"]["tool"], "get_y")
        self.assertNotIn("TOOL:get_y", rules)  # the most common next action there is a reply, not a tool
        mixed = self.trajectories(18) + self.trajectories(3, follow="get_z")  # 18 of 21 = 86% < 90%
        self.assertNotIn("TOOL:get_x", h.mine_rules(mixed)["retail"])
        writes = self.trajectories(h.RULE_MIN_SUPPORT, follow="cancel_order")
        self.assertNotIn("TOOL:get_x", h.mine_rules(writes)["retail"])
        failed = [parse([USER, LOOKUP, result("get_x", "ok"), REPLY], task_id=i, reward=0.0) for i in range(40)]
        self.assertEqual(h.mine_rules(failed)["retail"], {})

    def test_oracles_nest_and_d0_counts_false_fires(self):
        rules = h.mine_rules(self.trajectories(h.RULE_MIN_SUPPORT))["retail"]
        hit = self.trajectories(1)[0]
        sel = h.selections(hit, rules)
        self.assertEqual((sel["D2"], sel["D1"], sel["D0"]), (frozenset({1, 3}),) * 3)
        self.assertEqual((sel["d0_fires"], sel["d0_correct"]), (2, 2))
        # The agent replied where the rule expected get_y, and its first call was not determinable.
        miss = parse([{"role": "user", "content": "hello"}, call("get_x", {"id": "Z9"}), result("get_x", "ok"), REPLY])
        sel = h.selections(miss, rules)
        self.assertEqual((sel["D2"], sel["D1"], sel["D0"]), (frozenset({1}), frozenset(), frozenset()))
        self.assertEqual((sel["d0_fires"], sel["d0_correct"]), (2, 0))

    def test_summary_shares_and_intervals(self):
        trajectories = self.trajectories(30)
        rules = h.mine_rules(trajectories)
        summary = h.summarise(h.analyse(trajectories, rules), intervals=True)
        d2 = summary["oracles"]["D2"]
        self.assertEqual(summary["model_turns"], 90)
        self.assertAlmostEqual(d2["turn_share"], 2 / 3, places=3)
        self.assertTrue(0 < d2["cost_share"]["P3"] < 1)
        low, high = d2["cost_share_interval_P1"]
        self.assertLessEqual(low, d2["cost_share"]["P1"])
        self.assertGreaterEqual(high, d2["cost_share"]["P1"])
        self.assertEqual(summary["d0_fires"]["false_fire_rate"], 0.0)

    def test_decision_rule_order(self):
        def domain(d1, d0, batching):
            return {"oracles": {name: {"cost_share": {"P1": value}} for name, value in
                                (("D1", d1), ("D0", d0), ("batching", batching))}}

        self.assertEqual(h.verdict({"a": domain(0.10, 0.02, 0.05), "b": domain(0.14, 0.01, 0.0)})[0],
                         "STOP pending a coding set")
        self.assertEqual(h.verdict({"a": domain(0.30, 0.02, 0.05), "b": domain(0.20, 0.01, 0.01)})[0], "SHRINK")
        self.assertEqual(h.verdict({"a": domain(0.30, 0.16, 0.05), "b": domain(0.20, 0.01, 0.02)})[0], "PROCEED")
        self.assertEqual(h.verdict({"a": domain(0.30, 0.10, 0.05), "b": domain(0.20, 0.01, 0.02)})[0], "HOLD")
        self.assertEqual(h.verdict({"a": domain(None, 0.1, 0.1)})[0], "INCONCLUSIVE")


class DataHandlingTests(unittest.TestCase):
    def test_tool_definitions_are_parsed_as_literals_and_never_executed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tools = Path(tmp) / "tau_bench" / "envs" / "retail" / "tools"
            tools.mkdir(parents=True)
            (tools / "__init__.py").write_text("raise SystemExit('must not be imported')\n")
            (tools / "get_x.py").write_text(
                "raise SystemExit('must not be executed')\n"
                "class GetX:\n    @staticmethod\n    def get_info():\n"
                "        return {'type': 'function', 'function': {'name': 'get_x', 'parameters': {}}}\n")
            (tools / "odd.py").write_text("class Odd:\n    @staticmethod\n    def get_info():\n        return build()\n")
            total, problems = h.tool_definition_tokens(Path(tmp), "retail")
        self.assertGreater(total, 0)
        self.assertEqual(problems, ["retail/odd.py: ValueError"])

    def test_a_file_with_a_different_hash_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "historical_trajectories"
            directory.mkdir()
            for name in h.FILES:
                (directory / name).write_text("[]")
            with self.assertRaises(SystemExit) as raised:
                h.load(Path(tmp), "eval")
        self.assertIn("refusing to run", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
