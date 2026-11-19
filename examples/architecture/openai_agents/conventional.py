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

from agents import Agent, FunctionTool, RunConfig, RunContextWrapper, Runner, ToolCallOutputItem

from ..incident_env import AGENT_INSTRUCTIONS, TOOLS, HostSession, IncidentHost, ToolSpec
from ..trace import NativeTurnItem, RunResult, conventional_rows, receipt_id_from_output


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
    # Each raw response is one model call, i.e. one model decision.
    turns = [_decision(response.output) for response in result.raw_responses]
    receipt_for_call = {}
    for item in result.new_items:  # the SDK's record of each tool output, keyed by the model's call id
        if isinstance(item, ToolCallOutputItem):
            raw = item.raw_item
            call_id = raw.get("call_id") if isinstance(raw, dict) else getattr(raw, "call_id", None)
            rid = receipt_id_from_output(item.output)
            if call_id and rid:
                receipt_for_call[call_id] = rid
    rows = conventional_rows(turns, host.receipts, receipt_for_call=receipt_for_call,
                             controller="LLM (inside the SDK Runner loop)", loop_name="the SDK Runner")
    return RunResult(
        title="Conventional agent -- OpenAI Agents SDK (Agent + Runner.run_sync + function tools)",
        model_label=model_label, task=task, status="completed (SDK final_output)",
        answer=str(result.final_output), rows=rows,
        notes=["the SDK ends the run when the model answers without a tool call; no host check of the answer", host.action_record()],
        counts={"model_calls": len(result.raw_responses), "host_tool_requests": len(host.receipts)},
        writes_executed=len(host.write_ledger))


def _decision(output: list[Any]) -> list[NativeTurnItem]:
    """Tool calls if the response has any (the loop continues); otherwise its message text (the run ends).

    Text sent alongside tool calls is shown as such (it is not a decision). Reasoning items are not shown.
    """
    calls = [NativeTurnItem("tool_call", tool=i.name, arguments=i.arguments, call_id=i.call_id)
             for i in output if getattr(i, "type", None) == "function_call"]
    text = "".join(getattr(part, "text", "") for i in output if getattr(i, "type", None) == "message"
                   for part in getattr(i, "content", []) or [])
    if calls:
        return ([NativeTurnItem("text", text=text)] if text.strip() else []) + calls
    return [NativeTurnItem("answer", text=text)]
