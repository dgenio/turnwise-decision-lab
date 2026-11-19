"""Controllers for the v0.7 study.

* ``GatedDecider`` / ``GroundedGenerator`` put the exit gate around any v0.6
  controller without changing it. The inner controller is still asked at every
  step it was asked before; the gate only acts when it proposes to end the turn.
* ``run_contract_turn`` is the contract planner: for a request the host can
  type, the contract already determines every next call, so no model is asked
  to choose. A request it cannot type goes to the tool-capable heavy agent,
  under the same gate, so an action request can still become an approval.
"""
from __future__ import annotations

import json
import time

from ..agent.context import assemble, select_heuristic
from ..agent.contracts import SCORE_RULE, Decision, Observation, Question
from ..agent.heavy_agent import run_heavy_agent
from ..agent.host import CATALOG_BY_ID, Host
from ..agent.loop import TurnState, TurnTrace, _obs_json
from .evidence import compile_contract, derive, missing, receipts, render_findings, revise, type_claim
from .gate import ACQUIRE, ALLOW, CLARIFY, HOLD, ExitGate

GATE_SCORE = "none: exit-gate rule (no model inference)"
PLAN_SCORE = "none: contract planner rule (no model inference)"


def _call_decision(cap_id: str, args: dict, provider: str, questions: list, rationale: str) -> Decision:
    cap = CATALOG_BY_ID[cap_id]
    return Decision("call_workflow" if cap.kind == "workflow" else "call_tool", cap_id, dict(args), provider=provider,
                    model="host rule", questions=questions, rationale=rationale)


class GatedDecider:
    """Wraps any DecisionProvider. One instance per user turn."""

    def __init__(self, inner, gate: ExitGate):
        self.inner, self.gate = inner, gate
        self.name = f"{inner.name}+exit-gate"
        self.model = getattr(inner, "model", "")
        self.interventions = 0
        self.events: list[dict] = []
        self.last_state = None
        self.acquiring: str | None = None  # the exit the gate is currently holding back

    def _gate_decision(self, cap, args, reason, extra_questions=()):
        q = Question("exit_gate", [ALLOW, ACQUIRE, HOLD, CLARIFY], "acquire" if not CATALOG_BY_ID[cap].side_effect else "hold",
                     None, GATE_SCORE, 0.0, None, note=reason)
        return _call_decision(cap, args, self.gate.name, list(extra_questions) + [q], reason)

    def decide(self, state, host) -> Decision:
        self.last_state = state
        if self.acquiring:
            # The gate is holding an exit back. It runs one required call at a time and re-reads the contract after each,
            # because what comes back can revise it (retry, widen, drop). No model is asked while this lasts.
            v = self.gate.review(message=state.user_message, conversation=state.conversation, observations=state.observations,
                                 terminal=self.acquiring, interventions=self.interventions - 1)
            if v.action == ACQUIRE:
                return self._gate_decision(*v.calls[0], f"{v.reason} (missing: {', '.join(v.missing)})")
            self.acquiring = None
        d = self.inner.decide(state, host)
        terminal = {"finish": "finish", "clarify": "clarify", "abstain": "abstain"}.get(d.operation)
        if d.operation == "call_model" and not d.requires_continuation:
            terminal = "answer"
        if d.operation in ("call_tool", "call_workflow") and d.target in CATALOG_BY_ID and CATALOG_BY_ID[d.target].side_effect:
            terminal = "write"
            reason = self.gate.veto(state.user_message, state.conversation, d.target, d.arguments)
            if reason:
                # The controller insists on a write the user declined or never made. The gate does not hand that back to it
                # (a deterministic controller would only repeat it): it ends the turn on what the contract supports.
                self.events.append({"step_index": len(state.observations), "terminal": "write", "action": "veto", "reason": reason,
                                    "proposed": {"operation": d.operation, "model_tier": None, "target": d.target, "arguments": dict(d.arguments)}})
                self.interventions += 1
                d = Decision("finish", provider=self.gate.name, model="host rule", rationale=reason,
                             questions=d.questions + [Question("exit_gate", [], "veto", None, GATE_SCORE, 0.0, None, note=reason)])
                terminal = "finish"
        if terminal is None:
            return d
        v = self.gate.review(message=state.user_message, conversation=state.conversation, observations=state.observations,
                             terminal=terminal, interventions=self.interventions)
        self.events.append({"step_index": len(state.observations), "terminal": terminal, **v.as_json(),
                            "proposed": {"operation": d.operation, "model_tier": d.model_tier, "target": d.target, "arguments": dict(d.arguments)}})
        if v.action == ALLOW:
            d.questions.append(Question("exit_gate", [ALLOW, ACQUIRE, HOLD, CLARIFY], ALLOW, None, GATE_SCORE, 0.0, None, note=v.reason))
            return d
        self.interventions += 1
        if v.action == CLARIFY:
            return Decision("clarify", provider=self.gate.name, model="host rule", rationale=v.reason,
                            questions=d.questions + [Question("exit_gate", [], CLARIFY, None, GATE_SCORE, 0.0, None, note=v.reason)])
        reason = f"{v.reason} (missing: {', '.join(v.missing)})" if v.missing else v.reason
        self.acquiring = terminal if v.action == ACQUIRE else None
        cap, args = v.calls[0]
        return self._gate_decision(cap, args, reason, d.questions)


class GroundedGenerator:
    """Wraps a generator: a final reply that fails the grounding check is replaced by the host's findings."""

    def __init__(self, inner, gate: ExitGate, decider: GatedDecider, host: Host):
        self.inner, self.gate, self.decider, self.host = inner, gate, decider, host

    def counter(self, tier):
        return getattr(self.inner, "counter", lambda t: None)(tier)

    def generate(self, prompt, tier, max_new_tokens):
        gen = self.inner.generate(prompt, tier, max_new_tokens)
        state = self.decider.last_state
        if gen.get("status") != "ok" or state is None:
            return gen
        if (gen.get("text") or "").strip().upper().startswith("NEED_MORE_EVIDENCE"):
            return gen  # the controller's own verification protocol: not a reply, so there is nothing to ground
        g = self.gate.ground(gen.get("text") or "", message=state.user_message, conversation=state.conversation,
                             observations=state.observations, host_facts=self.host.host_facts())
        gen["grounding"] = {k: g[k] for k in g if k != "replacement"}
        if "replacement" in g:
            self.decider.interventions += 1
            gen["withheld_text"] = gen["text"]
            gen["text"] = g["replacement"]
        return gen


# ------------------------------------------------------------ contract planner
NARRATE_SYSTEM = ("You are an incident assistant for on-call engineers. The host has already gathered the evidence and computed the "
                  "findings below. Answer the engineer's question in 2-3 sentences using only those findings. Do not add values, "
                  "ids or times that are not in the findings. Do not claim that any rollback, page or status post was performed.")


def _totals(trace: TurnTrace, state_obs: list[Observation], t0: float, host: Host, interventions: int, events: list[dict]) -> dict:
    decisions = [s for s in trace.steps if s.get("decision")]
    gens = [s["generation"] for s in trace.steps if s.get("generation")]
    return {
        "decision_calls": len(decisions), "decision_questions": sum(len(s["decision"]["questions"]) for s in decisions),
        "decision_latency_ms": round(sum((s["decision"]["latency_ms"] or 0) for s in decisions), 1),
        "decision_input_tokens": sum((s["decision"]["input_tokens"] or 0) for s in decisions),
        "tool_calls": sum(1 for o in state_obs if o.operation in ("call_tool", "call_workflow") and o.status in ("ok", "error")),
        "rejected_decisions": sum(1 for o in state_obs if o.status == "rejected"), "verification_requests": 0, "escalations": 0,
        "generation_calls": {t: sum(1 for g in gens if g.get("tier") == t and g.get("status") == "ok") for t in ("light", "heavy")},
        "generation_prompt_tokens": sum(g.get("prompt_tokens") or 0 for g in gens),
        "generation_completion_tokens": sum(g.get("completion_tokens") or 0 for g in gens),
        "generation_latency_ms": round(sum((g.get("prefill_ms") or 0) + (g.get("decode_ms") or 0) for g in gens), 1),
        "wall_ms": round((time.perf_counter() - t0) * 1000, 1), "writes_executed": len(host.world.write_ledger),
        "gate_interventions": interventions, "gate_events": events,
    }


def record_text(host: Host, fields: list[str]) -> str:
    facts = host.host_facts()
    return "Verified incident record (no model used): " + "; ".join(f"{f.replace('_', ' ')} {facts[f]}" for f in fields if f in facts) + "."


def clarify_text(reason: str) -> str:
    if "text to post" in reason:
        return f"I need one detail before I can request this: what exactly should the status update say? [{reason}]"
    return ("I need one detail before I can do this safely: which service do you mean (checkout, payments, search or auth)? "
            f"[{reason}]")


def run_contract_turn(message: str, *, host: Host, generator, heavy_lm, turn_id: str, conversation: list[dict] | None = None,
                      gate: ExitGate | None = None, narrate: bool = False, arm: str = "contract", fallback=None) -> dict:
    """One turn under the contract planner. Returns a JSON trace in the v0.6 shape plus a ``plan`` field.

    ``fallback(message, host=, turn_id=, conversation=, gate=, arm=) -> trace dict`` handles untyped requests. The
    default is the local heavy agent; ``v07.hosted.run_hosted_agent`` (with ``chat=`` bound) has the same shape.
    """
    gate = gate or ExitGate()
    conversation = list(conversation or [])
    t0 = time.perf_counter()
    claim = type_claim(message, conversation)
    plan = {"claim": claim.as_json(), "contract": compile_contract(claim, message).as_json(),
            "typing_ms": round((time.perf_counter() - t0) * 1000, 3)}
    if claim.type == "untyped":
        plan["route"] = "delegate: the host could not type this request; tool-capable heavy agent under the exit gate"
        if fallback is not None:
            tr = fallback(message, host=host, turn_id=turn_id, conversation=conversation, gate=gate, arm=arm)
        else:
            tr = run_heavy_agent(message, host=host, lm=heavy_lm, turn_id=turn_id, conversation=conversation, gate=gate, arm=arm).as_json()
        tr["plan"] = plan
        return tr
    plan["route"] = "planned: the contract determines every call; no model chooses"
    trace = TurnTrace(turn_id, message, arm, host.world.variant)
    state = TurnState(turn_id, message, conversation)
    events: list[dict] = []

    def step_for(d: Decision, v) -> dict:
        s = {"step_index": len(trace.steps), "decision_call_id": f"{turn_id}/p{len(trace.steps) + 1}",
             "snapshot": state.compact_snapshot(), "decision": d.as_json(), "validation": {"status": v.status, "reason": v.reason}}
        trace.steps.append(s)
        return s

    def finish(kind, text, by, reason, step=None):
        if step is not None:
            step["terminate_reason"] = reason
        trace.final = {"kind": kind, "text": text, "by": by, "reason": reason}

    calls_made = 0
    while True:
        t1 = time.perf_counter()
        k = revise(compile_contract(claim, message), state.observations)
        todo, unavailable = missing(k, state.observations, message, gate.max_retries)
        if todo and calls_made >= host.limits.max_steps:  # same bound as every other arm: at most max_steps tool calls
            unavailable, todo = unavailable + todo, []
            plan["step_limit"] = "tool-call budget spent before the contract was met; the reply says what is missing"
        ms = lambda: round((time.perf_counter() - t1) * 1000, 3)
        if k.clarify:
            d = Decision("clarify", provider="contract-planner", model="host rules v0.7", rationale=k.clarify,
                         questions=[Question("plan", [], "clarify", None, PLAN_SCORE, ms(), None, note=k.clarify)])
            finish("clarify", clarify_text(k.clarify), "host (contract planner)", "contract: the request has no resolvable target",
                   step_for(d, host.validate(d, state.observations)))
            break
        if todo:
            r = todo[0]
            cap, args = r.call(message, receipts(state.observations))
            d = _call_decision(cap, args, "contract-planner", [Question("plan", [x.key for x in todo], r.key, None, PLAN_SCORE, ms(), None, note=r.why)], r.why)
            v = host.validate(d, state.observations)
            s = step_for(d, v)
            calls_made += 1
            if not v.ok:
                obs = Observation(s["step_index"], s["decision_call_id"], d.operation, d.target, dict(d.arguments), "rejected", reason=v.reason)
            else:
                obs = host.execute(d, step_index=s["step_index"], call_id=s["decision_call_id"], user_text=message)
            state.observations.append(obs)
            s["observation"] = _obs_json(obs)
            s["continue_reason"] = "contract not yet met; next requirement" if obs.status == "ok" else f"tool returned {obs.status}; retry within budget"
            continue
        findings = render_findings(claim, derive(state.observations, claim), unavailable) if state.observations else ""
        if k.hold and not any(o.status == "approval_required" for o in state.observations):
            cap, args = k.hold
            d = _call_decision(cap, args, "contract-planner", [Question("plan", [], f"hold:{cap}", None, PLAN_SCORE, ms(), None,
                                                                         note="the user asked for a side effect")], "action intent")
            v = host.validate(d, state.observations)
            s = step_for(d, v)
            obs = Observation(s["step_index"], s["decision_call_id"], d.operation, cap, dict(args),
                              "approval_required" if v.status == "approval_required" else "rejected", reason=v.reason)
            state.observations.append(obs)
            s["observation"] = _obs_json(obs)
            if obs.status == "approval_required":
                finish("approval_required", host.approval_message(obs) + (f"\n{findings}" if findings else ""), "host (contract planner)",
                       "side effect needs human approval", s)
            else:
                finish("abstain", host.abstain_message(v.reason), "host", "approval request rejected by host validation", s)
            break
        if claim.type == "record":
            d = Decision("finish", provider="contract-planner", model="host rules v0.7", rationale="host-verified incident record",
                         questions=[Question("plan", [], "finish", None, PLAN_SCORE, ms(), None, note="answerable from the incident record")])
            finish("verified", record_text(host, claim.record_fields), "host (deterministic)", "contract: incident record answers the request",
                   step_for(d, type("V", (), {"status": "accepted", "reason": "no tool needed"})()))
            break
        if claim.type == "smalltalk" or (narrate and claim.type in ("causal", "verification")):
            tier = "light" if claim.type == "smalltalk" else "heavy"
            d = Decision("call_model", model_tier=tier, provider="contract-planner", model="host rules v0.7",
                         questions=[Question("plan", [], f"{tier}_model", None, PLAN_SCORE, ms(), None,
                                             note="small talk" if tier == "light" else "contract met; the model narrates the host's findings")])
            s = step_for(d, host.validate(d, state.observations))
            counter = getattr(generator, "counter", lambda t: None)(tier)
            if tier == "light":
                prompt = assemble(state, tier, select_heuristic(state, tier, host.permitted_blocks), host.permitted_blocks, "heuristic", count_tokens=counter)
            else:
                user = f"{findings}\n\nQuestion: {message}"
                n = (counter or (lambda t: max(1, len(t) // 4)))(NARRATE_SYSTEM + user)
                prompt = type("P", (), {"messages": [{"role": "system", "content": NARRATE_SYSTEM}, {"role": "user", "content": user}],
                                        "tokens": n, "as_json": lambda self: {"tier": tier, "policy": "contract findings", "messages": self.messages,
                                                                              "included": [{"id": "host_findings", "tokens": n, "trust": "host", "source": "contract planner", "mandatory": True}],
                                                                              "excluded": [], "tokens": n, "token_counter": "model tokenizer" if counter else "approximate (chars/4)", "redactions": 0}})()
            gen = generator.generate(prompt, tier, host.limits.max_generation_tokens[tier])
            s["context"] = {"decision": {"proposed": [], "policy": "contract planner", "questions": [], "provider": "contract-planner", "model": "rule"},
                            "assembled": prompt.as_json()}
            s["generation"] = gen
            text = gen.get("text", "")
            g = gate.ground(text, message=message, conversation=conversation, observations=state.observations, host_facts=host.host_facts())
            gen["grounding"] = {x: g[x] for x in g if x != "replacement"}
            events.append({"step_index": s["step_index"], "terminal": "answer", "action": ALLOW if g["ok"] else "withhold", "grounding": gen["grounding"]})
            if "replacement" in g:
                gen["withheld_text"] = text
                finish("verified", g["replacement"], "host (exit gate: generated reply withheld)", "grounding check failed", s)
            else:
                finish("answer", text, f"{tier} model: {gen.get('model', '')}", "final answer generated", s)
            break
        d = Decision("finish", provider="contract-planner", model="host rules v0.7", rationale="contract met",
                     questions=[Question("plan", [], "finish", None, PLAN_SCORE, ms(), None, note="contract met; host findings answer the request")])
        v = host.validate(d, state.observations)
        s = step_for(d, v)
        if not v.ok:
            finish("abstain", host.abstain_message("no evidence could be retrieved"), "host", v.reason, s)
        else:
            finish("verified", findings, "host (deterministic findings)", "contract met; findings computed by the host", s)
        break
    trace.observations = [_obs_json(o) for o in state.observations]
    withheld = sum(1 for e in events if e.get("action") == "withhold")
    trace.totals = _totals(trace, state.observations, t0, host, withheld, events)
    out = trace.as_json()
    out["plan"] = plan
    return out


def run_gated_loop(message: str, *, host: Host, decider, context, generator, turn_id: str, arm: str, conversation=None,
                   gate: ExitGate | None = None, verification: bool = False) -> dict:
    """The unchanged v0.6 loop with the exit gate around its controller and generator."""
    from ..agent.host import Validation
    from ..agent.loop import execute_user_turn
    gate = gate or ExitGate()
    gd = GatedDecider(decider, gate)
    conversation = list(conversation or [])
    validate = host.validate

    def validate_with_veto(d, executed):
        reason = gate.veto(message, conversation, d.target, d.arguments) if d.operation in ("call_tool", "call_workflow") else None
        return Validation(False, d, "rejected", reason) if reason else validate(d, executed)
    host.validate = validate_with_veto
    try:
        tr = execute_user_turn(message, host=host, decider=gd, context=context, generator=GroundedGenerator(generator, gate, gd, host),
                               turn_id=turn_id, arm=arm, conversation=conversation, verification=verification).as_json()
    finally:
        host.validate = validate
    if tr["final"].get("kind") in ("step_limit", "abstain"):  # a forced exit: only the latch can still act
        obs = [Observation(o["step_index"], o["call_id"], o["operation"], o["target"], o["arguments"], o["status"], o.get("facts") or {},
                           o.get("text", ""), o.get("reason", "")) for o in tr["observations"]]
        v = gate.review(message=message, conversation=conversation, observations=obs, terminal="abstain", interventions=gd.interventions)
        gd.events.append({"step_index": len(tr["steps"]), "terminal": "abstain", **v.as_json()})
        if v.action == HOLD:
            cap, args = v.calls[0]
            d = _call_decision(cap, args, gate.name, [Question("exit_gate", [], HOLD, None, GATE_SCORE, 0.0, None, note=v.reason)], v.reason)
            val = host.validate(d, obs)
            if val.status == "approval_required":
                gd.interventions += 1
                o = Observation(len(tr["steps"]), f"{turn_id}/gate", d.operation, cap, dict(args), "approval_required", reason=val.reason)
                tr["steps"].append({"step_index": len(tr["steps"]), "decision_call_id": f"{turn_id}/gate", "decision": d.as_json(),
                                    "validation": {"status": val.status, "reason": val.reason}, "observation": _obs_json(o),
                                    "terminate_reason": "exit gate: the user asked for a side effect; approval request raised at a forced exit"})
                tr["observations"].append(_obs_json(o))
                tr["final"] = {"kind": "approval_required", "text": host.approval_message(o), "by": "host (exit gate: action latch)",
                               "reason": "the user asked for a side effect; the gate raised the approval request"}
        elif v.action == CLARIFY:
            gd.interventions += 1
            tr["final"] = {"kind": "clarify", "text": clarify_text(v.reason), "by": "host (exit gate)", "reason": v.reason}
    tr["totals"]["gate_interventions"] = gd.interventions
    tr["totals"]["gate_events"] = gd.events
    if tr["final"].get("kind") == "answer":
        last = next((s["generation"] for s in reversed(tr["steps"]) if s.get("generation")), None)
        if last and "withheld_text" in last:
            tr["final"].update(kind="verified", by="host (exit gate: generated reply withheld)", withheld_text=last["withheld_text"])
    return tr
