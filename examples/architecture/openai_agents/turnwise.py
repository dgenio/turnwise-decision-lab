"""B -- The same agent with Turnwise Core in control (OpenAI Agents SDK).

Same task, same ``build_agent(...)`` (instructions, tools, model), same host.
What changes is who chooses the next operation:

* the loop is ``TurnwiseRuntime``: ``policy.decide(snapshot)`` chooses every
  operation, and the host validates it;
* the policy's tool and workflow choices are executed by the host;
* the model is invoked as ONE bounded operation: the *same agent*, cloned with
  no tools, handoffs or MCP servers (so the SDK has nothing it could execute)
  and a typed output (``StepOutcome``), run with ``max_turns=1`` (one model
  call). If the model wants a tool, that arrives as
  ``StepOutcome(kind="tool_proposal")`` and goes back to the policy.

``HANDOFF_AGENT`` (contrast only) runs the unmodified agent with ``Runner.run``
for a bounded number of turns: for that segment the model is the controller
again, and the trace says so.

Only public SDK APIs are used: ``Agent.clone``, ``output_type``,
``Runner.run_sync(max_turns=...)``, ``RunConfig``, ``ModelSettings``. The step
clones inherit the agent's ``model_settings`` (provider mode: no retries, an
explicit output-token limit), so A and B send the same model parameters.
"""
from __future__ import annotations

import json
from typing import Any, Mapping

from agents import Agent, ModelSettings, RunConfig, Runner

from ..incident_env import HostSession, IncidentHost
from ..policies import TriagePolicy
from ..provider import ProviderLedger, classify_from_wire
from ..step_schema import StepOutcome
from ..trace import RunResult
from ..turnwise_core import STEP_CONTRACT, Budget, Policy, TurnwiseRuntime
from .conventional import build_agent


class OpenAIAgentsModelPort:
    """How Turnwise invokes the model through the SDK: one call, typed result, no tools."""

    describe = "OpenAI Agents SDK: Runner.run_sync(agent.clone(tools=[], output_type=StepOutcome), max_turns=1)"

    def __init__(self, agent: Agent[HostSession], host: IncidentHost, *, light_model: Any, label: str,
                 ledger: ProviderLedger | None = None):
        self.agent, self.host, self.label, self.ledger = agent, host, label, ledger
        # Nothing executable is left on the clone: no tools, handoffs or MCP servers. max_turns=1 below bounds
        # it to one model call; it is the empty capability lists, not max_turns, that stop any execution.
        step = dict(tools=[], handoffs=[], mcp_servers=[], output_type=StepOutcome,
                    instructions=f"{agent.instructions}\n\n{STEP_CONTRACT}")
        self.step_agents = {
            "heavy": agent.clone(name=f"{agent.name} (one Turnwise step)", **step),
            "light": agent.clone(name=f"{agent.name} (one Turnwise step, light)", model=light_model, **step),
        }
        self._config = RunConfig(tracing_disabled=True)

    def call(self, tier: str, packet: Mapping[str, Any]) -> Mapping[str, Any]:
        sent_before = len(self.ledger.exchanges) if self.ledger else 0
        try:
            result = Runner.run_sync(self.step_agents[tier], json.dumps(packet, sort_keys=True), max_turns=1,
                                     run_config=self._config)
        except Exception as exc:  # the SDK already names refusals and timeouts; the wire record adds the rest
            wire = classify_from_wire(self.ledger, sent_before)
            if wire is not None:
                raise wire from exc
            raise
        return result.final_output.model_dump()

    def handoff(self, task_text: str, max_turns: int) -> str:
        # The unmodified agent, with its tools: the model controls this segment.
        result = Runner.run_sync(self.agent, task_text, context=HostSession(self.host, actor="native_agent"),
                                 max_turns=max_turns, run_config=self._config)
        return str(result.final_output)


def run_turnwise(task: str, heavy_model: Any, light_model: Any, *, model_label: str,
                 policy: Policy | None = None, budget: Budget = Budget(), model_settings: ModelSettings | None = None,
                 host: IncidentHost | None = None, ledger: ProviderLedger | None = None,
                 ) -> tuple[RunResult, TurnwiseRuntime]:
    host = host or IncidentHost(task)
    agent = build_agent(heavy_model, model_settings)  # the very same agent definition as the conventional example
    port = OpenAIAgentsModelPort(agent, host, light_model=light_model, label=model_label, ledger=ledger)
    policy = policy or TriagePolicy()
    runtime = TurnwiseRuntime(host, policy, port, budget=budget, framework="OpenAI Agents SDK")
    return runtime.run(), runtime
