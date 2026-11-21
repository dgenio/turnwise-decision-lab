"""B' -- The same agent under the Turnwise Core loop, asked through native tool calls (OpenAI Agents SDK).

An ABLATION of the model interface (#87), opt-in, not the canonical arm B. Same task, same
``build_agent(...)``, same host, same policy and loop as arm B. What changes is how the model is asked:

* the step agent keeps a real ``tools`` field (the policy's ``may_propose``) and a typed final reply
  (``StepAnswer``), and its conversation is appended to instead of rebuilt;
* every tool is **inert** and marked ``needs_approval=True``. The SDK therefore pauses the run before any tool
  runs and returns the model's tool calls as ``interruptions``. Each becomes a proposal for the policy;
* when the policy next calls the model, each earlier call is answered: an adopted call is approved and its
  inert tool returns the receipt the host already produced; a declined call is rejected with the reason. The
  SDK then makes exactly one more model call and pauses again, or returns the typed final reply.

The inert tool cannot execute anything: it only hands back a result the host recorded for that call id. If it
is ever invoked with no such result, it says so, changes nothing and records the event in
``unexpected_invocations`` (a tripwire the tests assert stays empty).

Only public SDK APIs are used: ``Agent.clone``, ``FunctionTool(needs_approval=True)``, ``RunResult.interruptions``,
``RunResult.to_state``, ``RunState.approve`` / ``reject`` / ``add_input``, ``Runner.run_sync``.
"""
from __future__ import annotations

from typing import Any, Mapping

from agents import Agent, FunctionTool, ModelSettings, RunConfig, Runner
from agents.tool_context import ToolContext

from ..incident_env import HostSession, IncidentHost, ToolSpec
from ..native_intercept import (HOST_RESULTS, INTERCEPT_CONTRACT, NOT_CONSIDERED, CallAnswer, NativeCall,
                                NativeInterceptRuntime, NativeTurn)
from ..policies import TriagePolicy
from ..provider import ProviderLedger, classify_from_wire
from ..step_schema import StepAnswer
from ..trace import RunResult
from ..turnwise_core import Budget, Policy
from .conventional import build_agent

NO_HOST_RESULT = "No host result is recorded for this call. Nothing was executed."
NOTHING_NEW = "HOST: no new host results since your last reply."


class OpenAIAgentsInterceptPort:
    """One model call with a real tools field; the SDK pauses before any tool, so nothing is executed."""

    describe = ("OpenAI Agents SDK: Runner.run_sync(agent.clone(tools=<inert, needs_approval=True>, "
                "output_type=StepAnswer)); the run pauses before any tool runs")

    def __init__(self, agent: Agent[HostSession], host: IncidentHost, *, light_model: Any, label: str,
                 ledger: ProviderLedger | None = None, max_turns: int = 64):
        self.agent, self.host, self.label, self.ledger = agent, host, label, ledger
        self._models = {"heavy": agent.model, "light": light_model}
        self._max_turns = max_turns  # the SDK counts turns across resumes; the policy's model budget is the real bound
        self._config = RunConfig(tracing_disabled=True)
        self._agents: dict[str, Agent[Any]] = {}  # tier -> its step agent; the tools field never changes afterwards
        self._last: dict[str, Any] = {}  # tier -> the RunResult of its latest call (paused, or finished)
        self._mailbox: dict[str, str] = {}  # call id -> the host receipt text of an adopted call
        self.unexpected_invocations: list[str] = []  # tripwire: an inert tool ran with no host result waiting

    def native_step(self, tier: str, *, first_message: str, offered: tuple[ToolSpec, ...],
                    answers: Mapping[str, CallAnswer], host_results: tuple[str, ...]) -> NativeTurn:
        if tier not in self._agents:
            self._agents[tier] = self.agent.clone(
                name=f"{self.agent.name} (one Turnwise step, native-intercept, {tier})", model=self._models[tier],
                tools=[self._inert_tool(spec) for spec in offered], handoffs=[], mcp_servers=[],
                output_type=StepAnswer, instructions=f"{self.agent.instructions}\n\n{INTERCEPT_CONTRACT}")
        last = self._last.get(tier)
        note = {"role": "user", "content": "\n".join([HOST_RESULTS, *host_results])} if host_results else None
        if last is None:
            run_input: Any = first_message
        elif last.interruptions:  # answer every call of the previous response, then one more model call
            run_input = last.to_state()
            for item in last.interruptions:
                answer = answers.get(_call_id(item)) or CallAnswer(False, NOT_CONSIDERED)
                if answer.adopted:
                    self._mailbox[_call_id(item)] = answer.text
                    run_input.approve(item)
                else:
                    run_input.reject(item, rejection_message=answer.text)
            if note:
                run_input.add_input([note])
        else:  # the previous reply was a final one: the conversation continues with whatever the host has
            run_input = last.to_input_list() + [note or {"role": "user", "content": NOTHING_NEW}]
        sent_before = len(self.ledger.exchanges) if self.ledger else 0
        try:
            result = Runner.run_sync(self._agents[tier], run_input, max_turns=self._max_turns, run_config=self._config)
        except Exception as exc:  # the SDK already names refusals and timeouts; the wire record adds the rest
            wire = classify_from_wire(self.ledger, sent_before)
            if wire is not None:
                raise wire from exc
            raise
        self._last[tier] = result
        if result.interruptions:
            return NativeTurn(calls=tuple(NativeCall(_call_id(i), str(i.name or ""), str(i.arguments or ""))
                                          for i in result.interruptions))
        return NativeTurn(final=result.final_output.model_dump())

    def handoff(self, task_text: str, max_turns: int) -> str:
        # The unmodified agent, with its tools: the model controls this segment (contrast only, as in arm B).
        result = Runner.run_sync(self.agent, task_text, context=HostSession(self.host, actor="native_agent"),
                                 max_turns=max_turns, run_config=self._config)
        return str(result.final_output)

    def _inert_tool(self, spec: ToolSpec) -> FunctionTool:
        async def deliver(ctx: ToolContext[Any], args_json: str) -> str:
            text = self._mailbox.get(ctx.tool_call_id)
            if text is None:
                self.unexpected_invocations.append(f"{spec.id}:{ctx.tool_call_id}")
                return NO_HOST_RESULT
            return text

        return FunctionTool(name=spec.id, description=spec.description, params_json_schema=spec.json_schema(),
                            on_invoke_tool=deliver, needs_approval=True)


def _call_id(item: Any) -> str:
    raw = item.raw_item
    return str(raw.get("call_id") if isinstance(raw, dict) else getattr(raw, "call_id", ""))


def run_native_intercept(task: str, heavy_model: Any, light_model: Any, *, model_label: str,
                         policy: Policy | None = None, budget: Budget = Budget(),
                         model_settings: ModelSettings | None = None, host: IncidentHost | None = None,
                         ledger: ProviderLedger | None = None, max_proposals: int = 8,
                         ) -> tuple[RunResult, NativeInterceptRuntime]:
    host = host or IncidentHost(task)
    agent = build_agent(heavy_model, model_settings)  # the very same agent definition as arms A and B
    port = OpenAIAgentsInterceptPort(agent, host, light_model=light_model, label=model_label, ledger=ledger)
    runtime = NativeInterceptRuntime(host, policy or TriagePolicy(), port, budget=budget,
                                     framework="OpenAI Agents SDK", max_proposals=max_proposals)
    return runtime.run(), runtime
