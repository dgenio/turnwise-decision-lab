"""Native baseline: a conventional OpenAI Agents SDK agent on the same world and tools.

One ``Agent`` with the shared instructions and every catalog tool, run by ``Runner.run``.
The model decides each next tool call and the Runner executes it, feeding the result
back to the model until it produces a final output. Tool calls still go through the
shared ``Host``; write tools use the SDK's own ``needs_approval`` so a write pauses the
run for a human instead of executing.

No network, keys or paid inference: the model is the SDK's own test double
(``agents.testing.ScriptedModel``), whose responder applies the same ``IncidentModel``
rules as the Turnwise configuration. SDK tracing runs normally but is routed to an
in-memory collector instead of the default exporter.

Optional dependency: ``pip install "turnwise-decision-lab[demo-openai]"``.
"""
from __future__ import annotations

import asyncio
from collections import Counter
from contextlib import contextmanager
import json

from .model import INSTRUCTIONS, Answer, IncidentModel, ToolRequest
from .trace import NATIVE_MODEL, DemoRun, Step
from .world import CATALOG, Host, as_model_text

FRAMEWORK_DIFFERENCES = (
    "The Runner returns every tool result to the model, which chooses the next step; there is no policy seam "
    "between a model tool call and its execution (only guardrails and approvals around it).",
    "The final output is whatever the model returns; the Runner has no host-side grounding check before finishing.",
    "Write tools use the SDK's needs_approval: the run pauses with an interruption and the host never sees the call.",
    "max_turns counts model turns; the Turnwise max_steps counts policy steps (both 8 here).",
)


def available() -> bool:
    try:
        import agents  # noqa: F401
        from agents.testing import ScriptedModel  # noqa: F401
        return True
    except ImportError:
        return False


@contextmanager
def _local_tracing():
    """Route SDK traces to memory for the run (never to the default exporter), then restore the processors."""
    from agents.tracing import TracingProcessor, get_trace_provider, set_trace_processors

    class Collector(TracingProcessor):
        def __init__(self):
            self.spans: list[dict] = []

        def on_trace_start(self, trace): pass
        def on_trace_end(self, trace): pass
        def on_span_start(self, span): pass

        def on_span_end(self, span):
            self.spans.append(span.export() or {})

        def shutdown(self): pass
        def force_flush(self): pass

    previous = getattr(getattr(get_trace_provider(), "_multi_processor", None), "_processors", None)
    collector = Collector()
    set_trace_processors([collector])
    try:
        yield collector.spans
    finally:
        if previous is not None:
            set_trace_processors(list(previous))


def _context_from_input(items) -> tuple[str, dict[str, dict]]:
    """The user request and the tool results the model can see, from the SDK's Responses-format input."""
    request, names, seen = "", {}, {}
    for item in items if isinstance(items, list) else [{"role": "user", "content": items}]:
        d = item if isinstance(item, dict) else item.model_dump()
        if d.get("role") == "user" and not request:
            content = d.get("content")
            request = content if isinstance(content, str) else " ".join(c.get("text", "") for c in content or [])
        elif d.get("type") == "function_call":
            names[d["call_id"]] = d["name"]
        elif d.get("type") == "function_call_output":
            seen[names[d["call_id"]]] = json.loads(d["output"])
    return request, seen


def run_native_openai(request: str, *, host: Host | None = None, model: IncidentModel | None = None,
                      max_turns: int = 8) -> DemoRun:
    from agents import Agent, FunctionTool, RunConfig, Runner
    from agents import __version__ as sdk_version
    from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call

    host, model = host or Host(), model or IncidentModel()
    outputs: list[ToolRequest | Answer] = []

    def invoker(name: str):
        async def on_invoke_tool(ctx, args_json: str) -> str:
            return as_model_text(host.submit(name, json.loads(args_json), proposer="native model via Runner",
                                             call_id=ctx.tool_call_id))
        return on_invoke_tool

    tools = [FunctionTool(name=t.name, description=t.description, params_json_schema=t.json_schema(),
                          on_invoke_tool=invoker(t.name), strict_json_schema=True, needs_approval=t.side_effect)
             for t in CATALOG]

    def responder(call):
        user_request, seen = _context_from_input(call.input)
        out = model.respond(user_request, seen)
        outputs.append(out)
        if isinstance(out, ToolRequest):
            return [function_call(out.name, out.arguments, call_id=f"call_{len(outputs)}")]
        return [assistant_message(out.text)]

    scripted = ScriptedModel([ModelStep.respond(responder) for _ in range(max_turns)], emit_traces=True)
    agent = Agent(name="incident-assistant", instructions=INSTRUCTIONS, tools=tools, model=scripted)
    with _local_tracing() as spans:
        result = asyncio.run(Runner.run(agent, request, max_turns=max_turns, run_config=RunConfig(
            workflow_name="control-demo-native", trace_include_sensitive_data=True)))

    receipts = {r["call_id"]: r for r in host.receipts}
    steps: list[Step] = []
    final = None
    for k, out in enumerate(outputs, start=1):
        if isinstance(out, ToolRequest):
            receipt = receipts.get(f"call_{k}")
            if receipt is None:
                steps.append(Step(k, NATIVE_MODEL, "call_tool", {"tool": out.name, "arguments": out.arguments},
                                  "not_submitted", "SDK paused the run for human approval (needs_approval)", None,
                                  "Runner interrupted: pending tool approval"))
                final = {"kind": "awaiting_approval", "text": f"{out.name}({out.arguments}) awaits human approval",
                         "decided_by": NATIVE_MODEL, "cites": []}
                break
            steps.append(Step(k, NATIVE_MODEL, "call_tool", {"tool": out.name, "arguments": out.arguments},
                              receipt["validation"], f"{receipt['observation_status']}: {receipt['fact_keys']} -> back to the model",
                              NATIVE_MODEL))
        else:
            steps.append(Step(k, NATIVE_MODEL, "answer", {"cites": list(out.cites)}, "-", "final output", None,
                              "model produced the final output; the Runner ended the run"))
            final = {"kind": "answer", "text": result.final_output, "decided_by": NATIVE_MODEL, "cites": list(out.cites)}
    if final is None:
        final = {"kind": "max_turns", "text": f"max_turns of {max_turns} reached", "decided_by": NATIVE_MODEL, "cites": []}
    notes = {"sdk": f"openai-agents {sdk_version}", "model": f"agents.testing.ScriptedModel -> {model.version}",
             "max_turns": max_turns, "interruptions": [i.raw_item.name for i in getattr(result, "interruptions", [])],
             "tools_offered": [t.name for t in scripted.calls[0].tools] if scripted.calls else [],
             "schemas_offered": {t.name: t.params_json_schema for t in scripted.calls[0].tools} if scripted.calls else {},
             "instructions_offered": scripted.calls[0].system_instructions if scripted.calls else None,
             "sdk_span_types": dict(Counter((s.get("span_data") or {}).get("type") for s in spans)),
             "framework_differences": list(FRAMEWORK_DIFFERENCES)}
    return DemoRun("OpenAI Agents SDK native agent", request, steps, final, list(host.receipts), len(scripted.calls), notes)
