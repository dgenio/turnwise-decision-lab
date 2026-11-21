"""Stage 0 amendment 1 (#86): definitions pinned on synthetic data with hand-computed values.

No benchmark data is read: the trajectories, tool sources and price tables are written here.
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "research" / "stage0_headroom" / "headroom_amendment1.py"
_SPEC = importlib.util.spec_from_file_location("stage0_amendment1", _PATH)
a1 = importlib.util.module_from_spec(_SPEC)
sys.modules["stage0_amendment1"] = a1
_SPEC.loader.exec_module(a1)
h = a1.h


def call(name, args):
    import json
    return a1.Call(name, json.dumps(args, sort_keys=True), h.is_read_tool(name), h.leaves(args))


class BashMapping(unittest.TestCase):
    def test_names_skip_cd_and_include_the_git_subcommand(self):
        self.assertEqual(a1.bash_call("cd /testbed && grep -rn foo src", "{}").name, "grep")
        self.assertEqual(a1.bash_call("git diff --stat", "{}").name, "git diff")
        self.assertEqual(a1.bash_call("cd /testbed", "{}").name, "cd")

    def test_read_calls(self):
        for command in ("cat a.py", "cd /testbed && grep -rn foo .", "sed -n '1,20p' a.py", "git status",
                        "find . -name '*.py' | head -5", "ls src && wc -l a.py"):
            with self.subTest(command=command):
                self.assertTrue(a1.bash_call(command, "{}").read)
        for command in ("sed -i 's/a/b/' a.py", "cat a.py > b.py", "grep foo a.py >> log", "echo x | tee f",
                        "python -c 'print(1)'", "git commit -m x", "cd /testbed", "grep foo a.py 2>&1"):
            with self.subTest(command=command):
                self.assertFalse(a1.bash_call(command, "{}").read)

    def test_leaves_drop_programs_flags_and_operators(self):
        self.assertEqual(a1.bash_call("cd /testbed && grep -rn 'def f' src/x.py | head -5", "{}").leaves,
                         ["/testbed", "def f", "src/x.py"])
        self.assertEqual(a1.bash_call("git diff --stat HEAD", "{}").leaves, ["HEAD"])

    def test_unparseable_commands_are_neither_read_nor_determinable(self):
        c = a1.bash_call("cat 'unterminated", "{}")
        self.assertFalse(c.read)
        self.assertIsNone(c.leaves)
        self.assertFalse(c.determinable("anything"))


class SameSemanticsAsTheFrozenParser(unittest.TestCase):
    def test_single_call_records_build_exactly_what_headroom_parse_trajectory_builds(self):
        # On all 1,092 tau-bench train trajectories this held field for field (checked during development).
        record = {"task_id": 3, "reward": 1, "traj": [
            {"role": "system", "content": "policy"},
            {"role": "user", "content": "I am u_1, order #W2"},
            {"role": "assistant", "content": "", "tool_calls": [{"function": {
                "name": "get_user_details", "arguments": '{"user_id": "u_1"}'}}]},
            {"role": "tool", "name": "get_user_details", "content": "{orders: [#W2, #W3]}"},
            {"role": "assistant", "content": "", "tool_calls": [{"function": {
                "name": "get_order_details", "arguments": '{"order_id": "#W3"}'}}]},
            {"role": "tool", "name": "get_order_details", "content": "{status: pending}"},
            {"role": "assistant", "content": "Done."}]}
        frozen = h.parse_trajectory(record, "retail", "m", 7)
        events = []
        for m in record["traj"][1:]:
            if m["role"] == "assistant":
                fc = h._first_call(m)
                events.append(a1.Event("assistant", m["content"], [] if fc is None else
                                       [a1.Call(fc[0], fc[2], h.is_read_tool(fc[0]), h.leaves(fc[1]))]))
            elif m["role"] == "tool":
                events.append(a1.Event("tool", m["content"], name=m["name"]))
            else:
                events.append(a1.Event("user", m["content"]))
        mine = a1.build_trajectory(events, "retail", "m", 3, 1.0, frozen.prefix_tokens)
        fields = ("role", "tokens", "call_tokens", "tool", "key", "determinable", "determinable_before_run",
                  "first_of_run")
        self.assertEqual([[getattr(x, f) for f in fields] for x in frozen.messages],
                         [[getattr(x, f) for f in fields] for x in mine.messages])
        self.assertAlmostEqual(h.cost(frozen, h.CARDS["P1"]), h.cost(mine, h.CARDS["P1"]))


class MultiCallTurns(unittest.TestCase):
    def test_a_turn_is_determinable_and_read_only_when_every_call_is(self):
        events = [a1.Event("user", "my order is #W1 and my id is u_7"),
                  a1.Event("assistant", "", [call("get_order_details", {"order_id": "#W1"}),
                                             call("get_user_details", {"user_id": "u_7"})]),
                  a1.Event("assistant", "", [call("get_order_details", {"order_id": "#W1"}),
                                             call("cancel_order", {"order_id": "#W9"})])]
        t = a1.build_trajectory(events, "tau2-retail", "m", 1, 1.0, 10)
        first, second = t.messages[1], t.messages[2]
        self.assertEqual(first.tool, "get_order_details")
        self.assertTrue(first.determinable and first.read_call)
        self.assertFalse(second.determinable)  # #W9 is not in context
        self.assertFalse(second.read_call)  # cancel_order is not a read tool
        expected = sum(h.tokens(c.name) + h.tokens(c.raw) for c in events[1].calls)
        self.assertEqual(first.call_tokens, expected)

    def test_d0_needs_a_read_call_not_just_a_read_first_name(self):
        events = [a1.Event("user", "order #W1"),
                  a1.Event("assistant", "", [call("get_order_details", {"order_id": "#W1"}),
                                             call("cancel_order", {"order_id": "#W1"})])]
        t = a1.build_trajectory(events, "tau2-retail", "m", 1, 1.0, 10)
        sel = a1.selections(t, {"USER": {"tool": "get_order_details", "support": 20, "share": 1.0}})
        self.assertEqual(sel["D1"], frozenset({1}))
        self.assertEqual(sel["D0"], frozenset())  # a write call rides along, so the host rule cannot issue it


class Tau2Transcript(unittest.TestCase):
    def test_user_side_tools_are_not_in_the_agents_transcript(self):
        messages = [
            {"role": "assistant", "content": "Hi"},
            {"role": "user", "content": "my phone is 555"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "c1", "name": "get_customer_by_phone", "arguments": {"phone": "555"}, "requestor": "assistant"}]},
            {"role": "tool", "id": "c1", "content": "{customer}", "requestor": "assistant"},
            {"role": "user", "content": "", "tool_calls": [
                {"id": "u1", "name": "toggle_airplane_mode", "arguments": {}, "requestor": "user"}]},
            {"role": "tool", "id": "u1", "content": "airplane off", "requestor": "user"},
            {"role": "user", "content": "done"}]
        events = a1.tau2_events(messages)
        self.assertEqual([e.role for e in events], ["assistant", "user", "assistant", "tool", "user"])
        self.assertEqual(events[3].name, "get_customer_by_phone")
        self.assertNotIn("airplane", " ".join(e.text for e in events))

    def test_tool_definitions_are_parsed_never_executed(self):
        source = ("raise SystemExit('must not be executed')\n"
                  "class Tools:\n"
                  "    @is_tool(ToolType.READ)\n"
                  "    def get_x(self, x_id: str) -> str:\n"
                  "        '''Get x.'''\n"
                  "    # @is_tool(ToolType.THINK)\n"
                  "    def think(self, t: str):\n"
                  "        pass\n"
                  "    @is_tool(ToolType.WRITE)\n"
                  "    def cancel_x(self, x_id: str):\n"
                  "        '''Cancel x.'''\n")
        with tempfile.TemporaryDirectory() as tmp:
            pins = {}
            for domain, (rel, _) in a1.TAU2_TOOLS.items():
                path = Path(tmp) / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(source, encoding="utf-8")
                pins[domain] = (rel, __import__("hashlib").sha256(source.encode()).hexdigest())
            original = a1.TAU2_TOOLS
            a1.TAU2_TOOLS = pins
            try:
                tokens, types = a1.tau2_tool_definitions(Path(tmp))
            finally:
                a1.TAU2_TOOLS = original
        self.assertEqual(types["tau2-airline"], {"get_x": "READ", "cancel_x": "WRITE"})
        self.assertGreater(tokens["tau2-airline"], 0)


class CodingTrajectory(unittest.TestCase):
    def steps(self):
        sys_u = [{"role": "system", "content": "shell"}, {"role": "user", "content": "fix src/a.py"}]
        a = {"role": "assistant", "content": "look", "tool_calls": [
            {"id": "t1", "function": {"name": "bash", "arguments": '{"command": "cat src/a.py"}'}}]}
        r = {"role": "tool", "tool_call_id": "t1", "content": "def f(): pass"}
        return [{"step_index": 1, "total_steps": 2, "messages": sys_u, "target_tier": "low"},
                {"step_index": 2, "total_steps": 2, "messages": sys_u + [a, r], "target_tier": "high"}]

    def test_final_turn_is_unobserved_and_never_deleted(self):
        t = a1.swe_trajectory("i1", self.steps())
        self.assertEqual([m.role for m in t.messages], ["user", "assistant", "tool", "assistant"])
        self.assertEqual(t.messages[1].tool, "cat")
        self.assertTrue(t.messages[1].determinable and t.messages[1].read_call)
        self.assertEqual(t.messages[-1].tokens, 0)
        self.assertNotIn(3, a1.selections(t, {})["D2"])

    def test_inconsistent_or_incomplete_instances_are_excluded(self):
        good = [dict(r, benchmark="swebench", instance_id="ok") for r in self.steps()]
        broken = [dict(r, benchmark="swebench", instance_id="bad") for r in self.steps()]
        broken[1] = dict(broken[1], messages=[{"role": "system", "content": "different"}])
        missing = [dict(self.steps()[0], benchmark="swebench", instance_id="gap")]
        complete, excluded = a1.instances(good + broken + missing, "swebench")
        self.assertEqual(list(complete), ["ok"])
        self.assertEqual(sorted(excluded), ["bad", "gap"])


class TierCeiling(unittest.TestCase):
    TIERS = {"low": "cheap", "high": "strong"}
    PRICES = {"cheap": {"input_per_m": 1.0, "cache_write_per_m": 0.5, "cache_read_per_m": 0.1, "output_per_m": 2.0},
              "strong": {"input_per_m": 10.0, "cache_write_per_m": 12.0, "cache_read_per_m": 1.0,
                         "output_per_m": 40.0}}

    def test_hand_computed_costs_with_per_model_cache(self):
        steps = [(2000, 100, "high"), (3000, 100, "low"), (4000, 100, "low")]
        # all high: 2000*12 + 100*40 ; then read 2000 at 1, 1000 fresh at 12, 100*40 ; then read 3000, 1000 fresh
        all_high = (2000 * 12 + 4000) + (2000 * 1 + 1000 * 12 + 4000) + (3000 * 1 + 1000 * 12 + 4000)
        self.assertAlmostEqual(a1.tier_cost(steps, self.TIERS, self.PRICES, all_high=True), all_high / 1e6)
        # tiered: high step as above; switch to cheap reads nothing (fresh at max(1.0, 0.5) = 1.0); then cheap reads
        tiered = (2000 * 12 + 4000) + (3000 * 1.0 + 200) + (3000 * 0.1 + 1000 * 1.0 + 200)
        self.assertAlmostEqual(a1.tier_cost(steps, self.TIERS, self.PRICES, all_high=False), tiered / 1e6)

    def test_short_inputs_are_not_read_from_cache(self):
        steps = [(500, 0, "high"), (800, 0, "high")]
        self.assertAlmostEqual(a1.tier_cost(steps, self.TIERS, self.PRICES, all_high=True),
                               (500 * 12 + 800 * 12) / 1e6)

    def test_outputs_come_from_the_next_steps_new_assistant_message(self):
        steps = CodingTrajectory().steps()
        ts = a1.tier_steps(steps)
        self.assertEqual(ts[1][1], 0)  # last step: output unobserved
        self.assertEqual(ts[0][1], a1.message_tokens(steps[1]["messages"][2]))


class CombinedVerdict(unittest.TestCase):
    def v(self, d1, d0, batching):
        return {"D1": d1, "D0": d0, "batching": batching}

    def test_rule_order(self):
        low = {"airline": self.v(0.1, 0.0, 0.01), "tau2-telecom": self.v(0.1, 0.0, 0.01)}
        self.assertEqual(a1.verdict(low, {"swebench": self.v(0.05, 0.0, 0.01)})[0], "STOP")
        mixed = {"airline": self.v(0.3, 0.0, 0.02), "tau2-telecom": self.v(0.1, 0.0, 0.01)}
        self.assertEqual(a1.verdict(mixed, {"swebench": self.v(0.05, 0.0, 0.01)})[0], "SHRINK")
        win = {"airline": self.v(0.3, 0.2, 0.02), "tau2-telecom": self.v(0.1, 0.0, 0.01)}
        self.assertEqual(a1.verdict(win, {"swebench": self.v(0.05, 0.0, 0.01)})[0], "PROCEED")
        hold = {"airline": self.v(0.3, 0.1, 0.02), "tau2-telecom": self.v(0.1, 0.0, 0.01)}
        self.assertEqual(a1.verdict(hold, {"swebench": self.v(0.05, 0.0, 0.01)})[0], "HOLD")

    def test_coding_d0_above_batching_blocks_shrink_but_cannot_proceed(self):
        noncoding = {"airline": self.v(0.3, 0.0, 0.02)}
        self.assertEqual(a1.verdict(noncoding, {"swebench": self.v(0.2, 0.2, 0.01)})[0], "HOLD")


class DataHandling(unittest.TestCase):
    def test_files_with_a_different_hash_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            for rel in a1.TWIN_FILES:
                (Path(tmp) / rel).parent.mkdir(parents=True, exist_ok=True)
                (Path(tmp) / rel).write_text("{}")
            with self.assertRaises(SystemExit) as raised:
                a1.load_twin(Path(tmp))
        self.assertIn("SHA-256", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
