"""Turnwise configuration: the same model and tools, with a per-step policy as the controller.

The policy proposes every next operation. A model call is one of those operations,
and its output (a typed tool request or an answer candidate) comes back as an
*observation*: nothing the model asks for runs until the policy decides again,
and anything the policy submits is validated by the host. The policy may finish
without another model call; the host checks that the answer only cites evidence
it actually returned.

The policy here is a handful of explicit rules for one task type (a causal
question about one service). It stands in for a cheap typed policy; it is not a
learned model and makes no claim of being better than a native agent (#9).
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import re

from .model import Answer, IncidentModel, ToolRequest, named_service
from .trace import HOST, POLICY, DemoRun, Step
from .world import CATALOG_BY_NAME, Host, as_model_text

CAUSAL = re.compile(r"\b(?:why|explain|cause|caused|because|could .* explain)\b", re.I)
# Evidence the policy gathers itself for a causal question before spending a model call.
REQUIRED_EVIDENCE = ("get_error_metrics", "get_deployment_history")
MAX_MODEL_CALLS = 3


@dataclass(frozen=True)
class Operation:
    kind: str  # call_tool | call_model | adopt_model_request | decline_model_request | finish | clarify | abstain
    tool: str | None = None
    arguments: dict | None = None
    reason: str = ""


@dataclass
class TurnState:
    request: str
    service: str | None
    seen: dict[str, dict] = field(default_factory=dict)   # tool -> result, exactly as shown to the model
    pending: ToolRequest | Answer | None = None            # the latest model output, not yet acted on
    model_calls: int = 0


class RulePolicy:
    name = "turnwise-rules/1"

    def next_operation(self, s: TurnState) -> Operation:
        if isinstance(s.pending, ToolRequest):
            return self._decide_on_model_request(s, s.pending)
        if isinstance(s.pending, Answer):
            return Operation("finish", reason="model produced an answer candidate; host checks its grounding")
        if s.service is None:
            return Operation("clarify", reason="no single service named")
        if CAUSAL.search(s.request):
            for tool in REQUIRED_EVIDENCE:
                if tool not in s.seen:
                    return Operation("call_tool", tool, {"service": s.service}, "required evidence for a causal question")
        if s.model_calls >= MAX_MODEL_CALLS:
            return Operation("abstain", reason=f"model-call budget of {MAX_MODEL_CALLS} reached")
        return Operation("call_model", reason="evidence gathered; reasoning needs the model")

    @staticmethod
    def _decide_on_model_request(s: TurnState, req: ToolRequest) -> Operation:
        spec = CATALOG_BY_NAME.get(req.name)
        if spec is None:
            return Operation("decline_model_request", req.name, req.arguments, "not a registered tool")
        if spec.side_effect:
            return Operation("decline_model_request", req.name, req.arguments,
                             "the user asked a question; no action was requested")
        if req.arguments.get("service") != s.service:
            return Operation("decline_model_request", req.name, req.arguments, "different service from the user's request")
        if req.name in s.seen:
            return Operation("decline_model_request", req.name, req.arguments, "already observed in this turn")
        return Operation("adopt_model_request", req.name, req.arguments, "registered read on the requested service")


def run_turnwise(request: str, *, host: Host | None = None, model: IncidentModel | None = None,
                 policy: RulePolicy | None = None, max_steps: int = 8) -> DemoRun:
    host, model, policy = host or Host(), model or IncidentModel(), policy or RulePolicy()
    s = TurnState(request, named_service(request))
    steps: list[Step] = []
    final = None
    for index in range(1, max_steps + 1):
        op = policy.next_operation(s)
        if op.kind in ("call_tool", "adopt_model_request"):
            origin = "policy" if op.kind == "call_tool" else "policy, adopting a model request"
            obs = host.submit(op.tool, op.arguments, proposer=origin, call_id=f"tw-{index}")
            s.seen[op.tool] = json.loads(as_model_text(obs))
            s.pending = None
            steps.append(Step(index, POLICY, op.kind, {"tool": op.tool, "arguments": op.arguments},
                              host.receipts[-1]["validation"], f"{obs['status']}: {list(obs.get('facts', {}))}", POLICY))
        elif op.kind == "decline_model_request":
            s.seen[op.tool] = {"tool": op.tool, "status": "declined_by_policy", "reason": op.reason}
            s.pending = None
            steps.append(Step(index, POLICY, op.kind, {"tool": op.tool, "arguments": op.arguments}, "not_submitted",
                              f"declined: {op.reason}", POLICY))
        elif op.kind == "call_model":
            s.model_calls += 1
            out = model.respond(request, {k: dict(v) for k, v in s.seen.items()})
            s.pending = out
            seen_by_model = (f"tool request {out.name}({out.arguments}), not executed"
                             if isinstance(out, ToolRequest) else f"answer candidate citing {list(out.cites)}")
            steps.append(Step(index, POLICY, "call_model", {"model": model.version}, "-",
                              f"model output -> observation: {seen_by_model}", POLICY))
        elif op.kind == "finish":
            answer = s.pending
            grounded = bool(answer.cites) and set(answer.cites) <= host.observed_fact_keys()
            if grounded:
                final = {"kind": "answer", "text": answer.text, "decided_by": POLICY, "cites": list(answer.cites)}
                steps.append(Step(index, POLICY, "finish", {"cites": list(answer.cites)}, "grounded",
                                  "answer cites only host-returned evidence", None, "policy finished; host checked grounding"))
            else:
                final = {"kind": "abstain", "text": "Stopped: the answer cites evidence the host never returned.",
                         "decided_by": HOST, "cites": list(answer.cites)}
                steps.append(Step(index, POLICY, "finish", {"cites": list(answer.cites)}, "ungrounded",
                                  "host refused an answer citing unreturned evidence", None, "host abstained"))
            break
        else:  # clarify | abstain
            final = {"kind": op.kind, "text": op.reason, "decided_by": POLICY, "cites": []}
            steps.append(Step(index, POLICY, op.kind, None, "-", op.reason, None, f"policy chose {op.kind}"))
            break
    if final is None:
        final = {"kind": "abstain", "text": f"step limit of {max_steps} reached", "decided_by": HOST, "cites": []}
    return DemoRun("Turnwise per-step policy", request, steps, final, list(host.receipts), s.model_calls,
                   {"policy": policy.name, "model": model.version, "max_steps": max_steps})
