"""Post-hoc audit of the recorded v0.6 held-out traces.

Added after the held-out run, in response to the owner review of PR #6 and issue #5.
It only re-reads `reports/v06/traces/heldout/*.json`. It never changes a trace, a
frozen label, a score, a prediction verdict or the pre-registration.

    python -m turnwise_lab.agent.audit                     # writes reports/v06/audit.{json,md}
    python -m turnwise_lab.agent.audit --packet DIR        # writes a blinded adjudication packet + key to DIR

The audit has four parts:
1. full local compute and token accounting, including the controller's own scoring passes;
2. why the conservative escalation gate did not help (the probability at each decisive step);
3. a mechanical failure taxonomy from the traces;
4. if `reports/v06/adjudication/grades.json` exists, the blinded adjudication merged with its key.
"""
from __future__ import annotations

from pathlib import Path
import argparse
import hashlib
import json

from . import world as world_mod
from .bench import ARM_LABELS, ARMS, OUT, SETS, load_scenarios, score
from .render import render_fact

TRACES = OUT / "traces" / "heldout"
ADJ = OUT / "adjudication"
ADJ_ARMS = ("heavy_agent", "rules", "dm_dynamic")
ADJ_TASKS = ("H07", "H08", "H09", "H10", "H11", "H12", "H13", "H18", "H19")
QWEN35 = "Qwen3.5-0.8B"


def _load(arm: str) -> dict | None:
    p = TRACES / f"{arm}.json"
    return json.loads(p.read_text()) if p.exists() else None


# ------------------------------------------------------------------ 1. accounting
def accounting(traces: list[dict]) -> dict:
    n = len(traces)
    acc = {k: 0.0 for k in ("op_q", "op_q_tokens", "op_ms", "arg_q", "arg_q_tokens", "arg_ms", "ctx_q", "ctx_q_tokens", "ctx_ms",
                            "heavy_calls", "heavy_new", "heavy_cached", "heavy_out", "heavy_ms",
                            "light_calls", "light_new", "light_cached", "light_out", "light_ms", "wall_ms", "tool_calls", "decode_ms")}
    ctx_models = set()
    for t in traces:
        acc["wall_ms"] += t["totals"].get("wall_ms", 0.0)
        acc["tool_calls"] += t["totals"].get("tool_calls", 0)
        for st in t["steps"]:
            for q in (st.get("decision") or {}).get("questions") or []:
                kind = "arg" if q["name"] == "arguments" else ("op" if q["name"] in ("operation", "kind") else None)
                if kind:
                    acc[f"{kind}_q"] += 1 if q.get("input_tokens") else 0
                    acc[f"{kind}_q_tokens"] += q.get("input_tokens") or 0
                    acc[f"{kind}_ms"] += q.get("latency_ms") or 0.0
            cd = (st.get("context") or {}).get("decision") or {}
            if cd.get("questions"):
                ctx_models.add(cd.get("model"))
            for q in cd.get("questions") or []:
                if not q.get("input_tokens"):
                    continue  # rule-based selection (no model question)
                acc["ctx_q"] += 1
                acc["ctx_q_tokens"] += q.get("input_tokens") or 0
                acc["ctx_ms"] += q.get("latency_ms") or 0.0
            g = st.get("generation")
            if g and g.get("status") == "ok" and g.get("tier") in ("heavy", "light"):
                p = g["tier"]
                acc[f"{p}_calls"] += 1
                acc[f"{p}_new"] += g.get("prompt_tokens") or 0
                acc[f"{p}_cached"] += g.get("cached_prompt_tokens") or 0
                acc[f"{p}_out"] += g.get("completion_tokens") or 0
                acc[f"{p}_ms"] += (g.get("prefill_ms") or 0.0) + (g.get("decode_ms") or 0.0)
                acc["decode_ms"] += g.get("decode_ms") or 0.0
    ctx_on_qwen35 = any(m and "Qwen3.5" in m for m in ctx_models)
    qwen35_computed = acc["op_q_tokens"] + (acc["ctx_q_tokens"] if ctx_on_qwen35 else 0) + acc["heavy_new"] + acc["heavy_out"]
    other_ms = acc["wall_ms"] - acc["op_ms"] - acc["arg_ms"] - acc["ctx_ms"] - acc["heavy_ms"] - acc["light_ms"]
    per = lambda v, d=2: round(v / n, d) if n else None
    return {
        "tasks": n,
        "per_task_s": {"total": per(acc["wall_ms"] / 1000), "controller": per(acc["op_ms"] / 1000), "argument_extraction": per(acc["arg_ms"] / 1000),
                       "context_selection": per(acc["ctx_ms"] / 1000), "heavy_generation": per(acc["heavy_ms"] / 1000),
                       "light_generation": per(acc["light_ms"] / 1000), "host_tools_other": per(other_ms / 1000)},
        "tokens_total": {"controller_scoring_input": int(acc["op_q_tokens"]), "argument_extraction_input": int(acc["arg_q_tokens"]),
                         "context_selection_input": int(acc["ctx_q_tokens"]),
                         "heavy_new_prompt": int(acc["heavy_new"]), "heavy_cached_prompt": int(acc["heavy_cached"]),
                         "heavy_completion": int(acc["heavy_out"]),
                         "light_new_prompt": int(acc["light_new"]), "light_completion": int(acc["light_out"])},
        "qwen35_tokens_computed_per_task": per(qwen35_computed, 1),
        "generated_tokens_per_task": per(acc["heavy_out"] + acc["light_out"], 1),
        "decode_s_per_task": per(acc["decode_ms"] / 1000),
        "qwen35_cache_hit_tokens_per_task": per(acc["heavy_cached"], 1),
        "heavy_generation_tokens_per_task_as_preregistered": per(acc["heavy_new"] + acc["heavy_cached"] + acc["heavy_out"], 1),
        "calls_per_task": {"controller_questions": per(acc["op_q"]), "context_questions": per(acc["ctx_q"]), "heavy": per(acc["heavy_calls"]),
                           "light": per(acc["light_calls"]), "tools": per(acc["tool_calls"])},
        "context_selector_model": sorted(m for m in ctx_models if m),
    }


# ------------------------------------------------------------ 2. gate diagnosis
def _decisions(t: dict) -> list[dict]:
    out = []
    for st in t["steps"]:
        d = st.get("decision")
        if not d:
            continue
        op = next((q for q in d.get("questions") or [] if q["name"] in ("operation", "kind")), None)
        esc = next((q for q in d.get("questions") or [] if q["name"] == "escalation"), None)
        top = max(op["scores"].values()) if op and op.get("scores") else None
        label = d.get("target") or d.get("operation")
        if d.get("operation") == "call_model":
            label = f"{d.get('model_tier')}_model"
        out.append({"step": st["step_index"], "chosen": label, "top_p": round(top, 3) if top is not None else None,
                    "escalated": bool(esc and esc.get("answer") == "escalate")})
    return out


def gate_diagnosis(traces: list[dict], scen: dict, gate: float = 0.5) -> dict:
    rows = []
    for t in traces:
        sc = score(scen[t["scenario_id"]], t)
        ds = _decisions(t)
        decisive = ds[-1] if ds else None
        rows.append({"id": t["scenario_id"], "category": scen[t["scenario_id"]]["category"], "success": sc["success"],
                     "final_kind": sc["final_kind"], "missing_facts": sc["missing_facts"], "dropped_action": sc["dropped_action"],
                     "sequence": " → ".join(f"{d['chosen']} ({d['top_p']})" if d["top_p"] is not None else d["chosen"] for d in ds),
                     "decisive_top_p": decisive["top_p"] if decisive else None,
                     "escalated": any(d["escalated"] for d in ds)})
    fails = [r for r in rows if not r["success"]]
    bins = [(0.0, gate, f"< {gate} (gate fires)"), (gate, 0.8, f"{gate}-0.8"), (0.8, 0.95, "0.8-0.95"), (0.95, 1.01, ">= 0.95")]
    table = []
    for lo, hi, name in bins:
        inb = [r for r in rows if r["decisive_top_p"] is not None and lo <= r["decisive_top_p"] < hi]
        table.append({"bin": name, "tasks": len(inb), "successes": sum(r["success"] for r in inb)})
    return {"gate": gate, "rows": rows, "bins": table,
            "failures_with_confident_decisive_step": sum(1 for r in fails if (r["decisive_top_p"] or 0) >= gate),
            "failures": len(fails),
            "escalated": [{"id": r["id"], "category": r["category"], "success": r["success"], "final_kind": r["final_kind"],
                           "dropped_action": r["dropped_action"]} for r in rows if r["escalated"]]}


# ---------------------------------------------------------- 3. failure taxonomy
TAXONOMY = {
    "premature_finish": "Causal question handled as a lookup: finished with raw verified data while required evidence was missing",
    "incomplete_evidence_generation": "Missed a complementary tool, then generated an answer with incomplete evidence",
    "evidence_complete_answer_rejected": "All required evidence gathered, but the answer failed the lexical check (adjudicate: poor generation or grader defect)",
    "dropped_action": "Action request neither raised for approval nor executed",
    "false_clarification": "Asked a clarifying question where an answer was expected",
    "missed_clarification": "Acted or answered where a clarifying question was expected",
    "forbidden_or_unrequested_action": "Proposed a forbidden side effect",
    "stopped": "Stopped at the step limit or abstained",
    "other": "Other",
}


def classify(sc: dict, e: dict) -> str:
    if sc["forbidden_requested"]:
        return "forbidden_or_unrequested_action"
    if e["outcome"] == "approval" and sc["dropped_action"]:
        return "dropped_action"
    if e["outcome"] == "clarify":
        return "missed_clarification"
    if sc["false_clarify"]:
        return "false_clarification"
    if sc["final_kind"] in ("step_limit", "abstain"):
        return "stopped"
    if sc["final_kind"] == "verified" and sc["missing_facts"]:
        return "premature_finish"
    if sc["final_kind"] == "answer" and sc["missing_facts"]:
        return "incomplete_evidence_generation"
    if sc["final_kind"] in ("answer", "verified") and not sc["missing_facts"]:
        return "evidence_complete_answer_rejected"
    return "other"


def taxonomy(traces_by_arm: dict, scen: dict) -> dict:
    out = {}
    for arm, traces in traces_by_arm.items():
        counts = {k: 0 for k in TAXONOMY}
        cases = []
        for t in traces:
            e = scen[t["scenario_id"]]["expect"]
            sc = score(scen[t["scenario_id"]], t)
            if sc["success"]:
                continue
            k = classify(sc, e)
            counts[k] += 1
            cases.append({"id": t["scenario_id"], "category": scen[t["scenario_id"]]["category"], "class": k,
                          "missing_facts": sc["missing_facts"]})
        out[arm] = {"counts": {k: v for k, v in counts.items() if v}, "cases": cases}
    return out


# ----------------------------------------------------------- 4. adjudication
def _reference(s: dict) -> list[str]:
    """Ground truth for the required facts, read from the same deterministic world variant."""
    w = world_mod.IncidentWorld(s["world_variant"])
    tool = {"errors": w.get_error_metrics, "deploys": w.get_deployment_history, "health": w.get_service_health,
            "config": w.get_config_diff, "owner": w.get_service_owner}
    lines = []
    for f in s["expect"].get("required_facts", []):
        kind, target = f.split(":", 1)
        if kind == "doc":
            d = world_mod.v05.DOCS_BY_ID[target]
            lines.append(render_fact(f, {"title": d.title, "body": d.body}))
        elif kind in tool:
            w._flaky_remaining = 0
            lines.append(render_fact(f, tool[kind]({"service": target})["facts"][f]))
    return lines


def _item_order(scenario_id: str, arm: str) -> str:
    return hashlib.sha256(f"turnwise-v06-adjudication|{scenario_id}|{arm}".encode()).hexdigest()


def build_packet() -> tuple[dict, dict]:
    scen = {s["id"]: s for s in load_scenarios(SETS["heldout"])}
    entries = []
    for arm in ADJ_ARMS:
        data = _load(arm)
        by_id = {t["scenario_id"]: t for t in data["traces"]}
        for sid in ADJ_TASKS:
            entries.append((_item_order(sid, arm), sid, arm, by_id[sid]))
    entries.sort()
    items, key = [], {}
    for i, (_, sid, arm, t) in enumerate(entries, 1):
        s = scen[sid]
        iid = f"J{i:02d}"
        key[iid] = {"scenario": sid, "arm": arm}
        evidence = [render_fact(k, v) for o in t["observations"] if o["status"] == "ok" for k, v in o["facts"].items()]
        approvals = [f"{o['target']}(service={o['arguments'].get('service')})" for o in t["observations"] if o["status"] == "approval_required"]
        items.append({"item": iid, "request": s["message"], "earlier_conversation": s.get("conversation", []),
                      "expected_kind_of_reply": s["expect"]["outcome"], "what_a_good_reply_does": s["expect"]["note"],
                      "reference_facts": _reference(s),
                      "evidence_the_system_gathered": evidence, "approval_requests_raised": approvals,
                      "final_reply_kind": t["final"].get("kind"), "final_reply": t["final"].get("text") or ""})
    return {"version": 1, "items": items}, key


def packet_markdown(packet: dict) -> str:
    L = ["# v0.6 blinded adjudication packet", "",
         "Grade each item with the rubric in `docs/v06-adjudication-rubric.md`. Items are shuffled and carry no architecture name.", ""]
    for it in packet["items"]:
        L += [f"## {it['item']}", "", f"**Request:** {it['request']}"]
        for m in it["earlier_conversation"]:
            L.append(f"- earlier {m['role']}: {m['content']}")
        L += ["", f"**Expected kind of reply:** {it['expected_kind_of_reply']}", f"**What a good reply does:** {it['what_a_good_reply_does']}", "",
              "**Reference facts (ground truth):**"] + [f"- {x}" for x in it["reference_facts"] or ["(none required)"]]
        L += ["", "**Evidence the system gathered:**"] + [f"- {x}" for x in it["evidence_the_system_gathered"] or ["(none)"]]
        L += ["", "**Approval requests raised:** " + (", ".join(it["approval_requests_raised"]) or "none"),
              f"**Final reply kind:** {it['final_reply_kind']}", "", "```text", it["final_reply"], "```", ""]
    return "\n".join(L)


def merge_adjudication(scen: dict) -> dict | None:
    gp, kp = ADJ / "grades.json", ADJ / "key.json"
    if not (gp.exists() and kp.exists()):
        return None
    grades = {g["item"]: g for g in json.loads(gp.read_text())["grades"]}
    key = json.loads(kp.read_text())
    frozen = {}
    for arm in ADJ_ARMS:
        for t in _load(arm)["traces"]:
            if t["scenario_id"] in ADJ_TASKS:
                frozen[(t["scenario_id"], arm)] = score(scen[t["scenario_id"]], t)["success"]
    rows = []
    for iid, k in sorted(key.items(), key=lambda kv: (ADJ_TASKS.index(kv[1]["scenario"]), ADJ_ARMS.index(kv[1]["arm"]))):
        g = grades.get(iid, {})
        rows.append({"item": iid, "scenario": k["scenario"], "arm": k["arm"], "frozen_success": frozen[(k["scenario"], k["arm"])],
                     **{f: g.get(f) for f in ("outcome", "causal_claim", "severity", "acknowledges_missing_evidence", "action_handling", "rationale")}})
    per_arm = {}
    for arm in ADJ_ARMS:
        rs = [r for r in rows if r["arm"] == arm]
        cnt = lambda f, v: sum(1 for r in rs if r[f] == v)
        per_arm[arm] = {"items": len(rs), "correct": cnt("outcome", "correct"), "partial": cnt("outcome", "partial"),
                        "incorrect": cnt("outcome", "incorrect"),
                        "unsupported_or_contradicted_causal_claims": sum(1 for r in rs if r["causal_claim"] in ("unsupported", "contradicted")),
                        "severity": {s: cnt("severity", s) for s in ("none", "minor", "major", "critical")},
                        "agrees_with_frozen_check": sum(1 for r in rs if (r["outcome"] == "correct") == r["frozen_success"])}
    return {"adjudicator": json.loads(gp.read_text()).get("adjudicator"), "rows": rows, "per_arm": per_arm}


# ------------------------------------------------------------------- report
def audit() -> dict:
    scen = {s["id"]: s for s in load_scenarios(SETS["heldout"])}
    loaded = {arm: _load(arm) for arm in ARMS}
    traces = {arm: d["traces"] for arm, d in loaded.items() if d and len(d["traces"]) == len(scen)}
    return {
        "note": "Post-hoc audit of recorded held-out traces; added after the run. Changes no trace, label, score or verdict.",
        "accounting": {arm: accounting(ts) for arm, ts in traces.items()},
        "gate": {arm: gate_diagnosis(traces[arm], scen) for arm in ("dm_dynamic",) if arm in traces},
        "taxonomy": taxonomy(traces, scen),
        "taxonomy_labels": TAXONOMY,
        "adjudication": merge_adjudication(scen),
    }


def render_markdown(a: dict) -> str:
    L = ["# v0.6 post-hoc audit (held-out traces)", "",
         "Generated by `python -m turnwise_lab.agent.audit` from `reports/v06/traces/heldout/`. It was added after the run, in response to the "
         "owner review of PR #6 and issue #5. **It changes no trace, frozen label, score or prediction verdict**, and nothing here was tuned "
         "on these cases. Status of the v0.6 result: **exploratory and inconclusive.**", "",
         "## 1. Full local compute and token accounting", "",
         "The pre-registered \"heavy tokens\" metric counts heavy *generation* only: new prompt, cache-reused prefix and completion. "
         f"It leaves out the decision controller's own scoring passes, which run on the same {QWEN35} model, and the context-selection questions. "
         "This table counts everything, per attempted task.", "",
         "| Arm | Wall time | Controller | Arg. extraction | Context selection | Heavy gen. | Light gen. | Host, tools, other | "
         f"{QWEN35} tokens computed | Cache-reused tokens | Heavy gen. tokens (pre-registered metric) |",
         "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for arm, x in a["accounting"].items():
        p = x["per_task_s"]
        L.append(f"| {arm} | {p['total']} s | {p['controller']} s | {p['argument_extraction']} s | {p['context_selection']} s | "
                 f"{p['heavy_generation']} s | {p['light_generation']} s | {p['host_tools_other']} s | {x['qwen35_tokens_computed_per_task']:,} | "
                 f"{x['qwen35_cache_hit_tokens_per_task']:,} | {x['heavy_generation_tokens_per_task_as_preregistered']:,} |")
    acc = a["accounting"]
    if "heavy_agent" in acc and "dm_dynamic" in acc:
        A, D = acc["heavy_agent"], acc["dm_dynamic"]
        red_pre = 1 - D["heavy_generation_tokens_per_task_as_preregistered"] / A["heavy_generation_tokens_per_task_as_preregistered"]
        red_all = 1 - D["qwen35_tokens_computed_per_task"] / A["qwen35_tokens_computed_per_task"]
        red_wall = 1 - D["per_task_s"]["total"] / A["per_task_s"]["total"]
        more = f"**{-red_all:.1%} more**" if red_all < 0 else f"{red_all:.1%} fewer"
        L += ["", f"Reading: the pre-registered metric shows a {red_pre:.1%} reduction in heavy generation tokens. That figure counts the "
              f"heavy-only agent's cache-reused tokens on every call. Those are its system prompt, its tool schemas and the turn so far: "
              f"{A['qwen35_cache_hit_tokens_per_task']:,} per task, which the model does not recompute. It also leaves out the controller's own scoring. "
              f"Counting only the tokens {QWEN35} actually computed (controller scoring, context questions, heavy prompt and completion), "
              f"the decision-driven arm processed {more} tokens than the heavy-only agent "
              f"({D['qwen35_tokens_computed_per_task']:,} vs {A['qwen35_tokens_computed_per_task']:,} per task). "
              f"**The {red_pre:.1%} figure is therefore not a compute saving.** What did fall is local compute per attempted task, by {red_wall:.1%}. "
              f"That saving is mostly decoding: the heavy-only agent generated {A['generated_tokens_per_task']} tokens per task (tool calls and answers) "
              f"in {A['decode_s_per_task']} s of decode, against {D['generated_tokens_per_task']} tokens and {D['decode_s_per_task']} s for the "
              "decision-driven arm. Both arms reuse a cached prefix. The decision controller reuses its few-shot prefix, but that reuse is not counted "
              "per call in the traces. It also re-reads the growing turn state at every decision instead of reusing a cache across steps; that is an "
              "implementation choice, not inherent to the design. A hosted provider would bill cache-reused tokens, usually at a discount.", ""]
    L += ["Context selection overhead: "]
    for arm in ("dm_dynamic", "dm_full"):
        if arm in acc:
            x = acc[arm]
            L.append(f"- `{arm}`: {x['calls_per_task']['context_questions']} context questions and {x['per_task_s']['context_selection']} s per task; "
                     f"{x['tokens_total']['context_selection_input']:,} context-question input tokens in total.")
    L += ["", "## 2. Why the conservative escalation gate did not help", ""]
    for arm, g in a["gate"].items():
        L += [f"**{arm}** (gate: escalate when the top probability is below {g['gate']}): {g['failures_with_confident_decisive_step']} of "
              f"{g['failures']} failures were decided at a step whose top probability was at or above the gate, so the gate could not fire on them.", "",
              "| Top probability at the decisive step | Tasks | Successes |", "|---|---:|---:|"]
        L += [f"| {b['bin']} | {b['tasks']} | {b['successes']} |" for b in g["bins"]]
        L += ["", "Escalated tasks: " + ("; ".join(f"`{e['id']}` ({e['category']}): {'success' if e['success'] else 'failure'}, final `{e['final_kind']}`"
                                               + (", **action dropped**" if e["dropped_action"] else "") for e in g["escalated"]) or "none"), ""]
    L += ["What this shows: most failures were **confident** errors, so a probability gate cannot catch them. Where the gate did fire on an "
          "action request, it handed the turn to a text generator that cannot raise an approval, so the action was dropped. "
          "Both of D's dropped actions (H18, H19) happened this way. This is a design defect of the escalation path, not a threshold "
          "problem. Any fix must be validated on new cases, not by moving the threshold on these.", "",
          "Decision sequences of the decision-driven arm (`dm_dynamic`) on its failures:", "",
          "| Task | Family | Decisions (top probability) | Missing evidence | Final |", "|---|---|---|---|---|"]
    for r in a["gate"].get("dm_dynamic", {}).get("rows", []):
        if not r["success"]:
            L.append(f"| {r['id']} | {r['category']} | {r['sequence']} | {', '.join(r['missing_facts']) or '-'} | {r['final_kind']}"
                     + (" (action dropped)" if r["dropped_action"] else "") + " |")
    L += ["", "## 3. Failure taxonomy (mechanical, from the traces)", "",
          "| Class | " + " | ".join(a["taxonomy"]) + " |", "|---|" + "---:|" * len(a["taxonomy"])]
    for k, label in a["taxonomy_labels"].items():
        vals = [a["taxonomy"][arm]["counts"].get(k, 0) for arm in a["taxonomy"]]
        if any(vals):
            L.append(f"| {label} | " + " | ".join(str(v) for v in vals) + " |")
    L.append("")
    adj = a.get("adjudication")
    L += ["## 4. Blinded adjudication of investigations and action requests", ""]
    if not adj:
        L += ["Not yet graded. Build the packet with `python -m turnwise_lab.agent.audit --packet DIR` and grade it with "
              "`docs/v06-adjudication-rubric.md`.", ""]
    else:
        L += [f"Adjudicator: {adj['adjudicator']}. The adjudicator saw shuffled items with no architecture name. The frozen lexical scores are unchanged; "
              "this is a second, independent reading.", "",
              "| Arm | Items | Correct | Partial | Incorrect | Unsupported or contradicted causal claims | Severity none / minor / major / critical | Agrees with frozen check |",
              "|---|---:|---:|---:|---:|---:|---:|---:|"]
        for arm, p in adj["per_arm"].items():
            s = p["severity"]
            L.append(f"| {arm} | {p['items']} | {p['correct']} | {p['partial']} | {p['incorrect']} | {p['unsupported_or_contradicted_causal_claims']} | "
                     f"{s['none']} / {s['minor']} / {s['major']} / {s['critical']} | {p['agrees_with_frozen_check']}/{p['items']} |")
        L += ["", "| Task | Arm | Frozen check | Adjudicated | Causal claim | Severity | Rationale |", "|---|---|---|---|---|---|---|"]
        for r in adj["rows"]:
            L.append(f"| {r['scenario']} | {r['arm']} | {'pass' if r['frozen_success'] else 'fail'} | {r['outcome']} | {r['causal_claim']} | "
                     f"{r['severity']} | {(r['rationale'] or '').replace('|', '/')} |")
        L.append("")
    return "\n".join(L)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--packet", help="write the blinded adjudication packet and key to this directory")
    a = p.parse_args()
    if a.packet:
        d = Path(a.packet)
        d.mkdir(parents=True, exist_ok=True)
        packet, key = build_packet()
        (d / "packet.json").write_text(json.dumps(packet, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        (d / "packet.md").write_text(packet_markdown(packet), encoding="utf-8")
        (d / "key.json").write_text(json.dumps(key, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {len(packet['items'])} items to {d}")
        return
    r = audit()
    (OUT / "audit.json").write_text(json.dumps(r, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    (OUT / "audit.md").write_text(render_markdown(r), encoding="utf-8")
    print(f"wrote {OUT / 'audit.md'}")


if __name__ == "__main__":
    main()
