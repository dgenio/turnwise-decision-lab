"""A deterministic stand-in for the OpenAI Responses API. SIMULATED: no inference.

The offline demo replaces the *model object* with each framework's test double
(``agents.testing.ScriptedModel``, ``MockFunctionCallingLLM``). That leaves the
classes a live run actually uses untested: ``OpenAIResponsesModel`` and the
``openai`` client in the Agents SDK, and ``OpenAIResponses`` in LlamaIndex,
whose ``structured_predict`` takes a different internal path than the mock.

This double sits one level lower, at HTTP: it answers ``POST /v1/responses``
(non-streaming) from an ``httpx2.MockTransport``. So the real provider classes
build real requests, and parse responses in the provider's wire format, with no
network and no credentials. What the reply *says* comes from the same
``SimulatedInvestigator`` as the offline demo:

* a request with ``text.format.type == "json_schema"`` is one Turnwise step:
  the user message is the context packet, and the reply is a ``StepOutcome`` JSON text;
* any other request is a native tool-calling turn: the reply is one
  ``function_call`` item or a final message. A brain built with
  ``batch_reads=True`` returns several ``function_call`` items in one response
  (parallel tool calls), which is what the batched-native arm of
  ``cost_structure.py`` uses.

``faults`` scripts provider misbehaviour, one entry per request (``None`` =
normal), to show that each failure is visible: see ``FAULTS``. Every response
says ``"model": <requested model>``, and the usage numbers are synthetic.
"""
from __future__ import annotations

import json
from typing import Any

import httpx2

from .simulated_model import SimulatedInvestigator

PACKET_MARKER = "TURNWISE STEP PACKET:"  # LlamaIndex B prefixes the packet with this; the Agents SDK B does not

FAULTS = (
    "refusal",  # a refusal content part instead of output text
    "not_json",  # prose where the structured output should be
    "schema_violation",  # JSON that does not match StepOutcome
    "bad_arguments",  # a function call whose arguments are not JSON
    "unknown_tool",  # a function call naming a tool that does not exist
    "write_call",  # a native function call to rollback_deploy (never requested by the user)
    "write_proposal",  # a StepOutcome proposing rollback_deploy
    "step_function_call",  # a function call in reply to a structured (tool-less) Turnwise step
    "always_tool",  # a native turn that calls yet another tool, every time (runaway loop)
    "incomplete",  # status=incomplete (max_output_tokens) with no usable output
    "http_400", "http_401", "http_429", "http_500",
    "timeout",  # the transport times out; no response
)


class ProviderDouble:
    def __init__(self, brain: SimulatedInvestigator | None = None, faults: list[str | None] | None = None,
                 *, reasoning_items: bool = False):
        self.brain = brain or SimulatedInvestigator()
        self.faults = list(faults or [])
        self.reasoning_items = reasoning_items  # emit a reasoning item before each output, like reasoning models
        self.requests: list[dict[str, Any]] = []
        self._runaway = 0
        unknown = [f for f in self.faults if f is not None and f not in FAULTS]
        if unknown:
            raise ValueError(f"unknown faults {unknown}")

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self.handle)

    # ------------------------------------------------------------------ the endpoint
    def handle(self, request: httpx2.Request) -> httpx2.Response:
        if request.method != "POST" or not request.url.path.endswith("/responses"):
            return _error(404, f"the provider double does not implement {request.method} {request.url.path}")
        body = json.loads(request.content)
        self.requests.append(body)
        n = len(self.requests)
        fault = self.faults.pop(0) if self.faults else None
        if body.get("stream"):
            return _error(400, "the provider double does not emulate streaming")
        if fault == "timeout":
            raise httpx2.ReadTimeout("provider double: simulated read timeout", request=request)
        if fault and fault.startswith("http_"):
            code = int(fault.split("_")[1])
            return _error(code, {400: "invalid request", 401: "invalid API key", 429: "rate limit reached",
                                 500: "internal server error"}[code])
        if (body.get("store") is False and any(isinstance(i, dict) and i.get("type") == "reasoning"
                                                and i.get("id") and not i.get("encrypted_content")
                                                for i in body.get("input", []))):
            # The real API behaves like this: items are not persisted when store=false.
            return _error(404, "Item with id 'rs_…' not found. Items are not persisted when `store` is set to false.")
        step = ((body.get("text") or {}).get("format") or {}).get("type") == "json_schema"
        output = self._typed_step(body, n, fault) if step else self._native_turn(body, n, fault)
        status = "completed"
        incomplete = None
        if fault == "incomplete":
            output, status, incomplete = [], "incomplete", {"reason": "max_output_tokens"}
        if self.reasoning_items:
            output = [{"type": "reasoning", "id": f"rs_{n}", "summary": []}] + output
        out_chars = len(json.dumps(output))
        return httpx2.Response(200, json={
            "id": f"resp_double_{n}", "object": "response", "created_at": 0, "model": body.get("model"),
            "status": status, "incomplete_details": incomplete, "output": output,
            "parallel_tool_calls": True, "tool_choice": body.get("tool_choice", "auto"), "tools": [],
            "usage": {"input_tokens": len(request.content) // 4, "output_tokens": out_chars // 4,
                      "total_tokens": len(request.content) // 4 + out_chars // 4,
                      "input_tokens_details": {"cached_tokens": 0},
                      "output_tokens_details": {"reasoning_tokens": 0}}})

    # ------------------------------------------------------------------ replies
    def _typed_step(self, body: dict[str, Any], n: int, fault: str | None) -> list[dict[str, Any]]:
        if fault == "refusal":
            return [_message(n, refusal="I can't help with that request.")]
        if fault == "not_json":
            return [_message(n, text="Sure! The deploy probably caused it.")]
        if fault == "schema_violation":
            return [_message(n, text=json.dumps({"kind": "final_answer", "answer": "yes"}))]
        if fault == "step_function_call":
            return [_function_call(n, "validate_config", '{"service": "checkout"}')]
        text = _user_text(body)
        packet = json.loads(text.split(PACKET_MARKER, 1)[1] if PACKET_MARKER in text else text)
        outcome = self.brain.typed_step(packet)
        if fault == "write_proposal":
            outcome = {"kind": "tool_proposal", "text": "Roll the deploy back now.", "tool": "rollback_deploy",
                       "arguments_json": json.dumps({"service": "checkout"}), "cited_receipts": []}
        return [_message(n, text=json.dumps(outcome))]

    def _native_turn(self, body: dict[str, Any], n: int, fault: str | None) -> list[dict[str, Any]]:
        if fault == "refusal":
            return [_message(n, refusal="I can't help with that request.")]
        if fault == "bad_arguments":
            return [_function_call(n, "error_trend", '{"service": checkout')]
        if fault == "unknown_tool":
            return [_function_call(n, "delete_everything", '{"service": "checkout"}')]
        if fault == "write_call":
            return [_function_call(n, "rollback_deploy", '{"service": "checkout"}')]
        if fault == "always_tool":
            self._runaway += 1
            query = f"incident runbook page {self._runaway}"
            return [_function_call(n, "search_docs", json.dumps({"query": query}))]
        items = [i for i in body.get("input", []) if isinstance(i, dict)]
        tools = [t.get("name") for t in body.get("tools") or [] if isinstance(t, dict)]
        actions = self.brain.native_turn(
            instructions=_instructions(body), task=_user_text(body).split("\n")[0],
            tool_results=[str(i.get("output")) for i in items if i.get("type") == "function_call_output"]
                         + [line for line in _user_text(body).split("\n")[1:] if line.startswith("{")],
            tools=tools)
        if actions[0].kind == "tool_call":
            # One function_call item per action: more than one only when the brain batches reads.
            return [_function_call(n, a.tool, json.dumps(a.arguments), k) for k, a in enumerate(actions)]
        return [_message(n, text=actions[0].text)]


# ---------------------------------------------------------------- request parsing
def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    return "".join(p.get("text", "") for p in content or [] if isinstance(p, dict))


def _user_text(body: dict[str, Any]) -> str:
    items = body.get("input")
    if isinstance(items, str):
        return items
    return next((_text_of(i.get("content")) for i in items or [] if isinstance(i, dict) and i.get("role") == "user"), "")


def _instructions(body: dict[str, Any]) -> str:
    parts = [body.get("instructions") or ""]
    parts += [_text_of(i.get("content")) for i in body.get("input") or []
              if isinstance(i, dict) and i.get("role") in ("system", "developer")]
    return "\n".join(p for p in parts if p)


# ---------------------------------------------------------------- response items
def _message(n: int, *, text: str | None = None, refusal: str | None = None) -> dict[str, Any]:
    part = ({"type": "refusal", "refusal": refusal} if refusal is not None
            else {"type": "output_text", "text": text, "annotations": []})
    return {"type": "message", "id": f"msg_double_{n}", "role": "assistant", "status": "completed", "content": [part]}


def _function_call(n: int, name: str, arguments: str, k: int = 0) -> dict[str, Any]:
    suffix = f"{n}" if k == 0 else f"{n}_{k}"  # the first call of a response keeps the historical id
    return {"type": "function_call", "id": f"fc_double_{suffix}", "call_id": f"call_double_{suffix}", "name": name,
            "arguments": arguments, "status": "completed"}


def _error(code: int, message: str) -> httpx2.Response:
    return httpx2.Response(code, json={"error": {"message": f"provider double: {message}", "type": "double_error",
                                                 "code": None, "param": None}})
