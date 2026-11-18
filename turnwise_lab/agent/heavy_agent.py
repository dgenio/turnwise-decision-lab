"""PRIMARY BASELINE: a conventional agent whose whole control loop is one heavy LLM.

The model sees the user turn, the conversation, the host-verified incident
record and all ten tools in its own native tool-calling format (Qwen2.5
``<tools>`` / ``<tool_call>`` / ``<tool_response>``). It may call tools as many
times as it likes within the step budget; every call goes through the same
Host validation and LocalHarness as the decision-driven loop, and tool output
goes back to the model. KV state is reused across steps (the local equivalent
of provider prompt caching), so each step only processes new tokens.

The baseline shares the host's write-intent gate and final envelope with the
decision-driven loop (#12/#13, #25 parity): a write it proposes is held only if
the user requested it, and a reply claiming an unexecuted action is withheld.
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


def system_block(host: Host, arch: str, *, include_incident_record: bool = True) -> str:
    tools = "\n".join(json.dumps(t, ensure_ascii=False) for t in tool_schemas())
    sys_text = SYSTEM
    if include_incident_record:
        record = json.dumps(host.host_facts(), sort_keys=True)
        sys_text += f"\nVerified incident record: {record}"
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
                    max_new_tokens: int = 220) -> TurnTrace:
    trace = TurnTrace(turn_id, message, "heavy_agent", host.world.variant)
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
    denied: list[dict] = []
    ledger = [dict(e) for e in host.action_intents(message, conversation or [])["intents"]]
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
            else:
                step["decision"] = Decision("answer", provider="heavy-agent", model=lm.version).as_json()
                trace.final = {"kind": "answer", "text": g.text, "by": f"heavy model: {lm.version}", "reason": "model produced a final answer"}
            step["terminate_reason"] = trace.final["reason"]
            break
        responses = []
        step["tool_calls"] = []
        for k, raw in enumerate(calls):
            call_id = f"{turn_id}/s{step_index + 1}c{k + 1}"
            name, args = parse_call(raw)
            cap = CATALOG_BY_ID.get(name or "")
            op = "call_workflow" if cap and cap.kind == "workflow" else "call_tool"
            d = Decision(op, name, dict(args) if isinstance(args, dict) else {}, provider="heavy-agent", model=lm.version,
                         questions=[Question("tool_call", [], name, None, "none: generated tool call text")])
            v = host.validate(d, observations, user_message=message, conversation=conversation or [])
            if not v.ok:
                obs = Observation(step_index, call_id, op, name, d.arguments, "rejected", reason=v.reason)
                content = json.dumps({"error": v.reason})
                if v.intent is not None:
                    denied.append({"capability": name, "arguments": dict(d.arguments), "code": v.intent["code"],
                                   "reason": v.intent["reason"], "proposed_by": "heavy-agent", "call_id": call_id})
            elif v.status == "approval_required":
                obs = Observation(step_index, call_id, op, name, d.arguments, "approval_required", reason=v.reason)
                content = json.dumps({"status": "approval_requested", "executed": False, "note": "a human must approve this action"})
                index = (v.intent or {}).get("intent_index")
                if index is not None and index < len(ledger) and ledger[index]["status"] != "held_for_approval":
                    ledger[index].update(status="held_for_approval", call_id=call_id, held_arguments=dict(d.arguments))
            else:
                obs = host.execute(d, step_index=step_index, call_id=call_id, user_text=message)
                content = render_facts(obs.facts) if obs.status == "ok" else json.dumps({"error": obs.status, "reason": obs.reason})
            observations.append(obs)
            step["tool_calls"].append({"decision": d.as_json(), "validation": {"status": v.status, "reason": v.reason},
                                       "observation": _obs_json(obs)})
            responses.append(f"<tool_response>\n{content}\n</tool_response>")
        step["continue_reason"] = "tool responses returned to the heavy model"
        pending = "<|im_end|>\n<|im_start|>user\n" + "\n".join(responses) + "<|im_end|>\n" + lm.assistant_header()
    else:
        trace.final = {"kind": "step_limit", "text": host.abstain_message(f"step limit of {host.limits.max_steps} reached"),
                       "by": "host", "reason": "step_limit"}
    trace.observations = [_obs_json(o) for o in observations]
    approvals = [o for o in observations if o.status == "approval_required"]
    if trace.final.get("kind") == "answer":
        claims = host.review_generated_answer(trace.final["text"])["unsupported_action_claims"]
        if claims:
            trace.final = {"kind": "abstain", "text": host.withheld_message(claims), "by": "host",
                           "reason": "unsupported_action_claim", "model_text": trace.final["text"],
                           "unsupported_action_claims": claims}
    if approvals and trace.final.get("kind") == "answer":
        trace.final["approval_requested"] = [{"target": o.target, "arguments": o.arguments} for o in approvals]
    trace.final = host.compose_final(trace.final, ledger, denied)
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
    return trace
