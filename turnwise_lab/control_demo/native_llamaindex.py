"""Native baseline: a conventional LlamaIndex ``FunctionAgent`` on the same world and tools.

One ``FunctionAgent`` with the shared instructions and every catalog tool. The model
decides each next tool call and the agent workflow executes it, feeding the result
back until the model answers. Tool calls go through the shared ``Host``.

No network, keys or paid inference: the model is LlamaIndex's own test double
(``MockFunctionCallingLLM``), whose response generator applies the same
``IncidentModel`` rules as the other configurations. The workflow's event stream
(``ToolCall`` / ``ToolCallResult`` / ``AgentOutput``) is the native instrumentation.

Optional dependency: ``pip install "turnwise-decision-lab[demo-llamaindex]"``.
"""
from __future__ import annotations

import asyncio
from collections import Counter
import json
from typing import Literal

from .model import INSTRUCTIONS, Answer, IncidentModel, ToolRequest
from .trace import DemoRun, Step
from .world import CATALOG, SERVICES, Host, as_model_text

NATIVE_LLAMA = "native model (FunctionAgent)"
FRAMEWORK_DIFFERENCES = (
    "The agent workflow returns every tool result to the model, which chooses the next step; there is no policy "
    "seam between a model tool call and its execution.",
    "The final output is whatever the model returns; the agent has no host-side grounding check before finishing.",
    "FunctionAgent has no per-tool approval pause: a write reaches the host, which records an approval request and "
    "returns it to the model (human-in-the-loop exists as separate workflow events, not used here).",
    "Tool schemas are generated from a pydantic model, so they add 'title' keys; properties, enum and required "
    "match the shared catalog.",
    "max_iterations bounds agent iterations; the Turnwise max_steps counts policy steps (both 8 here).",
)


def available() -> bool:
    try:
        from llama_index.core.agent.workflow import FunctionAgent  # noqa: F401
        from llama_index.core.llms.mock import MockFunctionCallingLLM  # noqa: F401
        return True
    except ImportError:
        return False


def _context_from_messages(messages) -> tuple[str, dict[str, dict]]:
    """The user request and the tool results the model can see, from the chat history."""
    from llama_index.core.base.llms.types import MessageRole, ToolCallBlock
    request, names, seen = "", {}, {}
    for m in messages:
        if m.role == MessageRole.USER and not request:
            request = m.content or ""
        elif m.role == MessageRole.ASSISTANT:
            for b in m.blocks:
                if isinstance(b, ToolCallBlock):
                    names[b.tool_call_id] = b.tool_name
        elif m.role == MessageRole.TOOL:
            seen[names[m.additional_kwargs["tool_call_id"]]] = json.loads(m.content)
    return request, seen


def run_native_llamaindex(request: str, *, host: Host | None = None, model: IncidentModel | None = None,
                          max_iterations: int = 8) -> DemoRun:
    from llama_index.core import __version__ as li_version
    from llama_index.core.agent.workflow import FunctionAgent
    from llama_index.core.base.llms.types import ChatMessage, MessageRole, ToolCallBlock
    from llama_index.core.llms.mock import MockFunctionCallingLLM
    from llama_index.core.tools import FunctionTool
    from pydantic import Field, create_model

    host, model = host or Host(), model or IncidentModel()
    outputs: list[ToolRequest | Answer] = []
    args_model = create_model("ServiceArgs", service=(Literal[SERVICES], Field(...)))  # type: ignore[valid-type]

    def make_tool(name: str, description: str):
        def call(service: str) -> str:
            # FunctionTool does not pass the call id to the function; the host receipt is matched by order.
            return as_model_text(host.submit(name, {"service": service}, proposer="native model via FunctionAgent",
                                             call_id=f"call_{len(outputs)}"))
        return FunctionTool.from_defaults(fn=call, name=name, description=description, fn_schema=args_model)

    def response_generator(messages, **kwargs):
        user_request, seen = _context_from_messages(messages)
        out = model.respond(user_request, seen)
        outputs.append(out)
        if isinstance(out, ToolRequest):
            return ChatMessage(role=MessageRole.ASSISTANT, blocks=[ToolCallBlock(
                tool_call_id=f"call_{len(outputs)}", tool_name=out.name, tool_kwargs=dict(out.arguments))])
        return ChatMessage(role=MessageRole.ASSISTANT, content=out.text)

    tools = [make_tool(t.name, t.description) for t in CATALOG]
    agent = FunctionAgent(tools=tools, llm=MockFunctionCallingLLM(response_generator=response_generator),
                          system_prompt=INSTRUCTIONS)

    async def drive():
        handler = agent.run(user_msg=request, max_iterations=max_iterations)
        events = [type(ev).__name__ async for ev in handler.stream_events()]
        return await handler, events

    result, events = asyncio.run(drive())

    receipts = {r["call_id"]: r for r in host.receipts}
    steps: list[Step] = []
    final = None
    for k, out in enumerate(outputs, start=1):
        if isinstance(out, ToolRequest):
            receipt = receipts[f"call_{k}"]
            steps.append(Step(k, NATIVE_LLAMA, "call_tool", {"tool": out.name, "arguments": out.arguments},
                              receipt["validation"], f"{receipt['observation_status']}: {receipt['fact_keys']} -> back to the model",
                              NATIVE_LLAMA))
        else:
            steps.append(Step(k, NATIVE_LLAMA, "answer", {"cites": list(out.cites)}, "-", "final output", None,
                              "model produced the final output; the agent ended the run"))
            final = {"kind": "answer", "text": result.response.content, "decided_by": NATIVE_LLAMA,
                     "cites": list(out.cites)}
    if final is None:
        final = {"kind": "max_iterations", "text": f"max_iterations of {max_iterations} reached",
                 "decided_by": NATIVE_LLAMA, "cites": []}
    notes = {"framework": f"llama-index-core {li_version}", "model": f"MockFunctionCallingLLM -> {model.version}",
             "max_iterations": max_iterations, "tools_offered": [t.metadata.name for t in tools],
             "schemas_offered": {t.metadata.name: t.metadata.get_parameters_dict() for t in tools},
             "instructions_offered": agent.system_prompt, "workflow_events": dict(Counter(events)),
             "framework_differences": list(FRAMEWORK_DIFFERENCES)}
    return DemoRun("LlamaIndex native FunctionAgent", request, steps, final, list(host.receipts), len(outputs), notes)
