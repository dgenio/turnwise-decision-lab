"""Capability-preserving escalation (#12): continue an unresolved turn with the tool-capable heavy agent.

v0.6's conservative gate replaced an uncertain decision with a *text-only* heavy
generation call. That generator could not call tools or raise an approval
request, so on held-out H18/H19 both requested actions were silently dropped
(``reports/v06/audit.md`` section 2). This module is the opt-in replacement: a
bounded continuation by the same native tool-calling heavy agent that serves as
the heavy-only baseline (same system prompt, tool schemas, parser, host
validation, fact rendering and per-round token limit), resumed from the turn's
host state. ``heavy_agent.py`` itself is unchanged.

Host-side invariants (no model output, controller hint or tool result can change them):

I1 Capability: the continuation exposes every catalog tool and the approval hold; it is never
   text-only. With no heavy agent configured, or no budget left, the turn abstains instead.
I2 Contract: the host builds it: the exact request, the conversation, the principal's permissions,
   prior receipts and the remaining budget. Controller hints are re-checked; bad ones are recorded
   and ignored.
I3 Authority: writes are never executed. A write proposal becomes an approval hold, and only when
   its service is one the user named; otherwise the action is kept for confirmation, not guessed.
I4 No silent drop: a pending action ends held for approval, in a host clarification that names it,
   or listed as not attempted in an abstention. Never as an ordinary answer.
I5 Bounds: model rounds share the turn's step budget; tool calls (and optionally newly computed
   tokens) are capped; calls that already succeeded in the turn are rejected, not repeated; a model
   error abstains.
I6 Status: final action statuses come from host receipts. When an action is involved the final text
   is written by the host; the model's prose is kept separately for audit.

Not covered: whether the heavy agent recognises an action the controller did not rank first (model
competence, to be measured on new cases under #9), and unsupported action claims in ordinary
answers where no action was involved (#13).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json

from .contracts import ActionIntent, Decision, Handoff, Observation, Question
from .heavy_agent import _PREFIX_CACHE, CALL_RE, parse_call, system_block
from .host import CATALOG_BY_ID, Capability, Host, Validation
from .loop import _obs_json
from .providers import named_services
from .render import render_facts
from .world import SERVICES

CONTRACT_VERSION = "turnwise.handoff/0.1"


def grounded_services(message: str, conversation) -> tuple[str, ...]:
    """Every service the user named in this session, current message first. Model output and tool data never count."""
    out = list(named_services(message))
    for m in conversation or ():
        if m.get("role") == "user":
            out += [s for s in named_services(str(m.get("content", ""))) if s not in out]
    return tuple(out)


def _grounded_args(cap: Capability, args: dict, grounded: tuple[str, ...]) -> dict:
    """The subset of proposed write arguments the host can stand behind; anything else is left for confirmation."""
    out = {}
    if "service" in cap.params and args.get("service") in SERVICES and args.get("service") in grounded:
        out["service"] = args["service"]
    if "message" in cap.params and isinstance(args.get("message"), str) and 0 < len(args["message"]) <= 300:
        out["message"] = args["message"]
    return out


def describe(capability: str, arguments: dict) -> str:
    cap = CATALOG_BY_ID[capability]
    call = f"{capability}({', '.join(f'{k}={v}' for k, v in arguments.items())})"
    missing = [p for p in cap.params if p not in arguments]
    return call + (f" with {', '.join(missing)} not specified" if missing else "")


@dataclass(frozen=True)
class HandoffContract:
    """What the heavy agent continues from. Built by the host, never by a decision provider."""
    version: str
    reason: str
    user_message: str
    conversation: tuple
    principal: str
    permissions: tuple[str, ...]
    tools: tuple[str, ...]
    approval_hold: bool
    writes_executable: bool
    receipts: tuple[dict, ...]
    pending_intents: tuple[ActionIntent, ...]
    ignored_hints: tuple[dict, ...]
    controller: dict
    grounded_services: tuple[str, ...]
    remaining_rounds: int
    max_tool_calls: int
    max_computed_tokens: int | None

    def as_json(self) -> dict:
        return json.loads(json.dumps(asdict(self)))


def build_contract(decision: Decision, state, host: Host, remaining_rounds: int) -> HandoffContract:
    hint = decision.handoff if isinstance(decision.handoff, Handoff) else None
    grounded = grounded_services(state.user_message, state.conversation)
    pending, ignored = [], []
    if decision.handoff is not None and hint is None:
        ignored.append({"hint": repr(decision.handoff)[:300], "reason": "not a typed Handoff"})
    for intent in (hint.pending_intents if hint else []):
        cap = CATALOG_BY_ID.get(getattr(intent, "capability", "") or "")
        if cap is None or not cap.side_effect:
            ignored.append({"hint": asdict(intent) if isinstance(intent, ActionIntent) else repr(intent),
                            "reason": "not a registered side-effecting capability"})
            continue
        pending.append(ActionIntent(cap.id, _grounded_args(cap, dict(intent.arguments or {}), grounded), "controller_candidate"))
    return HandoffContract(
        CONTRACT_VERSION, hint.reason if hint else "unspecified", state.user_message,
        tuple(dict(m) for m in state.conversation), host.identity.principal, tuple(sorted(host.identity.permissions)),
        tuple(c.id for c in host.allowed_capabilities()), True, False,
        tuple(_obs_json(o) for o in state.observations), tuple(pending), tuple(ignored),
        {"choice": hint.controller_choice if hint else None, "score": hint.controller_score if hint else None,
         "gate": hint.gate if hint else None, "provider": decision.provider},
        grounded, max(0, remaining_rounds), host.limits.max_handoff_tool_calls, host.limits.max_handoff_computed_tokens)


def handoff_note(contract: HandoffContract) -> str:
    """Host-written context for the heavy agent. Empty when there is nothing to carry (then the prompt equals the baseline's)."""
    parts = []
    lines = []
    for r in contract.receipts:
        if r["status"] == "ok":
            lines.append(render_facts(r["facts"]))
        elif r["status"] == "error":
            lines.append(json.dumps({"tool": r["target"], "error": r["status"], "reason": r["reason"]}))
    if lines:
        parts.append("Tool results already gathered in this turn (do not repeat these calls):\n<tool_response>\n"
                     + "\n".join(lines) + "\n</tool_response>")
    if contract.pending_intents:
        acts = "; ".join(describe(i.capability, i.arguments) for i in contract.pending_intents)
        parts.append(f"The request may ask for this action: {acts}. If the user asked for it, call the tool; it only creates "
                     "an approval request for a human. If the target is unclear, ask. Never say it was done.")
    return ("[host note, not from the user] " + "\n".join(parts)) if parts else ""


@dataclass
class HandoffResult:
    outcome: str  # answer | malformed | round_budget | token_budget | error | not_run
    detail: str
    ledger: list[dict]
    model: str = ""
    model_text: str | None = None
    steps: list[dict] = field(default_factory=list)
    rounds: int = 0
    tool_calls: int = 0
    computed_tokens: int = 0
    cached_prompt_tokens: int = 0

    def summary(self) -> dict:
        return {"outcome": self.outcome, "detail": self.detail, "model": self.model, "rounds": self.rounds,
                "tool_calls": self.tool_calls, "computed_tokens": self.computed_tokens,
                "cached_prompt_tokens": self.cached_prompt_tokens}


def _keep_pending(ledger: list[dict], cap: Capability, args: dict, grounded, reason: str, call_id: str) -> None:
    """A write the host could not hold stays visible as a pending intent (never dropped, never guessed)."""
    for e in ledger:
        if e["capability"] == cap.id and e["status"] == "pending":
            e["notes"].append(f"{call_id}: {reason}")
            return
    ledger.append({"capability": cap.id, "arguments": _grounded_args(cap, args, grounded), "source": "heavy_agent_proposal",
                   "status": "pending", "notes": [f"{call_id}: {reason}"]})


def _hold(ledger: list[dict], cap: Capability, args: dict, call_id: str) -> None:
    # A pending intent is resolved by a hold of the same capability on the same target. A status message is
    # content, not a target: the approver sees the exact text, so it does not have to match the request's wording.
    for e in ledger:
        if e["capability"] == cap.id and e["status"] == "pending" and all(
                args.get(k) == v for k, v in e["arguments"].items() if k != "message"):
            e.update(arguments=dict(args), status="held_for_approval")
            e["notes"].append(f"{call_id}: proposed by the heavy agent; held for approval")
            return
    ledger.append({"capability": cap.id, "arguments": dict(args), "source": "heavy_agent_proposal",
                   "status": "held_for_approval", "notes": [f"{call_id}: held for approval"]})


def run_handoff(contract: HandoffContract, *, host: Host, lm, observations: list[Observation], turn_id: str,
                first_step_index: int) -> HandoffResult:
    """Bounded native tool-calling continuation. Appends every host observation to ``observations`` (the turn's state)."""
    ledger = [{"capability": i.capability, "arguments": dict(i.arguments), "source": i.source, "status": "pending",
               "notes": ["the controller's own choice before the uncertainty gate"]} for i in contract.pending_intents]
    res = HandoffResult("round_budget", f"handoff round budget of {contract.remaining_rounds} reached", ledger)
    if lm is None:
        res.outcome, res.detail = "not_run", "no tool-capable heavy agent is configured; a text-only fallback is not allowed"
        return res
    res.model = getattr(lm, "version", "")
    if contract.remaining_rounds < 1:
        res.outcome, res.detail = "not_run", "no step budget left for the handoff"
        return res
    max_new = host.limits.max_generation_tokens["heavy"]
    try:
        sysb = system_block(host, lm.arch)  # identical system prompt + tool schemas to the heavy-only baseline
        key = (lm.version, sysb)
        if key not in _PREFIX_CACHE:
            _, st0, n0 = lm.extend(sysb)
            _PREFIX_CACHE[key] = (st0, n0)
        st, past = _PREFIX_CACHE[key]
    except Exception as exc:  # never fall back to text-only generation
        res.outcome, res.detail = "error", f"heavy agent unavailable ({type(exc).__name__})"
        return res
    convo = "".join(f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>\n" for m in contract.conversation)
    pending = convo + f"<|im_start|>user\n{contract.user_message}<|im_end|>\n"
    note = handoff_note(contract)
    if note:
        pending += f"<|im_start|>user\n{note}<|im_end|>\n"
    pending += lm.assistant_header()
    cap_tokens = contract.max_computed_tokens
    for r in range(contract.remaining_rounds):
        if cap_tokens is not None and res.computed_tokens >= cap_tokens:
            res.outcome, res.detail = "token_budget", f"handoff computed-token budget of {cap_tokens} reached"
            break
        try:
            g, st, past = lm.generate_continue(pending, st, past, max_new_tokens=max_new)
        except Exception as exc:  # timeout, backend failure: abstain, do not guess
            res.outcome, res.detail = "error", f"heavy agent error ({type(exc).__name__})"
            break
        step_index = first_step_index + r
        gen = {"status": "ok", "tier": "heavy", "model": lm.version, "text": g.text, "prompt_tokens": g.prompt_tokens,
               "cached_prompt_tokens": past - g.prompt_tokens - g.completion_tokens, "completion_tokens": g.completion_tokens,
               "prefill_ms": g.prefill_ms, "decode_ms": g.decode_ms, "stopped": g.stopped}
        step = {"step_index": step_index, "decision_call_id": f"{turn_id}/h{r + 1}", "handoff_round": r + 1, "generation": gen}
        res.steps.append(step)
        res.rounds += 1
        res.computed_tokens += g.prompt_tokens + g.completion_tokens
        res.cached_prompt_tokens += max(0, gen["cached_prompt_tokens"])
        calls = CALL_RE.findall(g.text)
        if not calls:
            if "<tool_call>" in g.text:
                res.outcome, res.detail = "malformed", "malformed tool call"
            else:
                res.outcome, res.detail, res.model_text = "answer", "heavy agent produced a final answer", g.text
            step["terminate_reason"] = res.detail
            break
        step["tool_calls"], responses = [], []
        for k, raw in enumerate(calls):
            call_id = f"{turn_id}/h{r + 1}c{k + 1}"
            name, args = parse_call(raw)
            cap = CATALOG_BY_ID.get(name or "")
            op = "call_workflow" if cap and cap.kind == "workflow" else "call_tool"
            d = Decision(op, name, dict(args) if isinstance(args, dict) else {}, provider="heavy-agent (handoff)",
                         model=lm.version, questions=[Question("tool_call", [], name, None, "none: generated tool call text")])
            if res.tool_calls >= contract.max_tool_calls:
                v = Validation(False, d, "rejected", f"handoff tool-call budget of {contract.max_tool_calls} exhausted")
            else:
                v = host.validate(d, observations)  # same host; earlier receipts make repeats fail
            res.tool_calls += 1
            duplicate = False
            if v.ok and v.status == "approval_required":
                duplicate = any(e["status"] == "held_for_approval" and e["capability"] == cap.id
                                and e["arguments"] == d.arguments for e in ledger)
                if "service" in cap.params and d.arguments.get("service") not in contract.grounded_services:
                    v = Validation(False, d, "rejected", f"service {d.arguments.get('service')!r} was not named by the user; "
                                   "ask which service is meant")
                elif duplicate:
                    v = Validation(False, d, "rejected", "approval for this action was already requested in this turn")
            if not v.ok:
                obs = Observation(step_index, call_id, op, name, d.arguments, "rejected", reason=v.reason)
                content = json.dumps({"error": v.reason})
                if cap is not None and cap.side_effect and not duplicate:
                    _keep_pending(ledger, cap, d.arguments, contract.grounded_services, v.reason, call_id)
            elif v.status == "approval_required":
                obs = Observation(step_index, call_id, op, name, d.arguments, "approval_required", reason=v.reason)
                content = json.dumps({"status": "approval_requested", "executed": False, "note": "a human must approve this action"})
                _hold(ledger, cap, d.arguments, call_id)
            else:
                obs = host.execute(d, step_index=step_index, call_id=call_id, user_text=contract.user_message)
                content = render_facts(obs.facts) if obs.status == "ok" else json.dumps({"error": obs.status, "reason": obs.reason})
            observations.append(obs)
            step["tool_calls"].append({"decision": d.as_json(), "validation": {"status": v.status, "reason": v.reason},
                                       "observation": _obs_json(obs)})
            responses.append(f"<tool_response>\n{content}\n</tool_response>")
        step["continue_reason"] = "tool responses returned to the heavy agent"
        pending = "<|im_end|>\n<|im_start|>user\n" + "\n".join(responses) + "<|im_end|>\n" + lm.assistant_header()
    return res


def compose_final(result: HandoffResult, host: Host) -> dict:
    """Host-owned final envelope. Action statuses come from the ledger of host receipts, never from model prose."""
    held = [e for e in result.ledger if e["status"] == "held_for_approval"]
    open_ = [e for e in result.ledger if e["status"] == "pending"]
    if held:
        lines = [host.approval_message(Observation(0, "", "call_tool", e["capability"], e["arguments"], "approval_required"))
                 for e in held]
        if open_:
            for e in open_:
                e["status"] = "needs_confirmation"
            lines.append(host.confirm_actions_message([describe(e["capability"], e["arguments"]) for e in open_]))
        kind, text, by, reason = "approval_required", "\n".join(lines), "host", "side effect needs human approval"
    elif open_ and result.outcome == "answer":
        for e in open_:
            e["status"] = "needs_confirmation"
        kind, by, reason = "clarify", "host", "a pending action was not resolved by the heavy agent"
        text = host.confirm_actions_message([describe(e["capability"], e["arguments"]) for e in open_])
    elif open_:
        for e in open_:
            e["status"] = "not_attempted"
        kind, by, reason = "abstain", "host", f"handoff_{result.outcome}"
        text = (host.abstain_message(result.detail) + " Not attempted: "
                + "; ".join(describe(e["capability"], e["arguments"]) for e in open_) + ".")
    elif result.outcome == "answer":
        kind, text, by, reason = "answer", result.model_text, f"heavy agent (handoff): {result.model}", "final answer generated"
    else:
        kind, text, by, reason = "abstain", host.abstain_message(result.detail), "host", f"handoff_{result.outcome}"
    return {"kind": kind, "text": text, "by": by, "reason": reason,
            "action_status": [dict(e) for e in result.ledger], "model_text": result.model_text}
