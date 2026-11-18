"""Writes reports/v07/summary.{json,md} from the recorded traces (no model needed; CI regenerates and diffs it)."""
from __future__ import annotations

import json

from .bench import ARM_LABELS, ARMS, OUT, PAIRS, REFERENCE

CATS = ("investigation", "lookup", "action_request", "multi_turn", "ambiguous", "adverse", "smalltalk_general")


def _s(v, suffix=""):
    return "n/a" if v is None else f"{v}{suffix}"


def _main_table(block: dict) -> list[str]:
    L = ["| Arm | Success | Silent failures | Serious failures* | Dropped actions | One-sided causal claims | Replies with ungrounded values | "
         "Claims a side effect happened | Unrequested write attempts (all held) | Writes executed |",
         "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for a in ARMS:
        if a not in block["arms"]:
            continue
        s = block["arms"][a]["summary"]
        L.append(f"| `{a}` | **{s['successes']}/{s['tasks']}** | {s['silent_failures']} | {s['serious_failure']} | {s['dropped_actions']} | "
                 f"{s['one_sided_causal_claim']} | {s['tasks_with_ungrounded_values']} | {s['claims_side_effect']} | {s['unsafe_write_attempts']} | {s['writes_executed']} |")
    return L


def _cost_table(block: dict) -> list[str]:
    L = ["| Arm | Local compute per attempted task | p50 / p95 latency | Controller scoring | Context selection | Heavy generation | Light generation | "
         "Qwen3.5-0.8B tokens computed per task | Cache-reused tokens per task | Tool calls per task | Heavy calls per task | Gate interventions | Compute per success |",
         "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for a in ARMS:
        if a not in block["arms"]:
            continue
        s, acc = block["arms"][a]["summary"], block["arms"][a]["accounting"]
        t = acc["per_task_s"]
        L.append(f"| `{a}` | {t['total']} s | {s['wall_ms_p50'] / 1000:.1f} s / {s['wall_ms_p95'] / 1000:.1f} s | {t['controller']} s | {t['context_selection']} s | "
                 f"{t['heavy_generation']} s | {t['light_generation']} s | {acc['qwen35_tokens_computed_per_task']} | {acc['qwen35_cache_hit_tokens_per_task']} | "
                 f"{acc['calls_per_task']['tools']} | {acc['calls_per_task']['heavy']} | {s['gate_interventions']} | {_s(s['local_compute_s_per_success'], ' s')} |")
    return L


def _category_table(block: dict) -> list[str]:
    arms = [a for a in ARMS if a in block["arms"]]
    L = ["| Category | " + " | ".join(f"`{a}`" for a in arms) + " |", "|---|" + "---:|" * len(arms)]
    for c in CATS:
        cells = []
        for a in arms:
            s = block["arms"][a]["by_category"].get(c)
            cells.append(f"{s['successes']}/{s['tasks']}" if s else "-")
        if any(x != "-" for x in cells):
            L.append(f"| {c} | " + " | ".join(cells) + " |")
    return L


def _gate_table(block: dict) -> list[str]:
    L = ["| Controller | Success without → with gate | Difference | 95% CI (paired, Newcombe) | Gate fixed / gate broke | Exact McNemar p | "
         "Tasks free of serious failure, without → with | Difference (95% CI) |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for g in block.get("gate_effect", []):
        off, on = g["controller"], g["controller"] + "_gated"
        d, ds = g["success"], g["free_of_serious_failure"]
        so, sn = block["arms"][off]["summary"], block["arms"][on]["summary"]
        L.append(f"| `{off}` | {so['successes']} → {sn['successes']} | {d['difference_pp']:+.1f} pp | {d['ci95_pp'][0]:+.1f} to {d['ci95_pp'][1]:+.1f} pp | "
                 f"{d['only_candidate']} / {d['only_reference']} | {d['mcnemar_exact_p']} | {so['tasks'] - so['serious_failure']} → {sn['tasks'] - sn['serious_failure']} | "
                 f"{ds['difference_pp']:+.1f} pp ({ds['ci95_pp'][0]:+.1f} to {ds['ci95_pp'][1]:+.1f}) |")
    return L


def _reference_table(block: dict) -> list[str]:
    L = [f"| Arm | Difference vs `{REFERENCE}` | 95% CI (paired, Newcombe) | Won / lost | Exact McNemar p | Loss the interval still allows |",
         "|---|---:|---:|---:|---:|---:|"]
    for a in ARMS:
        v = block.get("vs_reference", {}).get(a)
        if v:
            L.append(f"| `{a}` | {v['difference_pp']:+.1f} pp | {v['ci95_pp'][0]:+.1f} to {v['ci95_pp'][1]:+.1f} pp | {v['only_candidate']} / {v['only_reference']} | "
                     f"{v['mcnemar_exact_p']} | {max(0.0, -v['ci95_pp'][0]):.1f} pp |")
    return L


def _sensitivity_table(block: dict) -> list[str]:
    t = block["tool_latency_sensitivity"]
    L = ["| Arm | " + " | ".join(f"{g} ms" for g in t["assumed_tool_latency_ms"]) + " |", "|---|" + "---:|" * len(t["assumed_tool_latency_ms"])]
    for a in ARMS:
        if a in t["per_task_s"]:
            L.append(f"| `{a}` | " + " | ".join(f"{v} s" for v in t["per_task_s"][a]) + " |")
    return L


def _failures(block: dict) -> list[str]:
    L = []
    for a in ARMS:
        if a not in block["arms"]:
            continue
        f = block["arms"][a]["failures"]
        L += [f"<details><summary><code>{a}</code>: {len(f)} failure(s)</summary>", "", "| Task | Category | Final | Why | Serious | Reply (first 200 characters) |", "|---|---|---|---|---|---|"]
        for x in f:
            L.append(f"| {x['id']} | {x['category']} | {x['kind']} | {x['why']} | {'yes' if x['serious'] else ''} | {x['text'].replace('|', '/')} |")
        L += ["", "</details>", ""]
    return L


def _set_section(name: str, block: dict, heading: str, note: str) -> list[str]:
    prov = next(iter(block["arms"].values()))["provenance"]
    L = [f"## {heading}", "", note, "",
         f"{block['tasks']} tasks, file sha256 `{block['task_file_sha256'][:16]}`. Recorded {prov['recorded_at_utc']} on {prov['cpu']} "
         f"({prov['cpu_threads']} threads, onnxruntime {prov['onnxruntime']}), code at `{(prov.get('git_commit_at_run') or '')[:8]}`. {prov['decoding']}.", "",
         "### Outcomes", ""] + _main_table(block) + [
        "", "\\*Serious failure: the reply claims a side effect happened, an action request was dropped, a cause is attributed on one-sided evidence, "
        "a forbidden call was requested, or a write executed. The same code audits every arm's final reply; for host-written replies the first and third are 0 by construction.",
        "", "### What the gate changes, per controller (paired on the same tasks)", ""] + _gate_table(block) + [
        "", f"### Every arm against the heavy-only agent (`{REFERENCE}`)", "",
        "No non-inferiority margin has been approved by the owner, so no arm passes or fails a quality gate here. The last column is the loss each interval still allows.", ""]
    L += _reference_table(block) + ["", "### Success by task family", ""] + _category_table(block)
    L += ["", "### Full cost ledger (per attempted task; everything a model computed is counted)", ""] + _cost_table(block)
    L += ["", "Controller scoring, context selection and heavy generation all run on the same Qwen3.5-0.8B weights; \"tokens computed\" sums them. "
              "Cache-reused tokens are the heavy agent's system prompt, tool schemas and the turn so far, served from the KV cache; a hosted provider bills them at a discount. "
              "Gate and planner steps compute no tokens. This is local CPU time, not provider cost; `provider_cost_usd` is null.",
          "", "### What if tools were not free?", "",
          "Local tools return in microseconds, which flatters any design that calls more of them. This recomputes compute per attempted task under an assumed latency per tool call.", ""]
    L += _sensitivity_table(block)
    c = block["arms"].get("contract")
    if c:
        s = c["summary"]
        L += ["", "### Contract planner routing", "",
              f"The host typed {s['tasks'] - s['delegated_to_agent']} of {s['tasks']} requests and delegated {s['delegated_to_agent']} to the gated heavy agent."]
        r = block.get("planner_routing")
        if r:
            L += ["", "| Route | Tasks | Successes | Typing matched the gold claim type |", "|---|---:|---:|---:|"]
            for k in ("planned", "delegate"):
                if k in r:
                    L.append(f"| {k} | {r[k]['tasks']} | {r[k]['successes']} | {_s(r[k].get('typing_matches_gold'))} |")
    L += ["", "### Every failure", ""] + _failures(block)
    return L


def markdown(rep: dict) -> str:
    L = ["# v0.7 exit-gate study", "",
         "Generated by `python -m turnwise_lab.v07.bench --report` from the recorded traces in `reports/v07/traces/`. "
         "CI regenerates this file and fails on any difference. CI does not re-run model inference.", "",
         "**Question.** Does it matter more *who chooses each step* (rules, a trained decision head, an LLM agent) or *whether the host checks the exit* "
         "against an evidence contract? Three v0.6 controllers run unchanged, each with and without the exit gate, plus a contract planner that asks no model to choose.", "",
         "**Scale.** Every model is the pinned v0.6 local stack. The \"heavy\" model is Qwen3.5-0.8B (q4). Nothing here is evidence about a capable agent.", ""]
    locked = rep["sets"].get("locked")
    if rep.get("freeze"):
        f = rep["freeze"]
        L += [f"**Freeze.** Code, scorer, predictions and the locked task file were frozen at `{f.get('frozen_at_commit', 'see docs/v07-freeze.json')}` "
              f"before any arm ran on the locked set ([`docs/preregistration-v0.7.md`](../../docs/preregistration-v0.7.md), [`docs/v07-freeze.json`](../../docs/v07-freeze.json)).", ""]
    if rep.get("predictions"):
        L += ["## Pre-registered predictions (verdicts computed by code)", "", "| ID | Prediction | Observed | Verdict |", "|---|---|---|---|"]
        for p in rep["predictions"]:
            L.append(f"| {p['id']} | {p['prediction']} | {json.dumps(p['observed']) if p['observed'] is not None else '-'} | **{p['verdict']}** |")
        L.append("")
    if locked:
        L += _set_section("locked", locked, "Locked set (the evidence)",
                          "Written by an independent LLM author from the task specification and the world dump only. Not read by the implementer before the freeze.")
    dev = rep["sets"].get("dev")
    if dev:
        L += ["", "---", ""] + _set_section("dev", dev, "Development set (not evidence)",
                                           "Written by a second independent LLM author. The claim lexicon, the contract rules and the gate were developed against "
                                           "these tasks and the v0.6 sets, so these numbers are optimistic for anything the implementer could tune.")
    return "\n".join(L) + "\n"


def write(rep: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.json").write_text(json.dumps(rep, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    (OUT / "summary.md").write_text(markdown(rep), encoding="utf-8")
    for name, block in rep["sets"].items():
        print(f"== {name} ({block['tasks']} tasks)")
        for a in ARMS:
            if a in block["arms"]:
                s = block["arms"][a]["summary"]
                print(f"  {a:20} {s['successes']:>2}/{s['tasks']} silent={s['silent_failures']:>2} serious={s['serious_failure']:>2} dropped={s['dropped_actions']} "
                      f"tools={s['tool_calls']:>3} heavy={s['heavy_calls']:>3} gate={s['gate_interventions']:>2} s/task={s['local_compute_s_per_task']} p95={s['wall_ms_p95']}")
