"""OpenAI Agents SDK integration of the architecture example. Offline: the SDK runs for real, the model is simulated.

Skipped when ``openai-agents`` is not installed, unless TURNWISE_REQUIRE_FRAMEWORKS=1
(set in the CI job that installs examples/architecture/requirements.txt), in
which case a missing package is a failure, not a silent skip.
"""
from __future__ import annotations

import json
import os
import unittest

try:
    import agents  # noqa: F401
    HAVE_SDK = True
except ImportError:
    if os.environ.get("TURNWISE_REQUIRE_FRAMEWORKS") == "1":
        raise
    HAVE_SDK = False

if HAVE_SDK:
    from agents import Agent

    from examples.architecture.incident_env import AGENT_INSTRUCTIONS, TASKS, TOOLS
    from examples.architecture.openai_agents.conventional import build_agent, run_conventional
    from examples.architecture.openai_agents.models import choose_models
    from examples.architecture.openai_agents.turnwise import run_turnwise
    from examples.architecture.policies import HandoffPolicy
    from examples.architecture.simulated_model import SimulatedInvestigator
    from examples.architecture.turnwise_core import ModelOutcome


def _run_conventional(task=None, brain=None):
    m = choose_models(brain=brain)
    return run_conventional(task or TASKS["investigate"], m.heavy, model_label=m.label), m


def _run_turnwise(task=None, policy=None, brain=None):
    m = choose_models(brain=brain)
    result, rt = run_turnwise(task or TASKS["investigate"], m.heavy, m.light, model_label=m.label, policy=policy)
    return result, rt, m


@unittest.skipUnless(HAVE_SDK, "openai-agents not installed")
class ConventionalAgentIsANativeSDKAgentTests(unittest.TestCase):
    def test_the_sdk_runner_loop_lets_the_model_choose_every_tool(self):
        result, m = _run_conventional()
        calls = m.heavy.calls  # agents.testing.ScriptedModel records every call the SDK made
        self.assertEqual(len(calls), 4)
        for call in calls:
            self.assertEqual(sorted(t.name for t in call.tools), sorted(t.id for t in TOOLS))
            self.assertIsNone(call.output_schema)
            self.assertEqual(call.system_instructions, AGENT_INSTRUCTIONS)
        # The SDK appended each tool result to the conversation before asking the model again.
        outputs = [i for i in calls[1].input if isinstance(i, dict) and i.get("type") == "function_call_output"]
        self.assertEqual(json.loads(outputs[0]["output"])["receipt"], "r1")
        self.assertEqual([r.decision for r in result.rows], [
            "tool call error_trend(service=checkout)", "tool call recent_deploys(service=checkout)",
            "tool call validate_config(service=checkout)", "final answer (no tool call) -> the SDK Runner ends the run"])
        self.assertEqual({r.controller for r in result.rows}, {"LLM (inside the SDK Runner loop)"})
        self.assertTrue(result.answer.startswith("Plausibly yes."))
        self.assertEqual(result.writes_executed, 0)

    def test_trace_treats_text_beside_a_tool_call_as_part_of_that_tool_decision(self):
        from agents.testing import assistant_message, function_call

        from examples.architecture.openai_agents.conventional import _decision
        items = _decision([assistant_message("Let me check."), function_call("error_trend", {"service": "checkout"},
                                                                              call_id="c1")])
        self.assertEqual([(i.kind, i.tool) for i in items], [("tool_call", "error_trend")])
        self.assertEqual(_decision([assistant_message("Done.")])[0].kind, "answer")

    def test_the_shared_host_still_rejects_an_unrequested_write_from_the_model(self):
        result, _ = _run_conventional(brain=SimulatedInvestigator(rogue_write=True))
        rollback = [r for r in result.rows if "rollback_deploy" in r.decision]
        self.assertEqual(len(rollback), 1)
        self.assertIn("REJECTED", rollback[0].host)
        self.assertEqual(result.writes_executed, 0)


@unittest.skipUnless(HAVE_SDK, "openai-agents not installed")
class TurnwiseOnTheSDKTests(unittest.TestCase):
    def test_same_agent_definition_is_reused_for_bounded_typed_steps(self):
        result, rt, m = _run_turnwise()
        agent = rt.model.agent
        self.assertIsInstance(agent, Agent)
        self.assertEqual([t.name for t in agent.tools], [t.name for t in build_agent(m.heavy).tools])
        step = rt.model.step_agents["heavy"]
        self.assertIs(step.model, agent.model)  # the same capable model
        self.assertEqual(step.tools, [])  # nothing the model could execute
        self.assertTrue(step.instructions.startswith(AGENT_INSTRUCTIONS))

    def test_every_model_call_is_one_typed_step_and_its_proposal_returns_to_the_policy(self):
        result, rt, m = _run_turnwise()
        calls = m.heavy.calls
        self.assertEqual(len(calls), 2)  # exactly one SDK model call per CALL_HEAVY decision
        for call in calls:
            self.assertEqual((call.tools, call.handoffs), ([], []))  # nothing the SDK could execute
            self.assertEqual(call.output_schema.name(), "StepOutcome")
            self.assertEqual(len(call.input), 1)  # just the context packet the host assembled
        first_packet = json.loads(calls[0].input[0]["content"])
        self.assertEqual([e["receipt"] for e in first_packet["evidence"]], ["r1", "r2"])
        latest = rt.snapshots[3].latest
        self.assertIsInstance(latest, ModelOutcome)
        self.assertEqual((latest.kind, latest.proposal.tool), ("tool_proposal", "validate_config"))
        self.assertEqual({r.controller for r in result.rows}, {"Turnwise policy"})
        self.assertEqual(result.status, "finished")
        self.assertEqual([r.proposed_by for r in rt.host.receipts], ["turnwise_policy"] * 3)

    def test_turnwise_core_never_silently_becomes_a_native_agent_handoff(self):
        # After every heavy output, control is with the policy: no native-loop model call, no native-agent step.
        for brain in (SimulatedInvestigator(), SimulatedInvestigator(rogue_write=True)):
            result, rt, m = _run_turnwise(brain=brain)
            self.assertTrue(result.title.startswith("Turnwise Core"))
            self.assertEqual({r.controller for r in result.rows}, {"Turnwise policy"})
            self.assertTrue(all(c.output_schema is not None and c.tools == [] for c in m.heavy.calls))
            self.assertEqual(len(rt.snapshots), len(result.rows))
            self.assertNotIn("native_agent", [r.proposed_by for r in rt.host.receipts])
            self.assertEqual(result.writes_executed, 0)

    def test_every_scenario_runs_through_the_sdk(self):
        expected = {"investigate": "finished", "status": "finished", "severity": "answered_directly", "rollback": "held"}
        for name, status in expected.items():
            with self.subTest(name):
                result, rt, m = _run_turnwise(TASKS[name])
                self.assertEqual(result.status, status)
                self.assertEqual(result.writes_executed, 0)
        self.assertEqual(len(_run_turnwise(TASKS["status"])[2].light.calls), 1)  # CALL_LIGHT used the light model

    def test_handoff_contrast_gives_the_native_agent_control_for_a_segment(self):
        result, rt, m = _run_turnwise(policy=HandoffPolicy())
        self.assertTrue(result.title.startswith("Agent handoff (contrast; NOT Turnwise Core)"))
        native = [r for r in result.rows if r.controller == "native agent (handoff)"]
        self.assertEqual(native[0].decision, "tool call validate_config(service=checkout)")
        self.assertEqual([r.proposed_by for r in rt.host.receipts], ["turnwise_policy", "turnwise_policy", "native_agent"])
        self.assertIsNone(m.heavy.calls[-1].output_schema)  # the handoff ran the native tool-calling agent
        self.assertEqual(result.rows[-1].controller, "Turnwise policy")
        self.assertEqual(result.status, "finished")

    def test_live_mode_is_explicit_and_refuses_without_a_key(self):
        saved = os.environ.pop("OPENAI_API_KEY", None)
        try:
            with self.assertRaises(SystemExit):
                choose_models(live=True)
        finally:
            if saved is not None:
                os.environ["OPENAI_API_KEY"] = saved


if __name__ == "__main__":
    unittest.main()
