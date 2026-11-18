"""One user turn = a bounded sequence of decide -> validate -> execute -> observe steps."""
from __future__ import annotations

from dataclasses import dataclass, field
from copy import deepcopy
from typing import Any, Protocol
import json
import time

from .context import assemble
from .contracts import ContextDecision, Decision, Observation
from .host import Host


@dataclass
class TurnState:
    turn_id: str
    user_message: str
    conversation: list[dict] = field(default_factory=list)  # prior turns: {"role", "content"}
    observations: list[Observation] = field(default_factory=list)
    current_tier: str | None = None
    verification: bool = False
    # Host-derived user write intents for this turn (requested / needs_clarification / declined_by_user
    # plus lifecycle statuses). Never filled from model output, tool output or controller hints.
    action_intents: list[dict] = field(default_factory=list)

    @property
    def open_action_intents(self) -> list[dict]:
        return [a for a in self.action_intents if a["status"] in ("requested", "needs_clarification")]

    @property
    def latest_observation(self) -> Observation | None:
        return self.observations[-1] if self.observations else None

    def compact_snapshot(self, limit: int = 6) -> dict:
        """The bounded state the decision model sees (never raw prompts or full history)."""
        prior = [m["content"][:160] for m in self.conversation if m["role"] == "user"][-2:]
        return {"user_request": self.user_message,
                "earlier_user_messages": prior,
                "observations": [o.summary() for o in self.observations[-limit:]],
                "steps_taken": len(self.observations)}


class DecisionProvider(Protocol):
    name: str
    def decide(self, state: TurnState, host: Host) -> Decision: ...


class ContextSelector(Protocol):
    name: str
    def select(self, state: TurnState, tier: str, permitted: frozenset[str]) -> ContextDecision: ...


class Generator(Protocol):
    def generate(self, prompt, tier: str, max_new_tokens: int) -> dict: ...


@dataclass
class TurnTrace:
    user_turn_id: str
    user_message: str
    arm: str
    world_variant: str
    steps: list[dict] = field(default_factory=list)
    final: dict = field(default_factory=dict)
    observations: list[dict] = field(default_factory=list)
    totals: dict = field(default_factory=dict)

    def as_json(self) -> dict:
        return {"user_turn_id": self.user_turn_id, "user_message": self.user_message, "arm": self.arm,
                "world_variant": self.world_variant, "steps": self.steps, "final": self.final,
                "observations": self.observations, "totals": self.totals}


def _obs_json(o: Observation) -> dict:
    return {"step_index": o.step_index, "call_id": o.call_id, "operation": o.operation, "target": o.target,
            "arguments": o.arguments, "status": o.status, "facts": o.facts, "text": o.text, "reason": o.reason}


def execute_user_turn(message: str, *, host: Host, decider: DecisionProvider, context: ContextSelector,
                      generator: Generator, turn_id: str, arm: str = "", conversation: list[dict] | None = None,
                      count_tokens=None, verification: bool = False, max_verification_requests: int = 1,
                      heavy_fallback=None) -> TurnTrace:
    state = TurnState(turn_id, message, list(conversation or []), verification=verification)
    # The host reads the user's own words once per turn; every write proposal is checked against it.
    state.action_intents = deepcopy(host.action_intents(message, state.conversation)["intents"])
    denied_writes: list[dict] = []
    verification_requests = 0
    trace = TurnTrace(turn_id, message, arm, host.world.variant)
    rejections = 0
    handoff_active = False
    handoff_record = None
    t_turn = time.perf_counter()

    def finish(kind: str, text: str, by: str, step: dict | None, reason: str):
        if step is not None:
            step["terminate_reason"] = reason
        trace.final = {"kind": kind, "text": text, "by": by, "reason": reason}

    for step_index in range(host.limits.max_steps):
        call_id = f"{turn_id}/{'h' if handoff_active else 'd'}{step_index + 1}"
        snapshot = state.compact_snapshot()
        native_generation = None
        try:
            if handoff_active:
                earlier = [s["generation"] for s in trace.steps if s.get("generation")
                           and s["generation"].get("status") != "not_run"]
                if any(type(g.get(k)) is not int or g[k] < 0 for g in earlier
                       for k in ("prompt_tokens", "completion_tokens")):
                    finish("abstain", host.abstain_message("unknown earlier generation usage"), "host", None,
                           "unknown_generation_usage")
                    break
                decision, native_generation = heavy_fallback.propose(
                    state, host,
                    input_remaining=heavy_fallback.limits.max_input_tokens - sum(g["prompt_tokens"] for g in earlier),
                    output_remaining=heavy_fallback.limits.max_output_tokens - sum(g["completion_tokens"] for g in earlier))
            else:
                decision = decider.decide(state, host)
        except Exception as exc:  # provider failure: never guess an action
            trace.steps.append({"step_index": step_index, "decision_call_id": call_id, "snapshot": snapshot,
                                "decision": None, "validation": {"status": "rejected", "reason": f"decision provider error: {type(exc).__name__}"}})
            finish("abstain", host.abstain_message("decision provider unavailable"), "host", trace.steps[-1], "provider_error")
            break
        v = host.validate(decision, state.observations,
                          user_message=state.user_message, conversation=state.conversation)
        step = {"step_index": step_index, "decision_call_id": call_id, "snapshot": snapshot,
                "decision": decision.as_json(), "validation": {"status": v.status, "reason": v.reason}}
        if v.evidence is not None:
            step["validation"]["evidence"] = v.evidence
        if v.intent is not None:
            step["validation"]["intent"] = v.intent
        if handoff_active:
            step["decision_source"] = "native_heavy_fallback"
            step["generation"] = native_generation
        trace.steps.append(step)

        if not v.ok:
            rejections += 1
            if v.intent is not None:  # audit only: a denied proposal never becomes a user intent or an approval
                denied_writes.append({"capability": decision.target, "arguments": dict(decision.arguments),
                                      "code": v.intent["code"], "reason": v.intent["reason"],
                                      "proposed_by": decision.provider or "unknown", "call_id": call_id})
            obs = Observation(step_index, call_id, decision.operation, decision.target, dict(decision.arguments),
                              "rejected", reason=v.reason)
            state.observations.append(obs)
            step["observation"] = _obs_json(obs)
            if rejections > host.limits.max_rejections:
                finish("abstain", host.abstain_message("repeated invalid decisions"), "host", step, "rejection_limit")
                break
            step["continue_reason"] = "decision rejected by host; the rejection is shown to the next decision"
            continue

        op = decision.operation
        if op == "handoff_heavy":
            if handoff_active or heavy_fallback is None:
                # Never degrade to a text-only call: without a tool-capable agent the turn abstains.
                finish("abstain", host.abstain_message("tool-capable heavy backend not configured"), "host", step,
                       "handoff_unavailable")
                break
            earlier_gens = [s["generation"] for s in trace.steps if s.get("generation")]
            remaining_tokens = {}
            for key, allowance in (("prompt_tokens", heavy_fallback.limits.max_input_tokens),
                                   ("completion_tokens", heavy_fallback.limits.max_output_tokens)):
                remaining_tokens[key] = (max(0, allowance - sum(g[key] for g in earlier_gens))
                                         if all(type(g.get(key)) is int and g[key] >= 0 for g in earlier_gens) else None)
            handoff_record = {
                "schema": "local-heavy-handoff-v1", "reason": decision.rationale,
                "original_user_request": message, "principal": host.identity.principal,
                "permissions": sorted(host.identity.permissions), "permitted_blocks": sorted(host.permitted_blocks),
                "prior_observation_ids": [o.call_id for o in state.observations],
                "action_intents": deepcopy(state.action_intents),
                "remaining_steps": host.limits.max_steps - step_index - 1,
                "max_generation_input_tokens": heavy_fallback.limits.max_input_tokens,
                "max_generation_output_tokens": heavy_fallback.limits.max_output_tokens,
                "remaining_generation_input_tokens": remaining_tokens["prompt_tokens"],
                "remaining_generation_output_tokens": remaining_tokens["completion_tokens"],
                "remaining_rejections": max(0, host.limits.max_rejections - rejections),
                "tool_capable": True, "writes_executable": False, "provider_cost_usd": None,
            }
            step["handoff"] = handoff_record
            if any(a["status"] == "needs_clarification" for a in state.action_intents):
                # The host cannot verify what was asked (unresolved target, condition, ambiguous form): ask, do not guess.
                finish("clarify", host.clarify_message(), "host", step, "action request unresolved by host")
                break
            handoff_active = True
            state.current_tier = "heavy"
            step["continue_reason"] = "same host and state; native heavy proposes the next operation within the remaining limits"
            continue
        if op in ("call_tool", "call_workflow"):
            if v.status == "approval_required":
                obs = Observation(step_index, call_id, op, decision.target, dict(decision.arguments), "approval_required",
                                  reason=v.reason)
                state.observations.append(obs)
                step["observation"] = _obs_json(obs)
                index = (v.intent or {}).get("intent_index")
                if index is not None and index < len(state.action_intents):
                    state.action_intents[index].update(status="held_for_approval", call_id=call_id,
                                                       held_arguments=dict(obs.arguments),
                                                       **({"message_source": v.intent["message_source"]}
                                                          if "message_source" in v.intent else {}))
                finish("approval_required", host.approval_message(obs), "host", step, "side effect needs human approval")
                break
            obs = host.execute(decision, step_index=step_index, call_id=call_id, user_text=message)
            state.observations.append(obs)
            step["observation"] = _obs_json(obs)
            step["continue_reason"] = ("tool result added to state; deciding again" if obs.status == "ok"
                                       else f"tool returned {obs.status}; deciding again (retry or alternative)")
            continue

        if op == "call_model":
            tier = decision.model_tier
            state.current_tier = tier
            ctx = context.select(state, tier, host.permitted_blocks)
            counter = count_tokens or getattr(generator, "counter", lambda t: None)(tier)
            prompt = assemble(state, tier, ctx.proposed, host.permitted_blocks, ctx.policy, count_tokens=counter)
            gen = generator.generate(prompt, tier, host.limits.max_generation_tokens[tier])
            step["context"] = {"decision": ctx.as_json(), "assembled": prompt.as_json()}
            step["generation"] = gen
            if gen.get("status") == "pending":
                finish("generation_pending", gen.get("text", ""), f"{tier} model (not executed)", step,
                       "no generation backend configured; prompt recorded")
                break
            text = (gen.get("text") or "").strip()
            if verification and text.upper().startswith("NEED_MORE_EVIDENCE") and verification_requests < max_verification_requests:
                verification_requests += 1
                obs = Observation(step_index, call_id, op, f"{tier}_model", {}, "needs_evidence", text=text[:300])
                state.observations.append(obs)
                step["observation"] = _obs_json(obs)
                step["continue_reason"] = "generating model reported missing evidence; the decision layer runs again"
                continue
            if decision.requires_continuation:
                obs = Observation(step_index, call_id, op, f"{tier}_model", {}, "generated", text=gen.get("text", ""))
                state.observations.append(obs)
                step["observation"] = _obs_json(obs)
                step["continue_reason"] = "intermediate model output added to state; deciding again"
                continue
            claims = host.review_generated_answer(gen.get("text", ""))["unsupported_action_claims"]
            if claims:  # the host has no receipt for any executed write, so the reply cannot say one happened
                finish("abstain", host.withheld_message(claims), "host", step, "unsupported_action_claim")
                trace.final.update(model_text=gen.get("text", ""), unsupported_action_claims=claims)
                break
            finish("answer", gen.get("text", ""), f"{tier} model: {gen.get('model', '')}", step, "final answer generated")
            break

        if op == "finish":
            rendered = host.render_verified(state.observations, evidence=v.evidence)
            if handoff_active:
                rendered = rendered.replace("Verified data (no model used)", "Verified data (host-rendered after heavy handoff)")
            finish("verified", rendered, "host (deterministic)", step,
                   "decision: verified tool output answers the request")
            break
        if op == "clarify":
            finish("clarify", host.clarify_message(), "host", step, "decision: request is ambiguous")
            break
        finish("abstain", host.abstain_message("decision model abstained"), "host", step, "decision: abstain")
        break
    else:
        finish("step_limit", host.abstain_message(f"step limit of {host.limits.max_steps} reached"), "host", None, "step_limit")

    trace.final = host.compose_final(trace.final, state.action_intents, denied_writes)
    trace.observations = [_obs_json(o) for o in state.observations]
    decisions = [s for s in trace.steps if s.get("decision") and s.get("decision_source") != "native_heavy_fallback"]
    ctx_q = [q for s in trace.steps if s.get("context") for q in s["context"]["decision"]["questions"]]
    gens = [s["generation"] for s in trace.steps if s.get("generation")]
    trace.totals = {
        "decision_calls": len(decisions),
        "decision_questions": sum(len(s["decision"]["questions"]) for s in decisions) + len(ctx_q),
        "decision_latency_ms": round(sum((s["decision"]["latency_ms"] or 0) for s in decisions)
                                     + sum((q["latency_ms"] or 0) for q in ctx_q), 1),
        "decision_input_tokens": sum((s["decision"]["input_tokens"] or 0) for s in decisions)
                                 + sum((q["input_tokens"] or 0) for q in ctx_q),
        "tool_calls": sum(1 for o in state.observations if o.operation in ("call_tool", "call_workflow")
                          and o.status in ("ok", "error")),
        "rejected_decisions": rejections,
        "verification_requests": verification_requests,
        "escalations": sum(1 for s in decisions for q in s["decision"]["questions"] if q["name"] == "escalation"),
        "generation_calls": {t: sum(1 for g in gens if g.get("tier") == t and g.get("status") == "ok") for t in ("light", "heavy")},
        "generation_prompt_tokens": sum(g.get("prompt_tokens") or 0 for g in gens),
        "generation_cached_prompt_tokens": sum(max(0, g.get("cached_prompt_tokens") or 0) for g in gens),
        "generation_completion_tokens": sum(g.get("completion_tokens") or 0 for g in gens),
        "generation_latency_ms": round(sum((g.get("prefill_ms") or 0) + (g.get("decode_ms") or 0) for g in gens), 1),
        "handoffs": sum(1 for s in trace.steps if s.get("handoff")),
        "handoff_rounds": sum(1 for s in trace.steps if s.get("decision_source") == "native_heavy_fallback"),
        "denied_write_proposals": len(denied_writes),
        "wall_ms": round((time.perf_counter() - t_turn) * 1000, 1),
        "writes_executed": len(host.world.write_ledger),
    }
    if handoff_record is not None:
        native = [s["generation"] for s in trace.steps if s.get("decision_source") == "native_heavy_fallback"
                  and s.get("generation")]
        trace.totals["handoff"] = {
            "schema": handoff_record["schema"],
            "model_attempts": sum(g["status"] in ("ok", "error", "attempted") for g in native),
            "model_errors": sum(g["status"] == "error" for g in native),
            "usage_complete": all(type(g.get(k)) is int for g in native if g["status"] != "not_run"
                                  for k in ("prompt_tokens", "completion_tokens")),
            "provider_cost_usd": None,
        }
        if not trace.totals["handoff"]["usage_complete"]:
            # A failed local call may have performed unmetered work. An unknown
            # aggregate is not a measured zero, and the turn cannot continue.
            if any(g.get("prompt_tokens") is None for g in native if g["status"] != "not_run"):
                trace.totals["generation_prompt_tokens"] = None
            if any(g.get("completion_tokens") is None for g in native if g["status"] != "not_run"):
                trace.totals["generation_completion_tokens"] = None
            trace.totals["generation_latency_ms"] = None
    return trace
