"""Capability-preserving escalation (#12): continue an unresolved turn with the tool-capable heavy agent.

v0.6's conservative gate replaced an uncertain decision with a *text-only* heavy generation call. That
generator could not call tools or raise an approval request, so on held-out H18/H19 both requested actions
were silently dropped (``reports/v06/audit.md`` section 2). This module is the opt-in replacement: a bounded
continuation by the same native tool-calling heavy agent that serves as the heavy-only baseline (same system
prompt and tool schemas, parser, host validation, fact rendering and per-round token limit), resumed from the
turn's host state.

Host-side invariants (no model output, controller hint or tool result can change them):

I1 Capability: every catalog tool and the approval hold stay available; never text-only. With no heavy agent
   configured, or no budget left, the turn abstains instead.
I2 Contract: the host builds it: the exact request, conversation, principal permissions (which also decide
   whether the incident record is shown), prior receipts, the user's actions as resolved by the host
   (``intent.py``), the remaining budget. Controller hints are re-checked; bad ones are recorded and ignored.
I3 Authority: writes are never executed. A write proposal becomes an approval hold only when it matches an
   action the host resolved as *requested* from the user's own words (capability, target and, for a literal
   status-post body, the exact text). Everything else is rejected and kept in the audit trail only; a
   rejected proposal never becomes a user intent and never prompts the user.
I4 No silent drop: a requested or unverified user action ends held for approval, in a host clarification that
   names it, or listed as not attempted in an abstention. Never as an ordinary answer.
I5 Bounds: model rounds share the turn's step budget; proposed tool calls are capped; an optional cap on newly
   computed tokens is enforced *before* each computation with the model's own tokenizer (refused when the model
   cannot count); calls that already succeeded are rejected, not repeated; a model error abstains.
I6 Status: final action statuses come from the host ledger. When an action is involved the final text is
   written by the host; the model's prose is kept separately for audit.

Not covered: indirect requests the resolver cannot verify (they end as rejected proposals or confirmations,
a recall limit for #9), and claims in prose where no write was proposed (#13).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json

from .contracts import ActionIntent, Decision, Handoff, Observation, Question
from .heavy_agent import _PREFIX_CACHE, CALL_RE, parse_call, system_block
from .host import CATALOG_BY_ID, Host, Validation
from .intent import _earlier_target, normalise_message, resolve_user_actions
from .loop import _obs_json
from .providers import named_services
from .render import render_facts

CONTRACT_VERSION = "turnwise.handoff/0.2"
OPEN = ("requested", "unverified")


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
    incident_record_visible: bool
    tools: tuple[str, ...]
    approval_hold: bool
    writes_executable: bool
    receipts: tuple[dict, ...]
    user_actions: tuple[dict, ...]  # host-resolved from user wording; the only basis for an approval hold
    controller_intents: tuple[ActionIntent, ...]  # unverified suspicions: can only ever lead to a question
    ignored_hints: tuple[dict, ...]
    controller: dict
    remaining_rounds: int
    max_tool_calls: int
    max_computed_tokens: int | None

    def as_json(self) -> dict:
        return json.loads(json.dumps(asdict(self)))


def build_contract(decision: Decision, state, host: Host, remaining_rounds: int) -> HandoffContract:
    hint = decision.handoff if isinstance(decision.handoff, Handoff) else None
    actions = resolve_user_actions(state.user_message, state.conversation)
    resolved = {a["capability"] for a in actions}
    observed = any(o.status in ("ok", "error") for o in state.observations)
    suspected, ignored = [], []
    if decision.handoff is not None and hint is None:
        ignored.append({"hint": repr(decision.handoff)[:300], "reason": "not a typed Handoff"})
    for intent in (hint.pending_intents if hint else []):
        cap = CATALOG_BY_ID.get(getattr(intent, "capability", "") or "")
        why = ("not a registered side-effecting capability" if cap is None or not cap.side_effect else
               "the user's wording already resolves this action" if cap.id in resolved else
               "formed after tool output, not from the user's words alone" if observed else None)
        if why:
            ignored.append({"hint": asdict(intent) if isinstance(intent, ActionIntent) else repr(intent), "reason": why})
            continue
        # Formed from the user's words alone. The host re-derives the target (never taken from the hint).
        args = {}
        if "service" in cap.params:
            named = named_services(state.user_message) or _earlier_target(state.conversation)
            args = {"service": named[0]} if len(named) == 1 else {}
        suspected.append(ActionIntent(cap.id, args, "controller_candidate"))
    return HandoffContract(
        CONTRACT_VERSION, hint.reason if hint else "unspecified", state.user_message,
        tuple(dict(m) for m in state.conversation), host.identity.principal, tuple(sorted(host.identity.permissions)),
        "incident_record" in host.permitted_blocks, tuple(c.id for c in host.allowed_capabilities()), True, False,
        tuple(_obs_json(o) for o in state.observations), tuple(actions), tuple(suspected), tuple(ignored),
        {"choice": hint.controller_choice if hint else None, "score": hint.controller_score if hint else None,
         "gate": hint.gate if hint else None, "provider": decision.provider},
        max(0, remaining_rounds), host.limits.max_handoff_tool_calls, host.limits.max_handoff_computed_tokens)


def handoff_note(contract: HandoffContract) -> str:
    """Host-written context for the heavy agent. Empty when there is nothing to carry (the prompt then equals the baseline's)."""
    parts, lines = [], []
    for r in contract.receipts:
        if r["status"] == "ok":
            lines.append(render_facts(r["facts"]))
        elif r["status"] == "error":
            lines.append(json.dumps({"tool": r["target"], "error": r["status"], "reason": r["reason"]}))
    if lines:
        parts.append("Tool results already gathered in this turn (do not repeat these calls):\n<tool_response>\n"
                     + "\n".join(lines) + "\n</tool_response>")
    asked = [describe(a["capability"], a["arguments"]) for a in contract.user_actions if a["status"] == "requested"]
    unsure = [describe(a["capability"], a["arguments"]) for a in contract.user_actions if a["status"] == "unverified"]
    unsure += [describe(i.capability, i.arguments) for i in contract.controller_intents]
    if asked:
        parts.append("The user asked for: " + "; ".join(asked) + ". Call the tool for it; it only creates an approval "
                     "request for a human. Never say it was done.")
    if unsure:
        parts.append("Not confirmed by the user: " + "; ".join(unsure) + ". Do not request it; the host will ask the user.")
    if asked or unsure:
        parts.append("Any other side-effecting call is rejected.")
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
    prefix_fill_tokens: int = 0
    cached_prompt_tokens: int = 0

    def summary(self) -> dict:
        return {"outcome": self.outcome, "detail": self.detail, "model": self.model, "rounds": self.rounds,
                "tool_calls": self.tool_calls, "computed_tokens": self.computed_tokens,
                "prefix_fill_tokens": self.prefix_fill_tokens, "cached_prompt_tokens": self.cached_prompt_tokens}


def _initial_ledger(contract: HandoffContract) -> list[dict]:
    ledger = [{"capability": a["capability"], "arguments": dict(a["arguments"]), "source": "user_request",
               "status": a["status"], "notes": [f"host resolver: {a['reason']} ({a['evidence']!r})"]}
              for a in contract.user_actions]
    ledger += [{"capability": i.capability, "arguments": dict(i.arguments), "source": i.source, "status": "unverified",
                "notes": ["the controller's own choice before the uncertainty gate, from the user's words alone"]}
               for i in contract.controller_intents]
    return ledger


def _match_request(ledger: list[dict], cap_id: str, args: dict) -> dict | None:
    for e in ledger:
        if e["source"] != "user_request" or e["status"] != "requested" or e["capability"] != cap_id:
            continue
        if "service" in e["arguments"] and args.get("service") != e["arguments"]["service"]:
            continue
        if "message" in e["arguments"] and normalise_message(args.get("message", "")) != normalise_message(e["arguments"]["message"]):
            continue
        return e
    return None


def _reject_write(ledger: list[dict], cap_id: str, args: dict, reason: str, call_id: str) -> None:
    """Audit only: a rejected proposal is never turned into a user intent and never prompts the user."""
    safe = {str(k)[:40]: str(v)[:300] for k, v in args.items()}
    for e in ledger:
        if e["source"] == "heavy_agent_proposal" and e["status"] == "rejected" and e["capability"] == cap_id and e["arguments"] == safe:
            e["notes"].append(f"{call_id}: {reason}")
            return
    ledger.append({"capability": cap_id, "arguments": safe, "source": "heavy_agent_proposal", "status": "rejected",
                   "notes": [f"{call_id}: {reason}"]})


def run_handoff(contract: HandoffContract, *, host: Host, lm, observations: list[Observation], turn_id: str,
                first_step_index: int) -> HandoffResult:
    """Bounded native tool-calling continuation. Appends every host observation to ``observations`` (the turn's state)."""
    res = HandoffResult("round_budget", f"handoff round budget of {contract.remaining_rounds} reached", _initial_ledger(contract))
    if lm is None:
        res.outcome, res.detail = "not_run", "no tool-capable heavy agent is configured; a text-only fallback is not allowed"
        return res
    res.model = getattr(lm, "version", "")
    if contract.remaining_rounds < 1:
        res.outcome, res.detail = "not_run", "no step budget left for the handoff"
        return res
    cap_tokens = contract.max_computed_tokens
    count = getattr(lm, "count_tokens", None)
    if cap_tokens is not None and not callable(count):
        res.outcome, res.detail = "not_run", "a computed-token cap is set but the model cannot count tokens; not run unmetered"
        return res
    try:
        sysb = system_block(host, lm.arch, include_incident_record=contract.incident_record_visible)
        key = (lm.version, sysb)
        if key not in _PREFIX_CACHE:
            if cap_tokens is not None and count(sysb) > cap_tokens:
                res.outcome, res.detail = "token_budget", f"the system prefix alone exceeds the {cap_tokens}-token cap"
                return res
            _, st0, n0 = lm.extend(sysb)
            _PREFIX_CACHE[key] = (st0, n0)
            res.prefix_fill_tokens = n0
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
    for r in range(contract.remaining_rounds):
        max_new = host.limits.max_generation_tokens["heavy"]
        if cap_tokens is not None:  # prospective: never start a computation that could cross the cap
            room = cap_tokens - res.prefix_fill_tokens - res.computed_tokens - count(pending)
            if room < 1:
                res.outcome, res.detail = "token_budget", f"the next round could exceed the {cap_tokens}-token cap"
                break
            max_new = min(max_new, room)
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
        if cap_tokens is not None and res.prefix_fill_tokens + res.computed_tokens > cap_tokens:
            res.outcome, res.detail = "token_budget", "the model reported more tokens than were counted; cap exceeded, stopped"
            step["terminate_reason"] = res.detail
            break
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
            match = None
            if v.ok and v.status == "approval_required":
                match = _match_request(res.ledger, cap.id, d.arguments)
                if any(e["status"] == "held_for_approval" and e["capability"] == cap.id and e["arguments"] == d.arguments
                       for e in res.ledger):
                    v = Validation(False, d, "rejected", "approval for this action was already requested in this turn")
                elif match is None:
                    v = Validation(False, d, "rejected", "the user did not verifiably ask for this action; no approval "
                                   "request was created. Ask the user if you think it is needed.")
            if not v.ok:
                obs = Observation(step_index, call_id, op, name, d.arguments, "rejected", reason=v.reason)
                content = json.dumps({"error": v.reason})
                if cap is not None and cap.side_effect:
                    _reject_write(res.ledger, cap.id, d.arguments, v.reason, call_id)
            elif v.status == "approval_required":
                obs = Observation(step_index, call_id, op, name, d.arguments, "approval_required", reason=v.reason)
                content = json.dumps({"status": "approval_requested", "executed": False, "note": "a human must approve this action"})
                match.update(arguments=dict(d.arguments), status="held_for_approval")
                match["notes"].append(f"{call_id}: proposed by the heavy agent; held for approval")
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
    """Host-owned final envelope. Action statuses come from the host ledger, never from model prose."""
    held = [e for e in result.ledger if e["status"] == "held_for_approval"]
    open_ = [e for e in result.ledger if e["status"] in OPEN]
    rejected = any(e["status"] == "rejected" for e in result.ledger)
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
        kind, by, reason = "clarify", "host", "a user action was not resolved by the heavy agent"
        text = host.confirm_actions_message([describe(e["capability"], e["arguments"]) for e in open_])
    elif open_:
        for e in open_:
            e["status"] = "not_attempted"
        kind, by, reason = "abstain", "host", f"handoff_{result.outcome}"
        text = (host.abstain_message(result.detail) + " Not attempted: "
                + "; ".join(describe(e["capability"], e["arguments"]) for e in open_) + ".")
    elif result.outcome == "answer":
        kind, text, by, reason = "answer", result.model_text, f"heavy agent (handoff): {result.model}", "final answer generated"
        if rejected:  # the model tried a write nobody asked for: its prose must not read as an action receipt
            text += "\n\n[host] No action was requested or executed in this turn."
    else:
        kind, text, by, reason = "abstain", host.abstain_message(result.detail), "host", f"handoff_{result.outcome}"
    return {"kind": kind, "text": text, "by": by, "reason": reason,
            "action_status": [dict(e) for e in result.ledger], "model_text": result.model_text}
