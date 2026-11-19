"""B -- The same agent with Turnwise Core in control (LlamaIndex).

Same task, same ``build_agent(...)`` (system prompt, tools, LLM), same host.
What changes is who chooses the next operation: ``TurnwiseRuntime`` asks the
policy after every observation. The model is invoked as ONE bounded operation
through LlamaIndex structured prediction -- ``llm.structured_predict(StepOutcome,
...)`` on the agent's own LLM (``CALL_HEAVY``) or a separate light LLM
(``CALL_LIGHT``) -- so a tool request comes back as a typed
``StepOutcome(kind="tool_proposal")`` for the policy. No agent workflow runs
in that call, and no tool is executed on the model's say-so.

``HANDOFF_AGENT`` (contrast only) runs the agent workflow itself for a bounded
number of iterations; for that segment the LLM controls the operations.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Mapping

from llama_index.core.agent.workflow import FunctionAgent
from llama_index.core.prompts import ChatPromptTemplate

from ..incident_env import HostSession, IncidentHost
from ..policies import TriagePolicy
from ..step_schema import StepOutcome
from ..trace import RunResult
from ..turnwise_core import STEP_CONTRACT, Budget, Policy, TurnwiseRuntime
from .conventional import build_agent, run_agent
from .models import PACKET_MARKER


class LlamaIndexModelPort:
    """How Turnwise invokes the model through LlamaIndex: one structured call, no tools, no agent loop."""

    describe = ("LlamaIndex: llm.structured_predict(StepOutcome, ...) -- the agent's own LLM for heavy, "
                "a separate light LLM for light")

    def __init__(self, agent: FunctionAgent, host: IncidentHost, *, light_llm: Any, label: str):
        self.agent, self.host, self.label = agent, host, label
        self.llms = {"heavy": agent.llm, "light": light_llm}
        # System prompt + user packet, like the agent's own messages. Each message is one template variable,
        # so the JSON braces inside them need no escaping.
        self.template = ChatPromptTemplate.from_messages([("system", "{system}"), ("user", "{packet}")])

    def call(self, tier: str, packet: Mapping[str, Any]) -> Mapping[str, Any]:
        outcome = self.llms[tier].structured_predict(
            StepOutcome, self.template, system=f"{self.agent.system_prompt}\n\n{STEP_CONTRACT}",
            packet=f"{PACKET_MARKER}{json.dumps(packet, sort_keys=True)}")
        return outcome.model_dump()

    def handoff(self, task_text: str, max_turns: int) -> str:
        # The same agent definition, with its tools: the LLM controls this segment.
        native = build_agent(self.agent.llm, HostSession(self.host, actor="native_agent"))
        final, _, _ = asyncio.run(run_agent(native, task_text, max_turns))
        return final.response.content or ""


def run_turnwise(task: str, heavy_llm: Any, light_llm: Any, *, model_label: str,
                 policy: Policy | None = None, budget: Budget = Budget()) -> tuple[RunResult, TurnwiseRuntime]:
    host = IncidentHost(task)
    agent = build_agent(heavy_llm, HostSession(host, actor="llm"))  # the very same agent definition
    port = LlamaIndexModelPort(agent, host, light_llm=light_llm, label=model_label)
    policy = policy or TriagePolicy()
    runtime = TurnwiseRuntime(host, policy, port, budget=budget, framework="LlamaIndex")
    return runtime.run(), runtime
