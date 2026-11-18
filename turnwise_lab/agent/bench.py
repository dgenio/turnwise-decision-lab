"""v0.6 paired benchmark: same scenarios, same world, same tools, same heavy model.

    python -m turnwise_lab.agent.bench --set dev --arms heavy_agent,rules,dm_dynamic
    python -m turnwise_lab.agent.bench --set heldout --arms all
    python -m turnwise_lab.agent.bench --report            # rebuild summaries from recorded traces (no models)

Running arms needs the local models (scripts/fetch_models.py). Recorded traces
are committed; `--report` and CI rebuild every summary from them offline.
Outcome scoring never looks at routing decisions, only at what each turn did.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import argparse
import hashlib
import json
import platform
import statistics
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SETS = {"dev": ROOT / "fixtures" / "v06_dev.json", "heldout": ROOT / "fixtures" / "v06_heldout.json"}
OUT = ROOT / "reports" / "v06"
ARMS = ("heavy_agent", "rules", "dm_dynamic", "dm_full", "dm_nogate", "dm_llm_args", "gen_chooser")
ARM_LABELS = {
    "heavy_agent": "A. Heavy-only agent (native tool calling) - primary baseline",
    "rules": "Deterministic host policy (rules) + heuristic context",
    "dm_dynamic": "D. turnwise-dm controller + dynamic prompt blocks",
    "dm_full": "E. turnwise-dm controller + full permitted context (ablation)",
    "dm_nogate": "Ablation: turnwise-dm without conservative escalation",
    "dm_llm_args": "Ablation: turnwise-dm with LLM-only argument construction",
    "gen_chooser": "D'. Small-LLM controller (Qwen3.5-0.8B constrained choice) + dynamic blocks",
}
NOT_RUN = {"B. OpenAI Decisions controller": "adapter implemented and tested against a fake server; no credentials or approved spend",
           "C. Jev / System One controller": "adapter implemented and tested against a fake server; no credentials or approved spend"}


def load_scenarios(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out, seen = [], set()
    for s in data["scenarios"]:
        e = s["expect"]
        if s["id"] in seen:
            raise ValueError(f"duplicate id {s['id']}")
        seen.add(s["id"])
        if e["outcome"] not in ("answer", "clarify", "approval"):
            raise ValueError(f"{s['id']}: bad outcome")
        if e.get("min_tier") not in ("none", "light", "heavy"):
            raise ValueError(f"{s['id']}: bad min_tier")
        for f in e.get("required_facts", []):
            if f.split(":")[0] not in ("health", "errors", "deploys", "config", "owner", "smoke", "doc"):
                raise ValueError(f"{s['id']}: unknown fact key {f}")
        out.append(s)
    return out


# ------------------------------------------------------------------ scoring
def _text_ok(text: str, must: list, must_not: list) -> bool:
    t = (text or "").lower()
    return all(any(term.lower() in t for term in group) for group in must) and not any(m.lower() in t for m in must_not)


def score(s: dict, tr: dict) -> dict:
    e = s["expect"]
    final = tr.get("final", {})
    kind, text = final.get("kind"), final.get("text") or ""
    obs = tr.get("observations", [])
    gathered = {k for o in obs if o["status"] == "ok" for k in o["facts"]}
    calls = [o for o in obs if o["operation"] in ("call_tool", "call_workflow")]
    approvals = {(o["target"], o["arguments"].get("service")) for o in obs if o["status"] == "approval_required"}
    relevant = {f.split(":", 1)[1] for f in e.get("required_facts", []) if not f.startswith("doc:")}
    if e.get("approval_service"):
        relevant.add(e["approval_service"])
    wrong_arg = [o for o in calls if relevant and o["arguments"].get("service") and o["arguments"]["service"] not in relevant]
    rejected = [o for o in obs if o["status"] == "rejected"]
    forbidden = [o for o in calls if o["target"] in e.get("forbidden_calls", [])]
    writes = tr.get("totals", {}).get("writes_executed", 0)
    evidence_ok = set(e.get("required_facts", [])) <= gathered
    is_question = "?" in text and len(text) < 400
    if e["outcome"] == "answer":
        success = kind in ("answer", "verified") and evidence_ok and _text_ok(text, e.get("answer_must_include", []),
                                                                              e.get("answer_must_not_include", []))
    elif e["outcome"] == "clarify":
        success = kind == "clarify" or (kind == "answer" and is_question and not calls)
    else:
        success = (e["approval_target"], e.get("approval_service")) in approvals or (
            e.get("approval_service") is None and any(t == e["approval_target"] for t, _ in approvals))
        success = success and _text_ok(text, [], e.get("answer_must_not_include", []))
    success = success and not forbidden and writes == 0
    gens = [st["generation"] for st in tr.get("steps", []) if st.get("generation") and st["generation"].get("status") == "ok"]
    heavy_calls = sum(1 for g in gens if g.get("tier") == "heavy")
    final_tier = "none" if kind == "verified" else (gens[-1]["tier"] if gens and kind == "answer" else "none")
    tot = tr.get("totals", {})
    return {
        "success": bool(success),
        "final_kind": kind,
        "evidence_ok": evidence_ok,
        "missing_facts": sorted(set(e.get("required_facts", [])) - gathered),
        "silent_failure": (not success) and kind in ("answer", "verified"),
        "dropped_action": e["outcome"] == "approval" and not approvals,
        "false_clarify": e["outcome"] != "clarify" and kind == "clarify",
        "wrong_argument_calls": len(wrong_arg),
        "rejected_proposals": len(rejected),
        "forbidden_requested": len(forbidden),
        "writes_executed": writes,
        "tool_calls": tot.get("tool_calls", 0),
        "heavy_calls": heavy_calls,
        "light_calls": sum(1 for g in gens if g.get("tier") == "light"),
        "under_provisioned": e.get("min_tier") == "heavy" and kind == "answer" and final_tier != "heavy" or
                             (e.get("min_tier") == "heavy" and kind == "verified"),
        "unnecessary_heavy": e.get("min_tier") in ("none", "light") and heavy_calls > 0,
        "escalations": tot.get("escalations", 0),
        "unnecessary_escalation": tot.get("escalations", 0) > 0 and e.get("min_tier") != "heavy",
        "verification_requests": tot.get("verification_requests", 0),
        "verification_recovered": tot.get("verification_requests", 0) > 0 and bool(success),
        "decision_calls": tot.get("decision_calls", 0),
        "decision_ms": tot.get("decision_latency_ms", 0.0),
        "decision_input_tokens": tot.get("decision_input_tokens", 0),
        "generation_prompt_tokens": tot.get("generation_prompt_tokens", 0),
        "generation_cached_prompt_tokens": tot.get("generation_cached_prompt_tokens", 0),
        "generation_completion_tokens": tot.get("generation_completion_tokens", 0),
        "heavy_tokens": sum((g.get("prompt_tokens") or 0) + (g.get("cached_prompt_tokens") or 0) + (g.get("completion_tokens") or 0)
                            for g in gens if g.get("tier") == "heavy"),
        "wall_ms": tot.get("wall_ms", 0.0),
    }


def _pct(vals, q):
    s = sorted(vals)
    return round(s[min(len(s) - 1, int(round((len(s) - 1) * q)))], 1) if s else None


def summarize(scored: list[dict]) -> dict:
    n = len(scored)
    ok = [x for x in scored if x["success"]]
    tot = lambda k: sum(x[k] for x in scored)
    wall = [x["wall_ms"] for x in scored]
    return {
        "tasks": n, "successes": len(ok), "success_rate": round(len(ok) / n, 3) if n else None,
        "silent_failures": tot("silent_failure"), "dropped_actions": tot("dropped_action"), "false_clarifications": tot("false_clarify"),
        "wrong_argument_calls": tot("wrong_argument_calls"), "rejected_proposals": tot("rejected_proposals"),
        "forbidden_requested": tot("forbidden_requested"), "writes_executed": tot("writes_executed"),
        "tool_calls": tot("tool_calls"), "heavy_calls": tot("heavy_calls"), "light_calls": tot("light_calls"),
        "decision_calls": tot("decision_calls"), "under_provisioned": tot("under_provisioned"),
        "unnecessary_heavy_tasks": tot("unnecessary_heavy"), "escalations": tot("escalations"),
        "unnecessary_escalations": tot("unnecessary_escalation"),
        "verification_requests": tot("verification_requests"), "verification_recovered": tot("verification_recovered"),
        "decision_ms_total": round(tot("decision_ms"), 1), "decision_input_tokens": tot("decision_input_tokens"),
        "heavy_tokens": tot("heavy_tokens"),
        "generation_prompt_tokens": tot("generation_prompt_tokens"),
        "generation_cached_prompt_tokens": tot("generation_cached_prompt_tokens"),
        "generation_completion_tokens": tot("generation_completion_tokens"),
        "wall_ms_total": round(sum(wall), 1), "wall_ms_p50": _pct(wall, 0.5), "wall_ms_p95": _pct(wall, 0.95),
        "local_compute_s_per_success": round(sum(wall) / 1000 / len(ok), 2) if ok else None,
        "heavy_tokens_per_success": round(tot("heavy_tokens") / len(ok), 1) if ok else None,
        "provider_cost_usd": None,
    }


# ------------------------------------------------------------------ running
class Runtime:
    """Lazily loads local models (only when an arm actually needs them)."""

    def __init__(self):
        self._c = {}

    def _get(self, key, fn):
        if key not in self._c:
            self._c[key] = fn()
        return self._c[key]

    @property
    def dm_lm(self):
        from ..local_models import LocalLM
        return self._get("dm_lm", lambda: LocalLM("qwen3.5-0.8b-q4"))

    @property
    def light(self):
        from ..local_models import LocalLM
        return self._get("light", lambda: LocalLM("qwen2.5-0.5b-instruct-int8"))

    @property
    def heavy(self):
        # Heavy tier = the strongest reasoner within the download budget (measured; see docs/v06-models.md).
        return self._get("heavy", lambda: self.dm_lm)

    def warm(self) -> dict:
        """Fill static prefixes once (cold start reported separately, not charged to any turn)."""
        import time as _t
        from .heavy_agent import warm_prefix
        from .host import Host
        from .world import IncidentWorld
        t0 = _t.perf_counter()
        self.chooser._prefix_state()
        out = {"chooser_prefix_fill_ms": round((_t.perf_counter() - t0) * 1000, 1)}
        out["heavy_agent_prefix_fill_ms"] = warm_prefix(Host(IncidentWorld()), self.heavy)
        return out

    @property
    def s1(self):
        from ..local_models import S1Router
        return self._get("s1", S1Router)

    @property
    def chooser(self):
        from .providers import GenerativeChooser
        return self._get("chooser", lambda: GenerativeChooser(self.dm_lm))

    @property
    def head(self):
        return self._get("head", lambda: json.loads((ROOT / "models" / "turnwise-dm-head.json").read_text()))


def provenance(rt: Runtime) -> dict:
    import onnxruntime
    cpu = next((l.split(":", 1)[1].strip() for l in Path("/proc/cpuinfo").read_text().splitlines() if l.startswith("model name")), platform.processor())
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    except Exception:
        commit = None
    models = {}
    for k in ("dm_lm", "light", "s1"):
        if k in rt._c:
            m = rt._c[k]
            models[k] = {"version": m.version, "graph_fingerprint": getattr(m, "graph_fingerprint", None)}
    models["roles"] = {"decision chooser + heavy tier + heavy-only agent": "dm_lm", "light tier": "light", "fixed-head classifier": "s1"}
    head = ROOT / "models" / "turnwise-dm-head.json"
    return {"recorded_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "cpu": cpu,
            "cpu_threads": 4, "onnxruntime": onnxruntime.__version__, "python": platform.python_version(),
            "git_commit_at_run": commit, "models": models,
            "decision_head_sha256": hashlib.sha256(head.read_bytes()).hexdigest() if head.exists() else None,
            "decoding": "greedy (no sampling): repeated runs give identical outputs; only latency varies",
            "where": "local CPU inside the development container; not a hosted provider"}


def run_arm(arm: str, s: dict, rt: Runtime) -> dict:
    from .heavy_agent import run_heavy_agent
    from .host import Host
    from .loop import execute_user_turn
    from .providers import (ArgumentBuilder, HeuristicDecider, LearnedDecider, LocalGenerator, LocalLMContextSelector,
                            LocalLMDecider, RuleContextSelector)
    from .world import IncidentWorld
    host = Host(IncidentWorld(s["world_variant"]))
    convo = s.get("conversation", [])
    if arm == "heavy_agent":
        return run_heavy_agent(s["message"], host=host, lm=rt.heavy, turn_id=s["id"], conversation=convo).as_json()
    gen = LocalGenerator(rt.light, rt.heavy)
    if arm == "rules":
        return execute_user_turn(s["message"], host=host, decider=HeuristicDecider(), context=RuleContextSelector("heuristic"),
                                 generator=gen, turn_id=s["id"], arm=arm, conversation=convo).as_json()
    args = ArgumentBuilder(rt.light, rt.heavy, deterministic=(arm != "dm_llm_args"))
    if arm == "gen_chooser":
        decider = LocalLMDecider(rt.chooser, args)
    else:
        decider = LearnedDecider(rt.head, rt.chooser, rt.s1, args, gate=0.0 if arm == "dm_nogate" else None)
    ctx = RuleContextSelector("full") if arm == "dm_full" else LocalLMContextSelector(rt.dm_lm)
    return execute_user_turn(s["message"], host=host, decider=decider, context=ctx, generator=gen, turn_id=s["id"], arm=arm,
                             conversation=convo, verification=True).as_json()


def trace_path(set_name: str, arm: str) -> Path:
    return OUT / "traces" / set_name / f"{arm}.json"


def run(set_name: str, arms: list[str], limit: int | None = None, only: list[str] | None = None) -> None:
    scenarios = load_scenarios(SETS[set_name])
    if only:
        scenarios = [s for s in scenarios if s["id"] in only]
    if limit:
        scenarios = scenarios[:limit]
    rt = Runtime()
    cold = rt.warm()
    for arm in arms:
        path = trace_path(set_name, arm)
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = json.loads(path.read_text()) if path.exists() else {"traces": []}
        by_id = {t["scenario_id"]: t for t in existing["traces"]}
        for s in scenarios:
            tr = run_arm(arm, s, rt)
            tr["scenario_id"] = s["id"]
            tr["score"] = score(s, tr)
            by_id[s["id"]] = tr
            sc = tr["score"]
            print(f"[{set_name}][{arm}] {s['id']:<18} success={sc['success']!s:<5} kind={sc['final_kind']:<17} "
                  f"tools={sc['tool_calls']} heavy={sc['heavy_calls']} light={sc['light_calls']} dec={sc['decision_calls']} "
                  f"wall={sc['wall_ms'] / 1000:.1f}s missing={sc['missing_facts']}", flush=True)
            order = [x["id"] for x in load_scenarios(SETS[set_name])]
            payload = {"set": set_name, "arm": arm, "label": ARM_LABELS[arm], "provenance": {**provenance(rt), "cold_start": cold},
                       "traces": [by_id[i] for i in order if i in by_id]}
            path.write_text(json.dumps(payload, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def report() -> dict:
    out = {"arms_not_run": NOT_RUN, "sets": {}}
    for set_name, spath in SETS.items():
        if not spath.exists():
            continue
        scen = {s["id"]: s for s in load_scenarios(spath)}
        sets = {}
        for arm in ARMS:
            p = trace_path(set_name, arm)
            if not p.exists():
                continue
            data = json.loads(p.read_text())
            scored = [score(scen[t["scenario_id"]], t) for t in data["traces"] if t["scenario_id"] in scen]
            if len(scored) != len(scen):
                continue  # only complete arms are reported
            sets[arm] = {"label": ARM_LABELS[arm], "summary": summarize(scored),
                         "by_category": {c: summarize([sc for sc, t in zip(scored, data["traces"]) if scen[t["scenario_id"]]["category"] == c])
                                         for c in sorted({s["category"] for s in scen.values()})},
                         "provenance": data["provenance"]}
        out["sets"][set_name] = sets
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--set", choices=list(SETS), default="dev")
    p.add_argument("--arms", default="heavy_agent,rules,dm_dynamic")
    p.add_argument("--only", help="comma-separated scenario ids")
    p.add_argument("--limit", type=int)
    p.add_argument("--report", action="store_true")
    a = p.parse_args()
    if a.report:
        r = report()
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "summary.json").write_text(json.dumps(r, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        for set_name, arms in r["sets"].items():
            for arm, v in arms.items():
                s = v["summary"]
                print(f"[{set_name}] {arm:<13} success {s['successes']}/{s['tasks']}  silent {s['silent_failures']}  heavy calls "
                      f"{s['heavy_calls']}  p50 {s['wall_ms_p50']} ms  compute/success {s['local_compute_s_per_success']} s")
        return
    arms = list(ARMS) if a.arms == "all" else a.arms.split(",")
    run(a.set, arms, a.limit, a.only.split(",") if a.only else None)


if __name__ == "__main__":
    main()
