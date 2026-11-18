"""PRIMARY BASELINE: a conventional agent whose whole control loop is one heavy LLM.

The model sees the user turn, the conversation, the host-verified incident
record and all ten tools in its own native tool-calling format (Qwen2.5
``<tools>`` / ``<tool_call>`` / ``<tool_response>``). It may call tools as many
times as it likes within the step budget; every call goes through the same
Host validation and LocalHarness as the decision-driven loop, and tool output
goes back to the model. KV state is reused across steps (the local equivalent
of provider prompt caching), so each step only processes new tokens.

v0.7 adds an optional ``gate`` (``turnwise_lab.v07.gate.ExitGate``). With the
default ``gate=None`` this function behaves exactly as it did when the v0.6
traces were recorded; the replay tests pin that. With a gate, the host reviews
the agent's exit: it runs any evidence the contract still requires and hands
the turn back to the model, raises the approval the user asked for, or
withholds a reply that states values found in no receipt.
"""
from __future__ import annotations

import json
import re
import time

from .contracts import Decision, Observation, Question
from .host import CATALOG, CATALOG_BY_ID, Host
from .loop import TurnTrace, _obs_json
from .render import render_facts
from .world import SERVICES

SYSTEM = ("You are an incident-response assistant for an on-call engineer. Use the tools to gather evidence before "
          "explaining a cause; answer simple lookups from the tool results. Side-effecting tools only create an approval "
          "request for a human; never claim they were executed. If the request is ambiguous, ask a short clarifying question. "
          "Be concise and cite the evidence you used.")


def tool_schemas() -> list[dict]:
    out = []
    for c in CATALOG:
        props = {}
        for p in c.params:
            props[p] = ({"type": "string", "enum": list(SERVICES)} if p == "service" else {"type": "string"})
        out.append({"type": "function", "function": {"name": c.id, "description": c.description,
                                                     "parameters": {"type": "object", "properties": props, "required": list(c.params)}}})
    return out


def system_block(host: Host, arch: str) -> str:
    tools = "\n".join(json.dumps(t, ensure_ascii=False) for t in tool_schemas())
    record = json.dumps(host.host_facts(), sort_keys=True)
    sys_text = f"{SYSTEM}\nVerified incident record: {record}"
    if arch == "qwen3_5":  # the model's own native template (tools block first, XML-style calls)
        return ("<|im_start|>system\n# Tools\n\nYou have access to the following functions:\n\n<tools>\n" + tools +
                "\n</tools>\n\nIf you choose to call a function ONLY reply in the following format with NO suffix:\n\n<tool_call>\n"
                "<function=example_function_name>\n<parameter=example_parameter_1>\nvalue_1\n</parameter>\n<parameter=example_parameter_2>\n"
                "This is the value for the second parameter\nthat can span\nmultiple lines\n</parameter>\n</function>\n</tool_call>\n\n"
                "<IMPORTANT>\nReminder:\n- Function calls MUST follow the specified format: an inner <function=...></function> block must be "
                "nested within <tool_call></tool_call> XML tags\n- Required parameters MUST be specified\n- You may provide optional reasoning "
                "for your function call in natural language BEFORE the function call, but NOT after\n- If there is no function call available, "
                "answer the question like normal with your current knowledge and do not tell the user about function calls\n</IMPORTANT>\n\n"
                + sys_text + "<|im_end|>\n")
    return (f"<|im_start|>system\n{sys_text}\n\n# Tools\n\nYou may call one or more functions to "
            "assist with the user query.\n\nYou are provided with function signatures within <tools></tools> XML tags:\n<tools>\n"
            f"{tools}\n</tools>\n\nFor each function call, return a json object with function name and arguments within "
            "<tool_call></tool_call> XML tags:\n<tool_call>\n{\"name\": <function-name>, \"arguments\": <args-json-object>}\n"
            "</tool_call><|im_end|>\n")


CALL_RE = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.S)
XML_FN = re.compile(r"<function=([\w.-]+)>(.*?)</function>", re.S)
XML_PARAM = re.compile(r"<parameter=([\w.-]+)>\s*(.*?)\s*</parameter>", re.S)


def parse_call(raw: str):
    """Parse one native tool call (JSON for Qwen2.5, XML-style for Qwen3.5). Returns (name, args) or (None, {})."""
    m = XML_FN.search(raw)
    if m:
        return m.group(1), {k: v.strip() for k, v in XML_PARAM.findall(m.group(2))}
    try:
        obj = json.loads(raw)
        args = obj.get("arguments") or {}
        if isinstance(args, str):
            args = json.loads(args)
        return obj.get("name"), args if isinstance(args, dict) else {}
    except Exception:
        return None, {}


_PREFIX_CACHE: dict = {}


def warm_prefix(host: Host, lm) -> float:
    """Fill the system+tools prefix cache once; returns the one-off cost in ms."""
    sysb = system_block(host, lm.arch)
    key = (lm.version, sysb)
    if key in _PREFIX_CACHE:
        return 0.0
    t0 = time.perf_counter()
    _, st, n = lm.extend(sysb)
    _PREFIX_CACHE[key] = (st, n)
    return round((time.perf_counter() - t0) * 1000, 1)


def run_heavy_agent(message: str, *, host: Host, lm, turn_id: str, conversation: list[dict] | None = None,
                    max_new_tokens: int = 220, gate=None, arm: str = "heavy_agent") -> TurnTrace:
    trace = TurnTrace(turn_id, message, arm, host.world.variant)
    interventions = 0
    gate_events: list[dict] = []
    t_turn = time.perf_counter()
    convo = "".join(f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>\n" for m in (conversation or []))
    sysb = system_block(host, lm.arch)
    key = (lm.version, sysb)
    if key not in _PREFIX_CACHE:  # system + tools prefix cached across turns (like provider prompt caching)
        _, st, n = lm.extend(sysb)
        _PREFIX_CACHE[key] = (st, n)
    state, past = _PREFIX_CACHE[key]
    pending = convo + f"<|im_start|>user\n{message}<|im_end|>\n" + lm.assistant_header()
    observations: list[Observation] = []
    gens = []

    def run_call(step: dict, step_index: int, k: int, name, args, provider: str, kind: str) -> str:
        """Validate and execute one proposed call through the host; returns the text handed back to the model."""
        call_id = f"{turn_id}/s{step_index + 1}c{k + 1}"
        cap = CATALOG_BY_ID.get(name or "")
        op = "call_workflow" if cap and cap.kind == "workflow" else "call_tool"
        d = Decision(op, name, dict(args) if isinstance(args, dict) else {}, provider=provider, model=lm.version if provider == "heavy-agent" else "host rule",
                     questions=[Question("tool_call", [], name, None, kind)])
        v = host.validate(d, observations)
        vetoed = gate.veto(message, conversation or [], name) if gate is not None and provider == "heavy-agent" else None
        if vetoed:
            v = type(v)(False, d, "rejected", vetoed)
        if not v.ok:
            obs = Observation(step_index, call_id, op, name, d.arguments, "rejected", reason=v.reason)
            content = json.dumps({"error": v.reason})
        elif v.status == "approval_required":
            obs = Observation(step_index, call_id, op, name, d.arguments, "approval_required", reason=v.reason)
            content = json.dumps({"status": "approval_requested", "executed": False, "note": "a human must approve this action"})
        else:
            obs = host.execute(d, step_index=step_index, call_id=call_id, user_text=message)
            content = render_facts(obs.facts) if obs.status == "ok" else json.dumps({"error": obs.status, "reason": obs.reason})
        observations.append(obs)
        step.setdefault("tool_calls", []).append({"decision": d.as_json(), "validation": {"status": v.status, "reason": v.reason},
                                                  "observation": _obs_json(obs)})
        return content

    def gate_exit(step: dict | None, step_index: int, terminal: str, text: str | None):
        """Returns "continue" when the gate handed the turn back to the model, else None. May rewrite trace.final."""
        nonlocal interventions, pending
        if gate is None:
            return None
        v = gate.review(message=message, conversation=conversation or [], observations=observations, terminal=terminal, text=text,
                        interventions=interventions)
        event = {"step_index": step_index, "terminal": terminal, **v.as_json()}
        gate_events.append(event)
        if step is not None:
            step["exit_gate"] = event
        if v.action == "allow":
            if terminal == "answer" and text is not None:
                g = gate.ground(text, message=message, conversation=conversation or [], observations=observations, host_facts=host.host_facts())
                event["grounding"] = {k: g[k] for k in g if k != "replacement"}
                if "replacement" in g:
                    interventions += 1
                    trace.final["withheld_text"] = trace.final["text"]
                    trace.final.update(text=g["replacement"], by="host (exit gate: generated reply withheld)", kind="verified")
            return None
        interventions += 1
        if v.action == "acquire" and terminal == "answer" and step is not None:
            step["tool_calls"] = []
            responses = []
            for _ in range(8):  # one call at a time: what comes back can revise the contract (retry, widen, drop)
                name, args = v.calls[0]
                content = run_call(step, step_index, len(step["tool_calls"]), name, args, gate.name, "none: exit-gate rule (no model inference)")
                responses.append(f"<tool_response>\n{content}\n</tool_response>")
                v = gate.review(message=message, conversation=conversation or [], observations=observations, terminal=terminal, text=text,
                                interventions=interventions - 1)
                if v.action != "acquire":
                    break
            if step_index >= host.limits.max_steps - 1:  # no step left for the model to answer again: the host reports what it has
                trace.final = {"kind": "verified", "by": "host (exit gate: step limit after acquisition)", "withheld_text": text,
                               "reason": "required evidence was gathered at the last step; the generated reply was not sent",
                               "text": gate.findings(message, conversation or [], observations,
                                                     "[The generated reply was not sent: it lacked required evidence, and the step limit left no room to write a new one.]")}
                return None
            step["continue_reason"] = "exit gate: the reply was not sent; the host ran the evidence the contract requires and returned it"
            pending = ("<|im_end|>\n<|im_start|>user\n" + "\n".join(responses) +
                       "\nMore evidence was required before answering. Using all the evidence above, answer the original request: "
                       + message + "<|im_end|>\n" + lm.assistant_header())
            return "continue"
        if v.action == "hold":
            name, args = v.calls[0]
            holder = step if step is not None else {"step_index": step_index, "decision_call_id": f"{turn_id}/gate"}
            if step is None:
                trace.steps.append(holder)
            run_call(holder, step_index, len(holder.get("tool_calls", [])), name, args, gate.name, "none: exit-gate rule (no model inference)")
            last = observations[-1]
            if last.status == "approval_required":
                trace.final = {"kind": "approval_required", "text": host.approval_message(last), "by": "host (exit gate: action latch)",
                               "reason": "the user asked for a side effect; the gate raised the approval request"}
            return None
        if v.action == "clarify":
            trace.final = {"kind": "clarify", "text": host.clarify_message(), "by": "host (exit gate)", "reason": v.reason}
        return None

    for step_index in range(host.limits.max_steps):
        g, state, past = lm.generate_continue(pending, state, past, max_new_tokens=max_new_tokens)
        gen = {"status": "ok", "tier": "heavy", "model": lm.version, "text": g.text, "prompt_tokens": g.prompt_tokens,
               "cached_prompt_tokens": past - g.prompt_tokens - g.completion_tokens, "completion_tokens": g.completion_tokens,
               "prefill_ms": g.prefill_ms, "decode_ms": g.decode_ms, "stopped": g.stopped}
        gens.append(gen)
        calls = CALL_RE.findall(g.text)
        step = {"step_index": step_index, "decision_call_id": f"{turn_id}/llm{step_index + 1}", "generation": gen}
        trace.steps.append(step)
        if not calls:
            if "<tool_call>" in g.text:
                step["decision"] = Decision("abstain", provider="heavy-agent", model=lm.version, rationale="malformed tool call").as_json()
                trace.final = {"kind": "abstain", "text": host.abstain_message("malformed tool call"), "by": "host",
                               "reason": "malformed tool call"}
                gate_exit(step, step_index, "abstain", None)
            else:
                step["decision"] = Decision("answer", provider="heavy-agent", model=lm.version).as_json()
                trace.final = {"kind": "answer", "text": g.text, "by": f"heavy model: {lm.version}", "reason": "model produced a final answer"}
                if gate_exit(step, step_index, "answer", g.text) == "continue":
                    trace.final = {}
                    continue
            step["terminate_reason"] = trace.final["reason"]
            break
        responses = []
        step["tool_calls"] = []
        for k, raw in enumerate(calls):
            name, args = parse_call(raw)
            content = run_call(step, step_index, k, name, args, "heavy-agent", "none: generated tool call text")
            responses.append(f"<tool_response>\n{content}\n</tool_response>")
        step["continue_reason"] = "tool responses returned to the heavy model"
        pending = "<|im_end|>\n<|im_start|>user\n" + "\n".join(responses) + "<|im_end|>\n" + lm.assistant_header()
    else:
        trace.final = {"kind": "step_limit", "text": host.abstain_message(f"step limit of {host.limits.max_steps} reached"),
                       "by": "host", "reason": "step_limit"}
        gate_exit(None, host.limits.max_steps, "abstain", None)
    trace.observations = [_obs_json(o) for o in observations]
    approvals = [o for o in observations if o.status == "approval_required"]
    if approvals and trace.final.get("kind") == "answer":
        trace.final["approval_requested"] = [{"target": o.target, "arguments": o.arguments} for o in approvals]
    trace.totals = {
        "decision_calls": 0, "decision_questions": 0, "decision_latency_ms": 0.0, "decision_input_tokens": 0,
        "tool_calls": sum(1 for o in observations if o.status in ("ok", "error")),
        "rejected_decisions": sum(1 for o in observations if o.status == "rejected"),
        "generation_calls": {"light": 0, "heavy": len(gens)},
        "generation_prompt_tokens": sum(g["prompt_tokens"] for g in gens),
        "generation_cached_prompt_tokens": sum(g["cached_prompt_tokens"] for g in gens),
        "generation_completion_tokens": sum(g["completion_tokens"] for g in gens),
        "generation_latency_ms": round(sum(g["prefill_ms"] + g["decode_ms"] for g in gens), 1),
        "wall_ms": round((time.perf_counter() - t_turn) * 1000, 1),
        "writes_executed": len(host.world.write_ledger),
    }
    if gate is not None:
        trace.totals["gate_interventions"] = interventions
        trace.totals["gate_events"] = gate_events
    return trace
