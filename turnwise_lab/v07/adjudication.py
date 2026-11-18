"""Blinded adjudication of the locked investigations (secondary outcome; the lexical check is known to be lenient).

    python -m turnwise_lab.v07.adjudication --packet     # writes reports/v07/adjudication/{packet.json,packet.md,key.json}
    python -m turnwise_lab.v07.adjudication --merge      # merges grades_*.json with the key into adjudication.{json,md}

The rubric is docs/v06-adjudication-rubric.md, unchanged. Each grader receives only the rubric and the packet. Two
graders grade independently; disagreements are reported, never resolved by the implementer.
"""
from __future__ import annotations

from pathlib import Path
import argparse
import hashlib
import json

from ..agent.host import Host
from ..agent.contracts import Decision
from ..agent.render import render_facts
from .bench import OUT, score, trace_path
from .evidence import BY_KIND
from .tasks import SETS, load_tasks
from .world import StudyWorld

ADJ = OUT / "adjudication"
ADJ_ARMS = ("heavy_agent", "heavy_agent_gated", "dm_dynamic", "contract", "contract_narrated")
FIELDS = ("outcome", "causal_claim", "severity", "acknowledges_missing_evidence", "action_handling", "rationale")
ORDER = {"correct": 0, "partial": 1, "incorrect": 2}


def reference_facts(task: dict) -> list[str]:
    """Ground truth for the task's required facts, read from the same deterministic world (after any transient failure)."""
    out = []
    for f in task["expect"]["required_facts"]:
        kind, _, ent = f.partition(":")
        if kind == "doc":
            from ..agent.world import DOCS
            d = next(d for d in DOCS if d.id == ent)
            out.append(f"[{f}] {d.title}: {d.body}")
            continue
        host = Host(StudyWorld(task["world_variant"]))
        d = Decision("call_workflow" if kind == "smoke" else "call_tool", BY_KIND[kind].capability, {"service": ent})
        o = host.execute(d, step_index=0, call_id="ref", user_text="")
        if o.status != "ok":
            o = host.execute(d, step_index=1, call_id="ref2", user_text="")
        out.append(render_facts(o.facts))
    return out


def build_packet() -> tuple[dict, dict]:
    tasks = [t for t in load_tasks(SETS["locked"]) if t["category"] == "investigation"]
    traces = {a: {t["scenario_id"]: t for t in json.loads(trace_path("locked", a).read_text())["traces"]} for a in ADJ_ARMS}
    rows = []
    for t in tasks:
        for a in ADJ_ARMS:
            tr = traces[a][t["id"]]
            gathered = [render_facts(o["facts"]) for o in tr["observations"] if o["status"] == "ok" and o["facts"]]
            rows.append({"scenario": t["id"], "arm": a, "request": t["message"], "earlier_conversation": t["conversation"],
                         "expected_kind_of_reply": t["expect"]["outcome"], "what_a_good_reply_does": t["expect"]["reference_answer"],
                         "reference_facts": reference_facts(t), "evidence_the_system_gathered": gathered,
                         "approval_requests_raised": [f"{o['target']}({o['arguments'].get('service', '')})" for o in tr["observations"] if o["status"] == "approval_required"],
                         "final_reply_kind": tr["final"].get("kind"), "final_reply": (tr["final"].get("text") or "")[:2400]})
    rows.sort(key=lambda r: hashlib.sha256(f"v07|{r['scenario']}|{r['arm']}".encode()).hexdigest())
    key = {}
    for i, r in enumerate(rows):
        r["item"] = f"K{i + 1:03d}"
        key[r["item"]] = {"scenario": r.pop("scenario"), "arm": r.pop("arm")}
    return {"rubric": "docs/v06-adjudication-rubric.md", "items": rows}, key


def packet_markdown(packet: dict) -> str:
    L = ["# v0.7 blinded adjudication packet (locked investigations)", "",
         "Grade each item with the rubric in `docs/v06-adjudication-rubric.md`. Items are shuffled and carry no system name.", ""]
    for it in packet["items"]:
        L += [f"## {it['item']}", "", f"**Request:** {it['request']}"]
        L += [f"- earlier {m['role']}: {m['content']}" for m in it["earlier_conversation"]]
        L += ["", f"**Expected kind of reply:** {it['expected_kind_of_reply']}", f"**What a good reply does:** {it['what_a_good_reply_does']}", "",
              "**Reference facts (ground truth):**"] + [f"- {x}" for x in it["reference_facts"] or ["(none required)"]]
        L += ["", "**Evidence the system gathered:**"] + [f"- {x}" for x in it["evidence_the_system_gathered"] or ["(none)"]]
        L += ["", "**Approval requests raised:** " + (", ".join(it["approval_requests_raised"]) or "none"),
              f"**Final reply kind:** {it['final_reply_kind']}", "", "```text", it["final_reply"], "```", ""]
    return "\n".join(L)


def merge() -> dict | None:
    kp = ADJ / "key.json"
    graders = sorted(ADJ.glob("grades_*.json"))
    if not kp.exists() or not graders:
        return None
    key = json.loads(kp.read_text())
    tasks = {t["id"]: t for t in load_tasks(SETS["locked"])}
    frozen = {}
    for a in ADJ_ARMS:
        for t in json.loads(trace_path("locked", a).read_text())["traces"]:
            frozen[(t["scenario_id"], a)] = score(tasks[t["scenario_id"]], t)["success"]
    grades = {p.stem.split("_", 1)[1]: {g["item"]: g for g in json.loads(p.read_text())["grades"]} for p in graders}
    who = {p.stem.split("_", 1)[1]: json.loads(p.read_text()).get("adjudicator", "") for p in graders}
    rows = []
    for item, k in sorted(key.items(), key=lambda kv: (kv[1]["scenario"], ADJ_ARMS.index(kv[1]["arm"]))):
        row = {"item": item, **k, "frozen_success": frozen[(k["scenario"], k["arm"])], "grades": {n: {f: g.get(item, {}).get(f) for f in FIELDS} for n, g in grades.items()}}
        outs = [row["grades"][n]["outcome"] for n in grades]
        row["agree_outcome"] = len(set(outs)) == 1
        row["consensus_outcome"] = max(outs, key=lambda o: ORDER.get(o, 2))  # disagreement resolves to the more severe grade (rubric rule 4)
        sev = ["none", "minor", "major", "critical"]
        row["consensus_severity"] = max((row["grades"][n]["severity"] for n in grades), key=lambda s: sev.index(s) if s in sev else 3)
        rows.append(row)
    per_arm = {}
    for a in ADJ_ARMS:
        rs = [r for r in rows if r["arm"] == a]
        per_arm[a] = {"items": len(rs), **{o: sum(1 for r in rs if r["consensus_outcome"] == o) for o in ORDER},
                      "by_grader": {n: {o: sum(1 for r in rs if r["grades"][n]["outcome"] == o) for o in ORDER} for n in grades},
                      "unsupported_or_contradicted_causal_claims": {n: sum(1 for r in rs if r["grades"][n]["causal_claim"] in ("unsupported", "contradicted")) for n in grades},
                      "major_or_critical": sum(1 for r in rs if r["consensus_severity"] in ("major", "critical")),
                      "frozen_passes": sum(1 for r in rs if r["frozen_success"]),
                      "frozen_passes_judged_correct": sum(1 for r in rs if r["frozen_success"] and r["consensus_outcome"] == "correct")}
    n_agree = sum(1 for r in rows if r["agree_outcome"])
    return {"graders": who, "items": len(rows), "outcome_agreement": {"agree": n_agree, "of": len(rows)}, "per_arm": per_arm, "rows": rows,
            "consensus_rule": "when the graders differ, the more severe grade is used (rubric rule 4); both grades are kept"}


def merged_markdown(m: dict) -> str:
    names = list(m["graders"])
    L = ["# v0.7 blinded adjudication of the locked investigations", "",
         "Generated by `python -m turnwise_lab.v07.adjudication --merge`. Secondary outcome: it changes no frozen score.", "",
         "Graders (each saw only the rubric and the shuffled packet, never the key, the traces or each other's grades):", ""]
    L += [f"- **{n}**: {m['graders'][n]}" for n in names]
    a = m["outcome_agreement"]
    L += ["", f"The graders agreed on the outcome of {a['agree']} of {a['of']} items. {m['consensus_rule'].capitalize()}.", "",
          "| Arm | Items | Correct | Partial | Incorrect | Major or critical | Unsupported or contradicted causal claims (" + " / ".join(names) + ") | Frozen-check passes judged correct |",
          "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for arm, p in m["per_arm"].items():
        L.append(f"| `{arm}` | {p['items']} | {p['correct']} | {p['partial']} | {p['incorrect']} | {p['major_or_critical']} | "
                 f"{' / '.join(str(p['unsupported_or_contradicted_causal_claims'][n]) for n in names)} | {p['frozen_passes_judged_correct']} of {p['frozen_passes']} |")
    L += ["", "Per grader (correct / partial / incorrect):", "", "| Arm | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for arm, p in m["per_arm"].items():
        L.append(f"| `{arm}` | " + " | ".join(f"{p['by_grader'][n]['correct']} / {p['by_grader'][n]['partial']} / {p['by_grader'][n]['incorrect']}" for n in names) + " |")
    L += ["", "## Every item", "", "| Task | Arm | Frozen check | " + " | ".join(f"{n}: outcome, claim, severity" for n in names) + " | Rationale (first grader) |",
          "|---|---|---|" + "---|" * len(names) + "---|"]
    for r in m["rows"]:
        g = r["grades"]
        L.append(f"| {r['scenario']} | `{r['arm']}` | {'pass' if r['frozen_success'] else 'fail'} | "
                 + " | ".join(f"{g[n]['outcome']}, {g[n]['causal_claim']}, {g[n]['severity']}" for n in names)
                 + f" | {(g[names[0]]['rationale'] or '').replace('|', '/')} |")
    return "\n".join(L) + "\n"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--packet", action="store_true")
    p.add_argument("--merge", action="store_true")
    args = p.parse_args()
    if not all(trace_path("locked", a).exists() for a in ADJ_ARMS):
        print("locked traces not recorded yet: nothing to adjudicate")
        return
    ADJ.mkdir(parents=True, exist_ok=True)
    if args.packet:
        packet, key = build_packet()
        (ADJ / "packet.json").write_text(json.dumps(packet, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        (ADJ / "packet.md").write_text(packet_markdown(packet), encoding="utf-8")
        (ADJ / "key.json").write_text(json.dumps(key, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {len(packet['items'])} items")
    if args.merge:
        m = merge()
        if m is None:
            print("no grades yet: packet only")
            return
        (ADJ / "adjudication.json").write_text(json.dumps(m, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        (ADJ / "adjudication.md").write_text(merged_markdown(m), encoding="utf-8")
        print(json.dumps({a: {k: v for k, v in p.items() if k in ORDER} for a, p in m["per_arm"].items()}))


if __name__ == "__main__":
    main()
