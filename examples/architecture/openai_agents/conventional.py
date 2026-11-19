"""A -- Conventional agent on the OpenAI Agents SDK. The model controls every step.

This is a plain SDK agent: one ``Agent`` with a system prompt and function
tools, run by ``Runner.run``. The SDK's loop sends the conversation and the
tool schemas to the model, executes whatever tool calls the model returns,
appends the results to the conversation and asks the model again -- until the
model answers without calling a tool. **The model chooses every operation.**

The tools call the shared host, which validates every request (registration,
arguments, write authority) exactly as it does for the Turnwise variant.
"""
from __future__ import annotations

import json
from typing import Any

from agents import Agent, FunctionTool, RunConfig, RunContextWrapper, Runner

from ..incident_env import AGENT_INSTRUCTIONS, TOOLS, HostSession, IncidentHost, ToolSpec
from ..trace import NativeTurnItem, RunResult, conventional_rows


def build_agent(model: Any) -> Agent[HostSession]:
    """The agent both variants share: same instructions, same tools, same model."""
    return Agent[HostSession](
        name="Incident investigator",
        instructions=AGENT_INSTRUCTIONS,
        tools=[_function_tool(spec) for spec in TOOLS],
        model=model,
    )


def _function_tool(spec: ToolSpec) -> FunctionTool:
    async def invoke(ctx: RunContextWrapper[HostSession], args_json: str) -> str:
        try:
            args = json.loads(args_json or "{}")
        except ValueError:
            args = None  # the host rejects it as malformed
        return ctx.context.host.execute(spec.id, args, proposed_by=ctx.context.actor).for_model()

    return FunctionTool(name=spec.id, description=spec.description,
                        params_json_schema=spec.json_schema(), on_invoke_tool=invoke)


def run_conventional(task: str, model: Any, *, model_label: str, max_turns: int = 10) -> RunResult:
    host = IncidentHost(task)
    agent = build_agent(model)
    result = Runner.run_sync(agent, task, context=HostSession(host, actor="llm"), max_turns=max_turns,
                             run_config=RunConfig(tracing_disabled=True))
    # Each raw response is one model call; whatever it contains is the model's decision.
    turns = [[_turn_item(item) for item in response.output] for response in result.raw_responses]
    rows = conventional_rows(turns, host.receipts, controller="LLM (inside the SDK Runner loop)",
                             loop_name="the SDK Runner")
    return RunResult(
        title="Conventional agent -- OpenAI Agents SDK (Agent + Runner.run_sync + function tools)",
        model_label=model_label, task=task, status="completed (SDK final_output)",
        answer=str(result.final_output), rows=rows,
        notes=["the SDK ends the run when the model answers without a tool call; no host check of the answer"],
        counts={"model_calls": len(result.raw_responses), "host_tool_requests": len(host.receipts)},
        writes_executed=len(host.write_ledger))


def _turn_item(item: Any) -> NativeTurnItem:
    if getattr(item, "type", None) == "function_call":
        return NativeTurnItem("tool_call", tool=item.name, arguments=item.arguments)
    text = "".join(getattr(part, "text", "") for part in getattr(item, "content", []) or [])
    return NativeTurnItem("answer", text=text)
