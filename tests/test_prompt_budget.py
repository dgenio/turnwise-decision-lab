"""Prospective prompt-budget invariants; no tokenizer download or inference."""
from dataclasses import replace
import unittest
from unittest.mock import patch

from turnwise_lab.agent import context as cx
from turnwise_lab.agent.contracts import Decision, Observation
from turnwise_lab.agent.host import Host, Limits
from turnwise_lab.agent.loop import TurnState, execute_user_turn
from turnwise_lab.agent.providers import LocalGenerator, RuleContextSelector, ScriptedDecider
from turnwise_lab.agent.world import IncidentWorld
from turnwise_lab.local_models import Generation


class ToyLM:
    """An exact character tokenizer with a deliberately expensive chat template."""
    version = "test-character-tokenizer"

    def __init__(self):
        self.generated = []

    def chat(self, messages):
        return "<chat>" + "".join(m["role"] + ":" + m["content"] + "\n" for m in messages) + "assistant:"

    def count_tokens(self, text):
        return len(text)

    def generate(self, text, max_new_tokens):
        self.generated.append((text, max_new_tokens))
        return Generation("test response", len(text), 2, 0, 0, "eos")


class PromptBudgetTests(unittest.TestCase):
    def setUp(self):
        self.host = Host(IncidentWorld())
        self.lm = ToyLM()

    def assemble(self, state=None, proposed=(), budget=2200, permitted=None, **kw):
        return cx.assemble(state or TurnState("new", "hello"), "heavy", list(proposed),
                           self.host.permitted_blocks if permitted is None else permitted, "test",
                           count_tokens=self.lm.count_tokens,
                           count_messages=lambda m: self.lm.count_tokens(self.lm.chat(m)), budget=budget, **kw)

    def test_mandatory_overflow_preserves_instructions_and_full_request(self):
        question = "a long new request " * 300
        p = self.assemble(TurnState("new", question), budget=700)
        self.assertEqual(p.budget_status, "mandatory_overflow")
        self.assertFalse(p.can_generate)
        self.assertIn(question, p.text())
        self.assertTrue({"core_instructions", "safety_policy"} <= {b["id"] for b in p.included})
        self.assertGreater(p.measured_tokens, p.budget)

    def test_exact_chat_count_and_estimate_are_separate(self):
        p = self.assemble()
        self.assertEqual(p.measured_tokens, self.lm.count_tokens(self.lm.chat(p.messages)))
        self.assertEqual(p.tokens, p.measured_tokens)
        self.assertGreater(p.measured_tokens, p.estimated_tokens)
        self.assertEqual(p.budget_status, "within_budget")
        self.assertTrue(p.can_generate)

    def test_chat_wrapper_alone_can_exceed_budget(self):
        p = self.assemble()
        content_only = sum(len(m["content"]) for m in p.messages)
        self.assertLess(content_only, p.measured_tokens)
        blocked = self.assemble(budget=content_only)
        self.assertEqual(blocked.budget_status, "mandatory_overflow")

    def test_zero_budget_is_not_replaced_with_the_default(self):
        p = self.assemble(budget=0)
        self.assertEqual(p.budget, 0)
        self.assertEqual(p.budget_status, "mandatory_overflow")
        for invalid in (-1, 1.5, True):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.assemble(budget=invalid)

    def test_optional_blocks_trim_by_exact_count(self):
        minimal = self.assemble()
        p = self.assemble(proposed=["tool_catalog", "response_style"], budget=minimal.tokens)
        self.assertTrue(p.can_generate)
        self.assertLessEqual(p.measured_tokens, p.budget)
        self.assertEqual({b["id"] for b in p.included}, {"core_instructions", "safety_policy"})
        self.assertEqual([e["id"] for e in p.excluded if e["reason"] == "over_budget"],
                         ["tool_catalog", "response_style"])

    def test_long_tool_result_is_dropped_whole_and_evidence_omission_recorded(self):
        state = TurnState("new", "summarise the evidence", observations=[
            Observation(0, "call", "call_tool", "search_runbooks", {}, "ok", facts={"note": "long note " * 1500})])
        p = self.assemble(state, ["latest_tool_result"], budget=1000)
        self.assertTrue(p.can_generate)
        self.assertNotIn("latest_tool_result", {b["id"] for b in p.included})
        self.assertIn({"id": "latest_tool_result", "reason": "over_budget", "source": "tool output"}, p.omitted_evidence)
        self.assertNotIn("long note", p.text())

    def test_dependencies_are_transitive_and_respect_permissions(self):
        # Exercise a three-block chain using existing host block types.
        original = cx.BLOCKS_BY_ID
        blocks = tuple(replace(b, depends_on=("recent_messages",)) if b.id == "response_style" else
                       replace(b, depends_on=("incident_record",)) if b.id == "recent_messages" else b
                       for b in cx.BLOCKS)
        state = TurnState("new", "hello", conversation=[{"role": "user", "content": "prior turn"}])
        with patch.object(cx, "BLOCKS", blocks), patch.object(cx, "BLOCKS_BY_ID", {b.id: b for b in blocks}):
            p = self.assemble(state, ["response_style"])
            self.assertTrue({"response_style", "recent_messages", "incident_record"} <= {b["id"] for b in p.included})
            p = self.assemble(state, ["response_style"], permitted=self.host.permitted_blocks - {"incident_record"})
            self.assertNotIn("response_style", {b["id"] for b in p.included})
            self.assertNotIn("recent_messages", {b["id"] for b in p.included})
            self.assertTrue(any(e["id"] == "response_style" and e["reason"] == "missing_dependency" for e in p.excluded))
        self.assertIs(cx.BLOCKS_BY_ID, original)

    def test_dropping_dependency_also_drops_dependents(self):
        state = TurnState("new", "hello", observations=[
            Observation(0, "a", "call_tool", "one", {}, "ok", facts={"a": "old"}),
            Observation(1, "b", "call_tool", "two", {}, "ok", facts={"b": "x" * 2000})])
        # Make the dependency cheaper to drop than its dependent.
        blocks = tuple(replace(b, priority=1) if b.id == "latest_tool_result" else b for b in cx.BLOCKS)
        with patch.object(cx, "BLOCKS", blocks), patch.object(cx, "BLOCKS_BY_ID", {b.id: b for b in blocks}):
            p = self.assemble(state, ["earlier_tool_results"], budget=1000)
        self.assertFalse({"latest_tool_result", "earlier_tool_results"} & {b["id"] for b in p.included})
        self.assertTrue(any(e["id"] == "earlier_tool_results" and e["reason"] == "dependency_removed" for e in p.excluded))

    def test_dependency_on_mandatory_block_is_satisfied(self):
        blocks = tuple(replace(b, depends_on=("safety_policy",)) if b.id == "response_style" else b for b in cx.BLOCKS)
        with patch.object(cx, "BLOCKS", blocks), patch.object(cx, "BLOCKS_BY_ID", {b.id: b for b in blocks}):
            p = self.assemble(proposed=["response_style"])
        self.assertIn("response_style", {b["id"] for b in p.included})

    def test_cyclic_optional_dependencies_are_excluded(self):
        blocks = tuple(replace(b, depends_on=("tool_catalog",)) if b.id == "response_style" else
                       replace(b, depends_on=("response_style",)) if b.id == "tool_catalog" else b for b in cx.BLOCKS)
        with patch.object(cx, "BLOCKS", blocks), patch.object(cx, "BLOCKS_BY_ID", {b.id: b for b in blocks}):
            p = self.assemble(proposed=["response_style"])
        self.assertFalse({"response_style", "tool_catalog"} & {b["id"] for b in p.included})

    def test_missing_or_broken_full_prompt_counter_is_unknown(self):
        for counter in (None, lambda m: None, lambda m: -1, lambda m: True,
                        lambda m: 1.5, lambda m: (_ for _ in ()).throw(RuntimeError("private tokenizer error"))):
            with self.subTest(counter=counter):
                p = cx.assemble(TurnState("new", "hello"), "heavy", [], self.host.permitted_blocks, "test",
                                count_tokens=self.lm.count_tokens, count_messages=counter)
                self.assertEqual(p.budget_status, "unknown_token_count")
                self.assertIsNone(p.measured_tokens)
                self.assertFalse(p.can_generate)
                self.assertNotIn("private tokenizer error", str(p.as_json()))

    def test_redaction_happens_before_measurement(self):
        p = self.assemble(TurnState("new", "api_key=sk-abcdef123456 please"))
        self.assertEqual(p.redactions, 1)
        self.assertNotIn("sk-abcdef123456", p.text())
        self.assertEqual(p.measured_tokens, len(self.lm.chat(p.messages)))


class PromptBudgetLoopTests(unittest.TestCase):
    def run_turn(self, lm=None, message="hello", budget=2200):
        lm = lm or ToyLM()
        host = Host(IncidentWorld(), limits=Limits(max_prompt_tokens={"light": budget, "heavy": budget}))
        trace = execute_user_turn(message, host=host, decider=ScriptedDecider([Decision("call_model", model_tier="heavy")]),
                                  context=RuleContextSelector("minimal"), generator=LocalGenerator(lm, lm), turn_id="new")
        return trace, lm

    def test_overflow_abstains_before_model_call_and_records_context_cost(self):
        trace, lm = self.run_turn(message="new request " * 300, budget=700)
        self.assertEqual(trace.final["kind"], "abstain")
        self.assertEqual(trace.final["reason"], "mandatory_overflow")
        self.assertEqual(lm.generated, [])
        self.assertEqual(trace.totals["generation_calls"]["heavy"], 0)
        self.assertEqual(trace.totals["prompt_budget_blocks"], 1)
        self.assertIn("context_selection_ms", trace.totals)
        self.assertIn("prompt_assembly_ms", trace.totals)
        self.assertEqual(trace.steps[0]["context"]["assembled"]["budget_status"], "mandatory_overflow")

    def test_long_request_does_not_reach_model_with_default_limits(self):
        # Uses the original public loop API too: this fails against the old code
        # because it calls the generator with mandatory content over the budget.
        lm = ToyLM()
        trace = execute_user_turn("new long request " * 1000, host=Host(IncidentWorld()),
                                  decider=ScriptedDecider([Decision("call_model", model_tier="light")]),
                                  context=RuleContextSelector("minimal"), generator=LocalGenerator(lm, lm), turn_id="new")
        self.assertEqual(len(lm.generated), 0)
        self.assertEqual(trace.final["reason"], "mandatory_overflow")

    def test_valid_prompt_reaches_model_with_exact_token_count(self):
        trace, lm = self.run_turn()
        self.assertEqual(trace.final["kind"], "answer")
        self.assertEqual(len(lm.generated), 1)
        assembled = trace.steps[0]["context"]["assembled"]
        self.assertEqual(assembled["measured_tokens"], trace.steps[0]["generation"]["prompt_tokens"])
        self.assertLessEqual(assembled["measured_tokens"], assembled["budget"])

    def test_unknown_tokenizer_abstains_and_never_calls_model(self):
        lm = ToyLM()
        lm.count_tokens = lambda text: None
        trace, lm = self.run_turn(lm)
        self.assertEqual(trace.final["reason"], "unknown_token_count")
        self.assertEqual(lm.generated, [])

    def test_changed_template_abstains_during_last_preflight(self):
        class ChangingLM(ToyLM):
            def __init__(self):
                super().__init__()
                self.templates = 0

            def chat(self, messages):
                self.templates += 1
                return super().chat(messages) + ("changed" if self.templates > 1 else "")

        trace, lm = self.run_turn(ChangingLM())
        self.assertEqual(trace.final["reason"], "prompt_changed")
        self.assertEqual(lm.generated, [])
        self.assertEqual(trace.totals["prompt_budget_blocks"], 1)

    def test_text_counter_alone_cannot_authorize_an_untemplated_backend(self):
        class UncountedGenerator:
            called = False

            def counter(self, tier):
                return len

            def generate(self, *args):
                self.called = True
                raise AssertionError("must not execute")

        gen = UncountedGenerator()
        trace = execute_user_turn("hello", host=Host(IncidentWorld()),
                                  decider=ScriptedDecider([Decision("call_model", model_tier="heavy")]),
                                  context=RuleContextSelector("minimal"), generator=gen, turn_id="new")
        self.assertEqual(trace.final["reason"], "unknown_token_count")
        self.assertFalse(gen.called)

    def test_prompt_budget_invariant_across_sizes_and_limits(self):
        for size in (0, 400, 5000):
            for budget in (0, 500, 700, 1000, 2200):
                with self.subTest(size=size, budget=budget):
                    trace, lm = self.run_turn(message="x" * size, budget=budget)
                    self.assertTrue(all(len(text) <= budget for text, _ in lm.generated))
                    self.assertEqual(trace.final["kind"], "answer" if lm.generated else "abstain")

    def test_local_generator_rechecks_mutated_prompt_before_inference(self):
        lm = ToyLM()
        gen = LocalGenerator(lm, lm)
        p = cx.assemble(TurnState("new", "hello"), "heavy", [], Host(IncidentWorld()).permitted_blocks, "test",
                        count_messages=gen.prompt_counter("heavy"))
        p.messages[-1]["content"] += "unbudgeted text " * 1000
        with self.assertRaises(ValueError):
            gen.generate(p, "heavy", 20)
        self.assertEqual(lm.generated, [])


if __name__ == "__main__":
    unittest.main()
