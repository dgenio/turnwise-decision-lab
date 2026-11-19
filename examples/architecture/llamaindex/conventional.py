"""A -- Conventional agent on LlamaIndex. The model controls every step.

A plain ``FunctionAgent`` with a system prompt and ``FunctionTool``s. The agent
workflow sends the chat history and tool schemas to the LLM, runs the tool
calls the LLM returns, appends the results and asks the LLM again, until the
LLM answers without a tool call. **The LLM chooses every operation.**

The tools call the shared host, which validates every request exactly as it
does for the Turnwise variant.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Literal

from llama_index.core.agent.workflow import AgentOutput, FunctionAgent, ToolCallResult
from llama_index.core.llms import ChatResponse
from llama_index.core.tools import FunctionTool
from pydantic import BaseModel, Field, create_model

from turnwise_lab.world import SERVICES

from ..incident_env import AGENT_INSTRUCTIONS, TOOLS, HostSession, IncidentHost, ToolSpec
from ..trace import NativeTurnItem, RunResult, conventional_rows, receipt_id_from_output


def build_agent(llm: Any, session: HostSession) -> FunctionAgent:
    """The agent both variants share: same system prompt, same tools, same LLM.

    ``streaming=False``: one complete LLM response per step, like the Agents SDK's ``Runner.run_sync``. This
    is a transport choice (the default streams the same response); it does not change who decides.
    """
    return FunctionAgent(
        name="incident_investigator",
        description="Investigates incidents with read tools.",
        system_prompt=AGENT_INSTRUCTIONS,
        tools=[_function_tool(spec, session) for spec in TOOLS],
        llm=llm,
        streaming=False,
    )


def _function_tool(spec: ToolSpec, session: HostSession) -> FunctionTool:
    def call(**kwargs: Any) -> str:
        return session.host.execute(spec.id, kwargs, proposed_by=session.actor).for_model()

    return FunctionTool.from_defaults(fn=call, name=spec.id, description=spec.description,
                                      fn_schema=_arguments_model(spec))


def _arguments_model(spec: ToolSpec) -> type[BaseModel]:
    if spec.param == "service":
        return create_model(f"{spec.id}_args", service=(Literal[SERVICES], Field(description="Service name.")))
    return create_model(f"{spec.id}_args", query=(str, Field(description="Free-text search query.")))


async def run_agent(agent: FunctionAgent, user_msg: str,
                    max_iterations: int) -> tuple[AgentOutput, list[list[NativeTurnItem]], dict[str, str]]:
    """Run the agent workflow. Every ``AgentOutput`` event is one LLM response, i.e. one LLM decision.

    The decision is read from the LLM's own response message with the LLM's
    ``get_tool_calls_from_response``: the final ``AgentOutput.tool_calls`` is
    extended by the workflow with every tool call of the run, so it is not a
    per-step record. ``ToolCallResult`` events give each call's host receipt
    by call id (the workflow may run one response's tool calls concurrently).
    """
    handler = agent.run(user_msg=user_msg, max_iterations=max_iterations)
    decisions: list[list[NativeTurnItem]] = []
    receipt_for_call: dict[str, str] = {}
    async for event in handler.stream_events():
        if isinstance(event, AgentOutput):
            calls = agent.llm.get_tool_calls_from_response(ChatResponse(message=event.response),
                                                           error_on_no_tool_call=False)
            text = event.response.content or ""
            items = [NativeTurnItem("tool_call", tool=c.tool_name, arguments=json.dumps(c.tool_kwargs),
                                    call_id=c.tool_id) for c in calls]
            if items and text.strip():
                items.insert(0, NativeTurnItem("text", text=text))
            decisions.append(items or [NativeTurnItem("answer", text=text)])
        elif isinstance(event, ToolCallResult):
            rid = receipt_id_from_output(event.tool_output.content)
            if rid:
                receipt_for_call[event.tool_id] = rid
    return await handler, decisions, receipt_for_call


def run_conventional(task: str, llm: Any, *, model_label: str, max_iterations: int = 10,
                     host: IncidentHost | None = None) -> RunResult:
    """``host`` may be passed in so a caller can still read its receipts if the run raises."""
    host = host or IncidentHost(task)
    agent = build_agent(llm, HostSession(host, actor="llm"))
    final, turns, receipt_for_call = asyncio.run(run_agent(agent, task, max_iterations))
    rows = conventional_rows(turns, host.receipts, receipt_for_call=receipt_for_call,
                             controller="LLM (inside the FunctionAgent workflow)", loop_name="the agent workflow")
    return RunResult(
        title="Conventional agent -- LlamaIndex (FunctionAgent + FunctionTool)",
        model_label=model_label, task=task, status="completed (FunctionAgent response)",
        answer=final.response.content or "", rows=rows,
        notes=["the workflow ends when the LLM answers without a tool call; no host check of the answer", host.action_record()],
        counts={"model_calls": len(turns), "host_tool_requests": len(host.receipts)},
        writes_executed=len(host.write_ledger))
