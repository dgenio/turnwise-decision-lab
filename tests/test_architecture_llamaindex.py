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

    from examples.architecture.checklist_null import native_instructions
    from examples.architecture.incident_env import TASKS, HostSession, IncidentHost
    from examples.architecture.llamaindex.conventional import build_agent, run_conventional
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

    def test_checklist_null_changes_only_the_native_prompt(self):
        m = choose_llms()
        host = IncidentHost(TASKS["investigate"])
        session = HostSession(host, actor="llm")
        baseline = build_agent(m.heavy, session)
        prompted = build_agent(m.heavy, session, checklist=True)
        self.assertEqual(baseline.system_prompt, native_instructions())
        self.assertEqual(prompted.system_prompt, native_instructions(checklist=True))
        self.assertEqual([t.metadata.name for t in baseline.tools],
                         [t.metadata.name for t in prompted.tools])
        self.assertIs(baseline.llm, prompted.llm)
        result = run_conventional(TASKS["investigate"], m.heavy, model_label=m.label, checklist=True)
        self.assertTrue(result.title.startswith("A+P"))
        self.assertEqual(result.writes_executed, 0)

    def test_turnwise_calls_the_agents_llm_once_per_step_with_structured_output(self):
        # With the offline mock (a function-calling LLM), structured_predict uses LlamaIndex's function-calling
        # program, hence the single StepOutcome tool. The provider LLM (OpenAIResponses) uses the Responses API's
        # JSON-schema decoding instead; tests/test_architecture_provider_readiness.py covers that path.
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

    def test_parallel_tool_calls_are_paired_with_receipts_by_call_id(self):
        # The workflow may run one response's tool calls concurrently and in any order.
        from llama_index.core.base.llms.types import TextBlock, ToolCallBlock
        from llama_index.core.llms import ChatMessage, MessageRole
        from llama_index.core.llms.mock import MockFunctionCallingLLM

        tools = ["validate_config", "error_trend", "recent_deploys"]

        def generate(messages, **kwargs):
            if not any(m.role == MessageRole.TOOL for m in messages):
                return ChatMessage(role=MessageRole.ASSISTANT, blocks=[TextBlock(text="Checking three things.")] + [
                    ToolCallBlock(tool_call_id=f"c{i}", tool_name=t, tool_kwargs={"service": "checkout"})
                    for i, t in enumerate(tools)])
            return ChatMessage(role=MessageRole.ASSISTANT, content="Done.")

        expected = {"validate_config": "drift:", "error_trend": "error rate", "recent_deploys": "d-142"}
        for _ in range(25):
            llm = MockFunctionCallingLLM(response_generator=generate, is_chat_model=True)
            result = run_conventional(TASKS["investigate"], llm, model_label="SIMULATED (test script)")
            rows = [r for r in result.rows if r.decision.startswith("tool call")]
            self.assertEqual(result.rows[0].decision, "text alongside the tool call(s) (not a decision)")
            self.assertEqual(len(rows), 3)
            for row in rows:
                self.assertNotIn("no host receipt", row.host)
                self.assertIn(expected[row.decision.split(" ")[2].split("(")[0]], row.observation)

    def test_run_demo_never_calls_a_provider_even_with_a_key(self):
        # Real-provider runs go only through the bounded live_smoke harness; run_demo --live refuses up front.
        from examples.architecture import run_demo
        saved = os.environ.get("OPENAI_API_KEY")
        os.environ["OPENAI_API_KEY"] = "dummy-key-never-used"
        try:
            with self.assertRaises(SystemExit) as ctx:
                run_demo.main(["--live", "--framework", "all"])
        finally:
            if saved is None:
                os.environ.pop("OPENAI_API_KEY", None)
            else:
                os.environ["OPENAI_API_KEY"] = saved
        self.assertIn("live_smoke", str(ctx.exception))

    def test_handoff_contrast(self):
        m = choose_llms()
        result, rt = run_turnwise(TASKS["investigate"], m.heavy, m.light, model_label=m.label, policy=HandoffPolicy())
        self.assertIn("native agent (handoff)", [r.controller for r in result.rows])
        self.assertEqual(rt.host.receipts[-1].proposed_by, "native_agent")
        self.assertEqual(result.status, "finished")


if __name__ == "__main__":
    unittest.main()
