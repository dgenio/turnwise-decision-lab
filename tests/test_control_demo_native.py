"""Native framework baselines vs Turnwise on the same world, tools and model rules (#49).

Skipped unless the optional framework is installed (``[demo-openai]``,
``[demo-llamaindex]``). Everything runs offline: each framework's own test-double
model applies the shared ``IncidentModel`` rules, and sockets are blocked during runs.
"""
from __future__ import annotations

import os
import socket
import unittest
from unittest import mock

from turnwise_lab.control_demo import native_llamaindex, native_openai
from turnwise_lab.control_demo.__main__ import REQUEST, run_all
from turnwise_lab.control_demo.model import INSTRUCTIONS, IncidentModel
from turnwise_lab.control_demo.trace import NATIVE_MODEL, POLICY
from turnwise_lab.control_demo.turnwise import run_turnwise
from turnwise_lab.control_demo.world import CATALOG


class RequiredFrameworksTests(unittest.TestCase):
    def test_frameworks_present_when_ci_requires_them(self):
        """The optional-framework CI job sets this, so a failed install cannot turn every native test into a skip."""
        if os.environ.get("TURNWISE_REQUIRE_DEMO_FRAMEWORKS"):
            self.assertTrue(native_openai.available(), "openai-agents missing")
            self.assertTrue(native_llamaindex.available(), "llama-index-core missing")


def no_network():
    """Fail loudly if anything opens a connection (e.g. a trace exporter), and offer a fake key to tempt one."""
    def refuse(*args, **kwargs):
        raise AssertionError(f"network access attempted: {args!r}")
    return (mock.patch.object(socket.socket, "connect", refuse),
            mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-not-a-real-key"}))


def essential(schema: dict) -> dict:
    """Properties, enum and required: what a model needs to call the tool."""
    return {"properties": {k: {kk: vv for kk, vv in v.items() if kk in ("type", "enum")}
                           for k, v in schema["properties"].items()}, "required": schema["required"]}


@unittest.skipUnless(native_openai.available(), "openai-agents not installed (pip install '.[demo-openai]')")
class OpenAIAgentsSDKTests(unittest.TestCase):
    def run_native(self, **kw):
        patches = no_network()
        with patches[0], patches[1]:
            return native_openai.run_native_openai(REQUEST, **kw)

    def test_native_agent_gets_the_same_tools_schemas_and_instructions(self):
        run = self.run_native()
        self.assertEqual(run.notes["tools_offered"], [t.name for t in CATALOG])
        self.assertEqual(run.notes["schemas_offered"], {t.name: t.json_schema() for t in CATALOG})
        self.assertEqual(run.notes["instructions_offered"], INSTRUCTIONS)

    def test_the_model_decides_and_the_runner_executes_without_a_policy_step(self):
        run = self.run_native()
        self.assertEqual([s.operation for s in run.steps], ["call_tool", "call_tool", "call_tool", "answer"])
        self.assertTrue(all(s.owner == NATIVE_MODEL for s in run.steps))
        self.assertTrue(all(s.next_controller == NATIVE_MODEL for s in run.steps[:-1]))
        self.assertEqual({r["proposer"] for r in run.host_receipts}, {"native model via Runner"})
        self.assertEqual(run.model_calls, 4)

    def test_same_task_same_answer_different_controller(self):
        native, turnwise = self.run_native(), run_turnwise(REQUEST)
        self.assertEqual(native.final["text"], turnwise.final["text"])
        self.assertEqual([r["tool"] for r in native.host_receipts], [r["tool"] for r in turnwise.host_receipts])
        self.assertEqual({s.owner for s in turnwise.steps}, {POLICY})
        self.assertEqual((native.model_calls, turnwise.model_calls), (4, 2))

    def test_unrequested_rollback_pauses_for_sdk_approval_where_turnwise_declines_it(self):
        native = self.run_native(model=IncidentModel(propose_remediation=True))
        self.assertEqual((native.final["kind"], native.notes["interruptions"]), ("awaiting_approval", ["rollback_deployment"]))
        self.assertNotIn("rollback_deployment", [r["tool"] for r in native.host_receipts])
        turnwise = run_turnwise(REQUEST, model=IncidentModel(propose_remediation=True))
        self.assertIn("decline_model_request", [s.operation for s in turnwise.steps])
        self.assertEqual(turnwise.final["kind"], "answer")

    def test_sdk_tracing_runs_locally_and_processors_are_restored(self):
        from agents.tracing import get_trace_provider
        before = getattr(get_trace_provider()._multi_processor, "_processors", None)
        run = self.run_native()
        self.assertEqual(getattr(get_trace_provider()._multi_processor, "_processors", None), before)
        spans = run.notes["sdk_span_types"]
        self.assertEqual((spans.get("function"), spans.get("generation"), spans.get("agent")), (3, 4, 1))

    def test_deterministic(self):
        self.assertEqual(self.run_native().as_json(), self.run_native().as_json())

    def test_documented_native_trace_is_the_real_output(self):
        from pathlib import Path
        from turnwise_lab.control_demo.trace import render
        doc = (Path(__file__).resolve().parents[1] / "docs" / "same-task-native-vs-turnwise.md").read_text(encoding="utf-8")
        self.assertIn(render(self.run_native()), doc)


@unittest.skipUnless(native_llamaindex.available(), "llama-index-core not installed (pip install '.[demo-llamaindex]')")
class LlamaIndexFunctionAgentTests(unittest.TestCase):
    def run_native(self, **kw):
        patches = no_network()
        with patches[0], patches[1]:
            return native_llamaindex.run_native_llamaindex(REQUEST, **kw)

    def test_native_agent_gets_the_same_tools_schemas_and_instructions(self):
        run = self.run_native()
        self.assertEqual(run.notes["tools_offered"], [t.name for t in CATALOG])
        self.assertEqual({k: essential(v) for k, v in run.notes["schemas_offered"].items()},
                         {t.name: essential(t.json_schema()) for t in CATALOG})
        self.assertEqual(run.notes["instructions_offered"], INSTRUCTIONS)

    def test_the_model_decides_and_the_agent_executes_without_a_policy_step(self):
        run = self.run_native()
        self.assertEqual([s.operation for s in run.steps], ["call_tool", "call_tool", "call_tool", "answer"])
        self.assertTrue(all(s.owner == native_llamaindex.NATIVE_LLAMA for s in run.steps))
        self.assertEqual({r["proposer"] for r in run.host_receipts}, {"native model via FunctionAgent"})
        self.assertEqual(run.notes["workflow_events"].get("ToolCallResult"), 3)

    def test_same_task_same_answer_different_controller(self):
        self.assertEqual(self.run_native().final["text"], run_turnwise(REQUEST).final["text"])

    def test_unrequested_rollback_reaches_the_host_as_an_approval_request(self):
        run = self.run_native(model=IncidentModel(propose_remediation=True))
        rollback = [r for r in run.host_receipts if r["tool"] == "rollback_deployment"]
        self.assertEqual([r["validation"] for r in rollback], ["approval_required"])
        self.assertEqual(run.final["kind"], "answer")  # the model continues after the approval request


@unittest.skipUnless(native_openai.available() and native_llamaindex.available(), "both frameworks needed")
class AllConfigurationsTests(unittest.TestCase):
    def test_three_configurations_one_answer_two_controllers(self):
        patches = no_network()
        with patches[0], patches[1]:
            runs = run_all()
        self.assertEqual(len(runs), 3)
        self.assertEqual(len({r.final["text"] for r in runs}), 1)
        self.assertEqual([{s.owner for s in r.steps} for r in runs],
                         [{NATIVE_MODEL}, {native_llamaindex.NATIVE_LLAMA}, {POLICY}])


if __name__ == "__main__":
    unittest.main()
