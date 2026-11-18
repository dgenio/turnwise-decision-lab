"""Opt-in capable-agent arm for the Level C study (issue #9). NEVER run by default, never run in CI.

``run_hosted_agent`` is the heavy-only agent of the v0.7 design with a hosted
model behind an OpenAI-compatible ``/chat/completions`` endpoint and native
tool calling. It goes through the same Host validation, the same LocalHarness
and, when asked, the same exit gate as the local arms, so the paired design of
the local study carries over unchanged: ``hosted_agent`` against
``hosted_agent`` + gate against the contract planner with this agent as its
fallback.

Safety is inherited from ``agent/remote.py``: nothing is sent unless
``allow_remote=True``, an API key is present, both prices are declared and a
spending cap is declared. The cap is checked *before* every request from a
conservative estimate, and provider-reported usage is recorded afterwards.

STATUS: exercised against a local fake HTTP server only (tests/test_v07_hosted.py).
No hosted model has been called from this repository: no credentials, no approved spend.
"""
from __future__ import annotations

import json
import time

from ..agent.contracts import Decision, Observation, Question
from ..agent.heavy_agent import SYSTEM, tool_schemas
from ..agent.host import CATALOG_BY_ID, Host
from ..agent.loop import TurnTrace, _obs_json
from ..agent.remote import _Remote
from ..agent.render import render_facts


class HostedChat(_Remote):
    name = "hosted-chat"

    def __init__(self, *, model: str, endpoint: str, api_key_env: str, allow_remote: bool = False, spend_cap_usd: float | None = None,
                 price_per_input_token: float | None = None, price_per_output_token: float | None = None,
                 price_per_cached_input_token: float | None = None, max_tokens: int = 400, timeout_s: int = 60):
        super().__init__(endpoint=endpoint, api_key_env=api_key_env, allow_remote=allow_remote, spend_cap_usd=spend_cap_usd, timeout_s=timeout_s)
        if price_per_input_token is None or price_per_output_token is None:
            raise PermissionError("declare the provider's input and output price per token so the cap can be enforced")
        self.model, self.max_tokens = model, max_tokens
        self.p_in, self.p_out = price_per_input_token, price_per_output_token
        self.p_cached = price_per_input_token if price_per_cached_input_token is None else price_per_cached_input_token

    def complete(self, messages: list[dict], tools: list[dict]) -> tuple[dict, dict]:
        body = {"model": self.model, "messages": messages, "tools": tools, "max_tokens": self.max_tokens, "temperature": 0}
        est_in = len(json.dumps(body)) // 3 + 50
        self.spend.reserve(est_in * self.p_in + self.max_tokens * self.p_out)
        payload, ms = self._post(body)
        usage = payload.get("usage") or {}
        prompt = usage.get("prompt_tokens", est_in)
        cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
        completion = usage.get("completion_tokens", self.max_tokens)
        cost = (prompt - cached) * self.p_in + cached * self.p_cached + completion * self.p_out
        self.spend.spent_usd += cost
        self.spend.requests += 1
        self.spend.usage.append(usage)
        msg = payload["choices"][0]["message"]
        return msg, {"status": "ok", "tier": "heavy", "model": self.model, "text": msg.get("content") or "",
                     "prompt_tokens": prompt - cached, "cached_prompt_tokens": cached, "completion_tokens": completion,
                     "prefill_ms": ms, "decode_ms": 0.0, "provider_cost_usd": round(cost, 8),
                     "usage_source": "provider-reported" if usage else "estimated from request size"}


def run_hosted_agent(message: str, *, host: Host, chat: HostedChat, turn_id: str, conversation: list[dict] | None = None,
                     gate=None, arm: str = "hosted_agent") -> dict:
    trace = TurnTrace(turn_id, message, arm, host.world.variant)
    t0 = time.perf_counter()
    conversation = list(conversation or [])
    messages = [{"role": "system", "content": f"{SYSTEM}\nVerified incident record: {json.dumps(host.host_facts(), sort_keys=True)}"},
                *conversation, {"role": "user", "content": message}]
    observations: list[Observation] = []
    gens, events, interventions = [], [], 0

    def run_call(step, name, args, provider, kind) -> str:
        call_id = f"{turn_id}/s{step['step_index'] + 1}c{len(step.setdefault('tool_calls', [])) + 1}"
        cap = CATALOG_BY_ID.get(name or "")
        op = "call_workflow" if cap and cap.kind == "workflow" else "call_tool"
        d = Decision(op, name, dict(args) if isinstance(args, dict) else {}, provider=provider, model=chat.model if provider == "hosted-agent" else "host rule",
                     questions=[Question("tool_call", [], name, None, kind)])
        v = host.validate(d, observations)
        if not v.ok:
            obs, content = Observation(step["step_index"], call_id, op, name, d.arguments, "rejected", reason=v.reason), json.dumps({"error": v.reason})
        elif v.status == "approval_required":
            obs = Observation(step["step_index"], call_id, op, name, d.arguments, "approval_required", reason=v.reason)
            content = json.dumps({"status": "approval_requested", "executed": False, "note": "a human must approve this action"})
        else:
            obs = host.execute(d, step_index=step["step_index"], call_id=call_id, user_text=message)
            content = render_facts(obs.facts) if obs.status == "ok" else json.dumps({"error": obs.status, "reason": obs.reason})
        observations.append(obs)
        step["tool_calls"].append({"decision": d.as_json(), "validation": {"status": v.status, "reason": v.reason}, "observation": _obs_json(obs)})
        return content

    def latch(step_index: int) -> None:
        """At any forced exit the gate may still raise the approval the user asked for."""
        nonlocal interventions
        if gate is None:
            return
        v = gate.review(message=message, conversation=conversation, observations=observations, terminal="abstain", interventions=interventions)
        events.append({"step_index": step_index, "terminal": "abstain", **v.as_json()})
        if v.action == "hold":
            interventions += 1
            step = {"step_index": step_index, "decision_call_id": f"{turn_id}/gate"}
            trace.steps.append(step)
            run_call(step, *v.calls[0], gate.name, "none: exit-gate rule (no model inference)")
            if observations[-1].status == "approval_required":
                trace.final = {"kind": "approval_required", "text": host.approval_message(observations[-1]),
                               "by": "host (exit gate: action latch)", "reason": "the user asked for a side effect; the gate raised the approval request"}

    for step_index in range(host.limits.max_steps):
        try:
            msg, gen = chat.complete(messages, tool_schemas())
        except PermissionError as exc:  # spending cap: stop cleanly, never retry around it
            trace.final = {"kind": "abstain", "text": host.abstain_message(str(exc)), "by": "host", "reason": "spending cap"}
            break
        gens.append(gen)
        step = {"step_index": step_index, "decision_call_id": f"{turn_id}/llm{step_index + 1}", "generation": gen}
        trace.steps.append(step)
        calls = msg.get("tool_calls") or []
        if calls:
            messages.append({"role": "assistant", "content": msg.get("content"), "tool_calls": calls})
            for c in calls:
                try:
                    args = json.loads(c["function"].get("arguments") or "{}")
                except (ValueError, TypeError):
                    args = {}
                content = run_call(step, c["function"].get("name"), args, "hosted-agent", "none: provider-native tool call")
                messages.append({"role": "tool", "tool_call_id": c.get("id", ""), "content": content})
            step["continue_reason"] = "tool results returned to the hosted model"
            continue
        text = msg.get("content") or ""
        step["decision"] = Decision("answer", provider="hosted-agent", model=chat.model).as_json()
        trace.final = {"kind": "answer", "text": text, "by": f"hosted model: {chat.model}", "reason": "model produced a final answer"}
        if gate is not None:
            v = gate.review(message=message, conversation=conversation, observations=observations, terminal="answer", text=text, interventions=interventions)
            event = {"step_index": step_index, "terminal": "answer", **v.as_json()}
            events.append(event)
            step["exit_gate"] = event
            if v.action == "acquire":
                interventions += 1
                step["tool_calls"] = []
                parts = []
                for _ in range(8):
                    parts.append(run_call(step, *v.calls[0], gate.name, "none: exit-gate rule (no model inference)"))
                    v = gate.review(message=message, conversation=conversation, observations=observations, terminal="answer", text=text,
                                    interventions=interventions - 1)
                    if v.action != "acquire":
                        break
                messages += [{"role": "assistant", "content": text},
                             {"role": "user", "content": "The host required more evidence before this reply could be sent:\n" + "\n".join(parts)
                                                         + f"\nUsing all the evidence, answer the original request: {message}"}]
                step["continue_reason"] = "exit gate: the reply was not sent; the host ran the evidence the contract requires and returned it"
                trace.final = {}
                continue
            if v.action == "hold":
                interventions += 1
                run_call(step, *v.calls[0], gate.name, "none: exit-gate rule (no model inference)")
                if observations[-1].status == "approval_required":
                    trace.final = {"kind": "approval_required", "text": host.approval_message(observations[-1]),
                                   "by": "host (exit gate: action latch)", "reason": "the user asked for a side effect; the gate raised the approval request"}
            elif v.action == "clarify":
                interventions += 1
                trace.final = {"kind": "clarify", "text": host.clarify_message(), "by": "host (exit gate)", "reason": v.reason}
            else:
                g = gate.ground(text, message=message, conversation=conversation, observations=observations, host_facts=host.host_facts())
                event["grounding"] = {k: g[k] for k in g if k != "replacement"}
                if "replacement" in g:
                    interventions += 1
                    trace.final.update(withheld_text=text, text=g["replacement"], by="host (exit gate: generated reply withheld)", kind="verified")
        step["terminate_reason"] = trace.final["reason"]
        break
    else:
        trace.final = {"kind": "step_limit", "text": host.abstain_message(f"step limit of {host.limits.max_steps} reached"), "by": "host", "reason": "step_limit"}
        latch(host.limits.max_steps)
    if trace.final.get("reason") == "spending cap":
        latch(len(trace.steps))
    trace.observations = [_obs_json(o) for o in observations]
    trace.totals = {
        "decision_calls": 0, "decision_questions": 0, "decision_latency_ms": 0.0, "decision_input_tokens": 0,
        "tool_calls": sum(1 for o in observations if o.status in ("ok", "error")),
        "rejected_decisions": sum(1 for o in observations if o.status == "rejected"),
        "generation_calls": {"light": 0, "heavy": len(gens)},
        "generation_prompt_tokens": sum(g["prompt_tokens"] for g in gens),
        "generation_cached_prompt_tokens": sum(g["cached_prompt_tokens"] for g in gens),
        "generation_completion_tokens": sum(g["completion_tokens"] for g in gens),
        "generation_latency_ms": round(sum(g["prefill_ms"] for g in gens), 1),
        "wall_ms": round((time.perf_counter() - t0) * 1000, 1), "writes_executed": len(host.world.write_ledger),
        "provider_cost_usd": round(sum(g["provider_cost_usd"] for g in gens), 8),
        "gate_interventions": interventions, "gate_events": events,
    }
    return trace.as_json()
