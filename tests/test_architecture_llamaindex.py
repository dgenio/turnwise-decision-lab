"""LlamaIndex integration of the architecture example. Offline: the framework runs for real, the LLM is simulated.

Skipped when ``llama-index-core`` is not installed, unless TURNWISE_REQUIRE_FRAMEWORKS=1.
"""
from __future__ import annotations

import os
import unittest

try:
    import llama_index.core  # noqa: F401
    HAVE_LLAMAINDEX = True
except ImportError:
    if os.environ.get("TURNWISE_REQUIRE_FRAMEWORKS") == "1":
        raise
    HAVE_LLAMAINDEX = False

if HAVE_LLAMAINDEX:
    from llama_index.core.agent.workflow import FunctionAgent

    from examples.architecture.incident_env import TASKS
    from examples.architecture.llamaindex.conventional import run_conventional
    from examples.architecture.llamaindex.models import choose_llms
    from examples.architecture.llamaindex.turnwise import run_turnwise
    from examples.architecture.policies import HandoffPolicy
    from examples.architecture.simulated_model import SimulatedInvestigator
    from examples.architecture.turnwise_core import ModelOutcome


class Recorder:
    """Wraps the simulated generator to record what LlamaIndex sends the LLM."""

    def __init__(self, llm):
        self.calls = []
        inner = llm.response_generator

        def generate(messages, **kwargs):
            self.calls.append({"roles": [m.role.value for m in messages],
                               "tools": [t.metadata.name for t in kwargs.get("tools") or []]})
            return inner(messages, **kwargs)

        llm.response_generator = generate


@unittest.skipUnless(HAVE_LLAMAINDEX, "llama-index-core not installed")
class LlamaIndexPairTests(unittest.TestCase):
    def test_conventional_function_agent_lets_the_llm_choose_every_tool(self):
        m = choose_llms()
        rec = Recorder(m.heavy)
        result = run_conventional(TASKS["investigate"], m.heavy, model_label=m.label)
        self.assertEqual(len(rec.calls), 4)
        self.assertTrue(all(len(c["tools"]) == 6 for c in rec.calls))
        self.assertEqual(rec.calls[1]["roles"][-1], "tool")  # the workflow fed the tool result back
        self.assertEqual([r.decision.split("(")[0] for r in result.rows],
                         ["tool call error_trend", "tool call recent_deploys", "tool call validate_config",
                          "final answer "])
        self.assertTrue(result.answer.startswith("Plausibly yes."))

    def test_turnwise_calls_the_agents_llm_once_per_step_with_structured_output(self):
        m = choose_llms()
        rec = Recorder(m.heavy)
        result, rt = run_turnwise(TASKS["investigate"], m.heavy, m.light, model_label=m.label)
        self.assertIsInstance(rt.model.agent, FunctionAgent)
        self.assertIs(rt.model.llms["heavy"], rt.model.agent.llm)
        self.assertEqual([c["tools"] for c in rec.calls], [["StepOutcome"], ["StepOutcome"]])
        self.assertEqual({tuple(c["roles"]) for c in rec.calls}, {("system", "user")})  # like the agent's own messages
        latest = rt.snapshots[3].latest
        self.assertIsInstance(latest, ModelOutcome)
        self.assertEqual((latest.kind, latest.proposal.tool), ("tool_proposal", "validate_config"))
        self.assertEqual({r.controller for r in result.rows}, {"Turnwise policy"})
        self.assertEqual(result.status, "finished")

    def test_every_scenario_and_host_authority(self):
        expected = {"investigate": "finished", "status": "finished", "severity": "answered_directly", "rollback": "held"}
        for name, status in expected.items():
            with self.subTest(name):
                m = choose_llms()
                result, _ = run_turnwise(TASKS[name], m.heavy, m.light, model_label=m.label)
                self.assertEqual((result.status, result.writes_executed), (status, 0))
        m = choose_llms(brain=SimulatedInvestigator(rogue_write=True))
        conventional = run_conventional(TASKS["investigate"], m.heavy, model_label=m.label)
        self.assertIn("REJECTED", next(r.host for r in conventional.rows if "rollback_deploy" in r.decision))
        self.assertEqual(conventional.writes_executed, 0)

    def test_handoff_contrast(self):
        m = choose_llms()
        result, rt = run_turnwise(TASKS["investigate"], m.heavy, m.light, model_label=m.label, policy=HandoffPolicy())
        self.assertIn("native agent (handoff)", [r.controller for r in result.rows])
        self.assertEqual(rt.host.receipts[-1].proposed_by, "native_agent")
        self.assertEqual(result.status, "finished")


if __name__ == "__main__":
    unittest.main()
