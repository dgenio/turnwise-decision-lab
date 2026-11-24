"""A ``HANDOFF_AGENT`` segment's own model calls are counted, or marked unknown -- never omitted or 0.

``HANDOFF_AGENT`` (a contrast, not Turnwise Core) gives a native agent its own loop, so the agent makes
model calls the policy never chose. The run's counts used to show only the number of handoffs, labelled
"agent's own model calls not counted here", next to ``model_calls_chosen_by_policy=0``. A port now reports
how many model calls the agent made (from the framework's own record); a port that cannot, or a handoff
that fails, reports ``unknown``. Mechanism tests, not a cost measurement: offline replies are simulated.
"""
from __future__ import annotations

import os
import unittest

from examples.architecture.incident_env import TASKS, IncidentHost
from examples.architecture.policies import HandoffPolicy
from examples.architecture.simulated_model import SimulatedInvestigator
from examples.architecture.turnwise_core import Budget, Decision, HandoffReport, Op, TurnwiseRuntime

try:
    import agents  # noqa: F401
    HAVE_SDK = True
except ImportError:
    if os.environ.get("TURNWISE_REQUIRE_FRAMEWORKS") == "1":
        raise
    HAVE_SDK = False
try:
    import llama_index.core  # noqa: F401
    HAVE_LLAMA = True
except ImportError:
    if os.environ.get("TURNWISE_REQUIRE_FRAMEWORKS") == "1":
        raise
    HAVE_LLAMA = False


class Port:
    label, describe = "SIMULATED (test port)", "test port"

    def __init__(self, *handoffs):
        self.handoffs, self.brain = list(handoffs), SimulatedInvestigator()

    def call(self, tier, packet):
        return self.brain.typed_step(packet)

    def handoff(self, task_text, max_turns):
        item = self.handoffs.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def run(*handoffs, handoff_count=1):
    """A policy that hands off ``handoff_count`` times, then stops visibly."""
    def decide(s):
        done = sum(1 for o in s.outcomes if o.source == "native_agent")
        if done < handoff_count:
            return Decision(Op.HANDOFF_AGENT, "contrast: give the native agent the turn")
        return Decision(Op.HOLD, "stop", message="Stopping after the handoff.")
    policy = type("P", (), {"name": "handoff script (test)", "decide": staticmethod(decide)})()
    host = IncidentHost(TASKS["investigate"])
    return TurnwiseRuntime(host, policy, Port(*handoffs), budget=Budget(max_model_calls=4)).run()


class HandoffCounts(unittest.TestCase):
    def test_reported_model_calls_are_counted(self):
        counts = run(HandoffReport("answer", model_calls=3)).counts
        self.assertEqual((counts["handoffs"], counts["model_calls_inside_handoffs"]), (1, 3))
        self.assertEqual(counts["model_calls_chosen_by_policy"], 0)
        self.assertFalse(any("not counted" in key for key in counts))

    def test_a_port_that_returns_plain_text_reports_unknown_not_zero(self):
        counts = run("answer").counts
        self.assertEqual((counts["handoffs"], counts["model_calls_inside_handoffs"]), (1, "unknown"))

    def test_a_failed_handoff_reports_unknown(self):
        counts = run(RuntimeError("agent hit its turn limit")).counts
        self.assertEqual(counts["model_calls_inside_handoffs"], "unknown")

    def test_invalid_reports_are_unknown(self):
        for bad in (-1, True, "3", 2.5):
            with self.subTest(model_calls=bad):
                counts = run(HandoffReport("answer", model_calls=bad)).counts
                self.assertEqual(counts["model_calls_inside_handoffs"], "unknown")

    def test_one_unknown_handoff_makes_the_total_unknown(self):
        counts = run(HandoffReport("a", model_calls=2), "b", handoff_count=2).counts
        self.assertEqual((counts["handoffs"], counts["model_calls_inside_handoffs"]), (2, "unknown"))
        counts = run(HandoffReport("a", model_calls=2), HandoffReport("b", model_calls=5), handoff_count=2).counts
        self.assertEqual(counts["model_calls_inside_handoffs"], 7)

    def test_turnwise_core_runs_carry_no_handoff_counts(self):
        from examples.architecture.policies import TriagePolicy
        host = IncidentHost(TASKS["investigate"])
        counts = TurnwiseRuntime(host, TriagePolicy(), Port()).run().counts
        self.assertNotIn("handoffs", counts)
        self.assertNotIn("model_calls_inside_handoffs", counts)


@unittest.skipUnless(HAVE_SDK, "openai-agents not installed")
class OpenAIAgentsHandoffCount(unittest.TestCase):
    def test_count_matches_the_calls_the_sdk_made(self):
        from examples.architecture.openai_agents.models import choose_models
        from examples.architecture.openai_agents.turnwise import run_turnwise
        m = choose_models()
        result, _ = run_turnwise(TASKS["investigate"], m.heavy, m.light, model_label=m.label, policy=HandoffPolicy())
        self.assertEqual(result.counts["model_calls_chosen_by_policy"], 0)
        # agents.testing.ScriptedModel records every call the SDK made; with HandoffPolicy all are the agent's.
        self.assertEqual(result.counts["model_calls_inside_handoffs"], len(m.heavy.calls))
        self.assertGreater(len(m.heavy.calls), 1)


@unittest.skipUnless(HAVE_LLAMA, "llama-index-core not installed")
class LlamaIndexHandoffCount(unittest.TestCase):
    def test_count_matches_the_calls_the_llm_received(self):
        from examples.architecture.llamaindex.models import choose_llms
        from examples.architecture.llamaindex.turnwise import run_turnwise
        m = choose_llms()
        received = []
        inner = m.heavy.response_generator

        def counting(messages, **kwargs):  # an independent counter around the simulated LLM
            received.append(1)
            return inner(messages, **kwargs)
        m.heavy.response_generator = counting
        result, _ = run_turnwise(TASKS["investigate"], m.heavy, m.light, model_label=m.label, policy=HandoffPolicy())
        self.assertEqual(result.counts["model_calls_chosen_by_policy"], 0)
        self.assertEqual(result.counts["model_calls_inside_handoffs"], len(received))
        self.assertGreater(len(received), 1)


if __name__ == "__main__":
    unittest.main()
