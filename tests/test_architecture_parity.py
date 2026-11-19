"""Cross-framework parity and offline isolation for the architectural exhibit.

Adapted as a focused independent check after comparing PR #50 with the canonical
OpenAI Agents SDK / LlamaIndex pairs in PR #51. Only the model is simulated;
these tests exercise real framework dispatch and metadata.
"""
from __future__ import annotations

import os
import socket
import unittest
from unittest import mock

try:
    import agents  # noqa: F401
    import llama_index.core  # noqa: F401
    FRAMEWORKS_PRESENT = True
except ImportError:
    if os.environ.get("TURNWISE_REQUIRE_FRAMEWORKS") == "1":
        raise
    FRAMEWORKS_PRESENT = False


@unittest.skipUnless(FRAMEWORKS_PRESENT, "both optional agent SDKs are needed")
class CrossFrameworkParityTests(unittest.TestCase):
    def test_same_task_and_host_results_with_all_four_configurations_without_network(self):
        """Fail loudly on outbound socket use, even with an apparently valid API key."""
        from examples.architecture.incident_env import TASKS
        from examples.architecture.run_demo import run_pair

        def deny(*args, **kwargs):
            raise AssertionError("offline architectural demo attempted a network connection")

        outcomes = []
        with mock.patch.object(socket.socket, "connect", deny), \
             mock.patch.object(socket.socket, "connect_ex", deny), \
             mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-local-fake-key-not-a-provider-credential"}):
            for framework in ("openai-agents", "llamaindex"):
                conventional, turnwise = run_pair(framework, TASKS["investigate"], live=False, handoff=False)
                self.assertEqual(conventional.answer, turnwise.answer, framework)
                self.assertEqual(conventional.counts["host_tool_requests"], 3, framework)
                self.assertEqual(turnwise.counts["host_tool_requests"], 3, framework)
                self.assertEqual((conventional.writes_executed, turnwise.writes_executed), (0, 0))
                self.assertEqual({r.controller for r in turnwise.rows}, {"Turnwise policy"})
                outcomes.append(conventional.answer)
        self.assertEqual(outcomes[0], outcomes[1])

    def test_native_agents_offer_same_effective_tool_arguments(self):
        """LlamaIndex may add titles/descriptions; the required parameters must agree."""
        from examples.architecture.incident_env import TASKS, TOOLS, HostSession, IncidentHost
        from examples.architecture.openai_agents.models import choose_models
        from examples.architecture.openai_agents.conventional import build_agent as openai_agent
        from examples.architecture.llamaindex.models import choose_llms
        from examples.architecture.llamaindex.conventional import build_agent as llama_agent

        native_openai = openai_agent(choose_models().heavy)
        native_llama = llama_agent(
            choose_llms().heavy, HostSession(IncidentHost(TASKS["investigate"]), actor="llm")
        )
        sdk_schemas = {tool.name: tool.params_json_schema for tool in native_openai.tools}
        llama_schemas = {
            tool.metadata.name: tool.metadata.get_parameters_dict() for tool in native_llama.tools
        }
        expected_names = {tool.id for tool in TOOLS}
        self.assertEqual(set(sdk_schemas), expected_names)
        self.assertEqual(set(llama_schemas), expected_names)

        for spec in TOOLS:
            expected = spec.json_schema()
            for name, schema in (("OpenAI SDK", sdk_schemas[spec.id]),
                                 ("LlamaIndex", llama_schemas[spec.id])):
                with self.subTest(framework=name, tool=spec.id):
                    self.assertEqual(set(schema["properties"]), set(expected["properties"]))
                    self.assertEqual(set(schema.get("required", [])), set(expected["required"]))
                    for argument, definition in expected["properties"].items():
                        actual = schema["properties"][argument]
                        self.assertEqual(actual.get("type"), definition.get("type"))
                        if "enum" in definition:
                            self.assertEqual(actual.get("enum"), definition["enum"])


if __name__ == "__main__":
    unittest.main()
