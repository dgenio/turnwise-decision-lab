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
import math
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
    heavy_steps = [st for st in tr.get("steps", []) if st.get("generation") and st["generation"].get("status") == "ok"
                   and st["generation"].get("tier") == "heavy"]
    if tr.get("arm") == "heavy_agent":
        # The heavy-only agent sees its system prompt + native tool schemas on every call (served from the KV cache
        # after the first); that prefix is the cached part of its first call in each turn.
        first = next((st["generation"] for st in tr.get("steps", []) if st.get("generation")), {}) or {}
        schema_tokens = (first.get("cached_prompt_tokens") or 0) * len(heavy_steps)
    else:
        schema_tokens = sum(b.get("tokens", 0) for st in heavy_steps
                            for b in ((st.get("context") or {}).get("assembled") or {}).get("included", []) if b.get("id") == "tool_catalog")
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
        "unsafe_write_attempts": sum(1 for o in obs if o["status"] == "approval_required" and e["outcome"] != "approval"),
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
        "heavy_missed_evidence_gap": kind == "answer" and final_tier == "heavy" and not evidence_ok
                                     and tot.get("verification_requests", 0) == 0,
        "decision_calls": tot.get("decision_calls", 0),
        "decision_ms": tot.get("decision_latency_ms", 0.0),
        "decision_input_tokens": tot.get("decision_input_tokens", 0),
        "generation_prompt_tokens": tot.get("generation_prompt_tokens", 0),
        "generation_cached_prompt_tokens": tot.get("generation_cached_prompt_tokens", 0),
        "generation_completion_tokens": tot.get("generation_completion_tokens", 0),
        "heavy_tokens": sum((g.get("prompt_tokens") or 0) + (g.get("cached_prompt_tokens") or 0) + (g.get("completion_tokens") or 0)
                            for g in gens if g.get("tier") == "heavy"),
        "heavy_input_tokens": sum((g.get("prompt_tokens") or 0) + (g.get("cached_prompt_tokens") or 0) for g in gens if g.get("tier") == "heavy"),
        "heavy_schema_tokens": schema_tokens,
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
        "unsafe_write_attempts": tot("unsafe_write_attempts"),
        "tool_calls": tot("tool_calls"), "heavy_calls": tot("heavy_calls"), "light_calls": tot("light_calls"),
        "decision_calls": tot("decision_calls"), "under_provisioned": tot("under_provisioned"),
        "unnecessary_heavy_tasks": tot("unnecessary_heavy"), "escalations": tot("escalations"),
        "unnecessary_escalations": tot("unnecessary_escalation"),
        "verification_requests": tot("verification_requests"), "verification_recovered": tot("verification_recovered"),
        "heavy_missed_evidence_gaps": tot("heavy_missed_evidence_gap"),
        "decision_ms_total": round(tot("decision_ms"), 1), "decision_input_tokens": tot("decision_input_tokens"),
        "heavy_tokens": tot("heavy_tokens"),
        "generation_prompt_tokens": tot("generation_prompt_tokens"),
        "generation_cached_prompt_tokens": tot("generation_cached_prompt_tokens"),
        "generation_completion_tokens": tot("generation_completion_tokens"),
        "wall_ms_total": round(sum(wall), 1), "wall_ms_p50": _pct(wall, 0.5), "wall_ms_p95": _pct(wall, 0.95),
        "local_compute_s_per_success": round(sum(wall) / 1000 / len(ok), 2) if ok else None,
        "local_compute_s_per_task": round(sum(wall) / 1000 / n, 2) if n else None,
        "heavy_calls_per_task": round(tot("heavy_calls") / n, 2) if n else None,
        "heavy_input_tokens": tot("heavy_input_tokens"),
        "heavy_input_tokens_per_heavy_call": round(tot("heavy_input_tokens") / tot("heavy_calls"), 1) if tot("heavy_calls") else None,
        "heavy_schema_tokens_per_heavy_call": round(tot("heavy_schema_tokens") / tot("heavy_calls"), 1) if tot("heavy_calls") else None,
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


def repeat_runs(set_name: str, arms: list[str], ids: list[str], n: int) -> dict:
    """Latency variability and determinism check: the same scenario n times per arm."""
    scenarios = [s for s in load_scenarios(SETS[set_name]) if s["id"] in ids]
    rt = Runtime()
    cold = rt.warm()
    out = {"set": set_name, "n": n, "cold_start": cold, "runs": {}}
    for arm in arms:
        for s in scenarios:
            walls, finals = [], set()
            for _ in range(n):
                tr = run_arm(arm, s, rt)
                walls.append(tr["totals"]["wall_ms"])
                finals.add(tr["final"]["text"])
            out["runs"][f"{arm}/{s['id']}"] = {"wall_ms": walls, "min": min(walls), "max": max(walls),
                                               "median": statistics.median(walls), "identical_outputs": len(finals) == 1}
            print(arm, s["id"], walls, "identical" if len(finals) == 1 else "DIFFERENT outputs", flush=True)
    out["provenance"] = provenance(rt)
    (OUT / "repeats.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return out


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
            fails = [{"id": t["scenario_id"], "category": scen[t["scenario_id"]]["category"], "kind": sc["final_kind"],
                      "why": _failure_reason(sc, scen[t["scenario_id"]]["expect"]),
                      "text": (t["final"].get("text") or "").replace("\n", " ")[:160]}
                     for sc, t in zip(scored, data["traces"]) if not sc["success"]]
            sets[arm] = {"label": ARM_LABELS[arm], "summary": summarize(scored), "failures": fails,
                         "success_by_task": {t["scenario_id"]: sc["success"] for sc, t in zip(scored, data["traces"])},
                         "by_category": {c: summarize([sc for sc, t in zip(scored, data["traces"]) if scen[t["scenario_id"]]["category"] == c])
                                         for c in sorted({s["category"] for s in scen.values()})},
                         "provenance": data["provenance"]}
        out["sets"][set_name] = sets
    out["predictions"] = evaluate_predictions(out["sets"].get("heldout", {}))
    out["quality_constrained"] = quality_constrained(out["sets"].get("heldout", {}))
    out["post_freeze_changes"] = POST_FREEZE_CHANGES
    return out


def evaluate_predictions(sets: dict) -> list[dict]:
    """P1-P9 from docs/preregistration-v0.6.md, computed from the held-out summaries."""
    h = {a: v["summary"] for a, v in sets.items()}
    out = []

    def add(pid, claim, observed, ok, needs):
        missing = [a for a in needs if a not in h]
        out.append({"id": pid, "prediction": claim, "observed": observed if not missing else None,
                    "verdict": ("not evaluable (arm missing: " + ", ".join(missing) + ")") if missing else ("supported" if ok else "falsified")})

    g = lambda a, k: h.get(a, {}).get(k)
    if "heavy_agent" in h and "dm_dynamic" in h:
        gap = g("dm_dynamic", "successes") - g("heavy_agent", "successes")
        add("P1", "D success within 3 tasks of A", {"A": g("heavy_agent", "successes"), "D": g("dm_dynamic", "successes"), "D_minus_A": gap},
            abs(gap) <= 3, ["heavy_agent", "dm_dynamic"])
        red = 1 - g("dm_dynamic", "heavy_tokens") / max(1, g("heavy_agent", "heavy_tokens"))
        add("P2", "D uses >=50% fewer heavy-model tokens than A", {"A": g("heavy_agent", "heavy_tokens"), "D": g("dm_dynamic", "heavy_tokens"),
            "reduction": round(red, 3)}, red >= 0.5, ["heavy_agent", "dm_dynamic"])
        add("P3", "D p50 end-to-end latency lower than A", {"A_p50_ms": g("heavy_agent", "wall_ms_p50"), "D_p50_ms": g("dm_dynamic", "wall_ms_p50")},
            g("dm_dynamic", "wall_ms_p50") < g("heavy_agent", "wall_ms_p50"), ["heavy_agent", "dm_dynamic"])
    else:
        for pid in ("P1", "P2", "P3"):
            add(pid, "", None, False, ["heavy_agent", "dm_dynamic"])
    pairs = [("P4", "gen_chooser succeeds on >=4 fewer tasks than D", "gen_chooser", lambda d, x: d - x >= 4, "successes"),
             ("P5", "rules succeed within 3 tasks of D", "rules", lambda d, x: abs(d - x) <= 3, "successes"),
             ("P6", "dm_nogate has >= as many silent failures as D", "dm_nogate", lambda d, x: x >= d, "silent_failures")]
    for pid, claim, arm, test, key in pairs:
        if arm in h and "dm_dynamic" in h:
            add(pid, claim, {"D": g("dm_dynamic", key), arm: g(arm, key)}, test(g("dm_dynamic", key), g(arm, key)), [arm, "dm_dynamic"])
        else:
            add(pid, claim, None, False, [arm, "dm_dynamic"])
    if "dm_llm_args" in h and "dm_dynamic" in h:
        err = lambda a: g(a, "wrong_argument_calls") + g(a, "false_clarifications")
        add("P7", "dm_llm_args has >= wrong-argument calls + false clarifications than D", {"D": err("dm_dynamic"), "dm_llm_args": err("dm_llm_args")},
            err("dm_llm_args") >= err("dm_dynamic"), ["dm_llm_args", "dm_dynamic"])
    else:
        add("P7", "", None, False, ["dm_llm_args", "dm_dynamic"])
    if "dm_full" in h and "dm_dynamic" in h:
        okp = abs(g("dm_full", "successes") - g("dm_dynamic", "successes")) <= 3 and \
            g("dm_dynamic", "generation_prompt_tokens") < g("dm_full", "generation_prompt_tokens")
        add("P8", "E success within 3 of D, and D uses fewer generation prompt tokens than E",
            {"D_successes": g("dm_dynamic", "successes"), "E_successes": g("dm_full", "successes"),
             "D_prompt_tokens": g("dm_dynamic", "generation_prompt_tokens"), "E_prompt_tokens": g("dm_full", "generation_prompt_tokens")},
            okp, ["dm_full", "dm_dynamic"])
    else:
        add("P8", "", None, False, ["dm_full", "dm_dynamic"])
    writes = {a: g(a, "writes_executed") for a in h}
    add("P9", "0 writes executed in every arm", writes, all(v == 0 for v in writes.values()), list(h))
    return out


# ------------------------------------------- quality-constrained efficiency view
# Added after the held-out run, following docs/quality-constrained-efficiency-v06.md (merged in PR #4 after v0.6 was
# frozen). It re-reads the same traces and changes no score, success count or prediction verdict.
QCE_REFERENCE = "heavy_agent"
QCE_ARM_MAP = [
    ("A. Heavy-only reference", "heavy_agent", "ran; the heavy model is Qwen3.5-0.8B, not a strong frontier model"),
    ("B. Heavy-only, optimized context / native tool search", "-", "not run"),
    ("C. Simple host + heavy fallback", "rules", "approximation: deterministic rules pick verified data, light or heavy; no uncertainty fallback"),
    ("D. Decision service + heavy fallback", "dm_dynamic (dm_nogate without the fallback)",
     "local learned decision model with an escalation gate; no hosted decision service was called"),
    ("E. Light argument model + heavy fallback", "inside dm_dynamic's argument cascade; dm_llm_args is the LLM-only ablation",
     "partial: the light-argument step never triggered on the held-out set"),
    ("F. Joint bounded architecture", "dm_dynamic (dm_full removes the bounded-context lever)", "ran"),
]


def _wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return c - h, c + h


def paired_difference(x: list[bool], y: list[bool]) -> dict:
    """Success of x minus success of y on the same tasks: Newcombe (1998) method 10 score interval for paired
    proportions, and an exact two-sided McNemar test on the discordant pairs."""
    n = len(x)
    a = sum(1 for i, j in zip(x, y) if i and j)
    b = sum(1 for i, j in zip(x, y) if i and not j)
    c = sum(1 for i, j in zip(x, y) if j and not i)
    d = n - a - b - c
    p1, p2 = (a + b) / n, (a + c) / n
    l1, u1 = _wilson(a + b, n)
    l2, u2 = _wilson(a + c, n)
    den = (a + b) * (c + d) * (a + c) * (b + d)
    phi = (a * d - b * c) / math.sqrt(den) if den else 0.0
    lo = (p1 - p2) - math.sqrt(max(0.0, (p1 - l1) ** 2 - 2 * phi * (p1 - l1) * (u2 - p2) + (u2 - p2) ** 2))
    hi = (p1 - p2) + math.sqrt(max(0.0, (u1 - p1) ** 2 - 2 * phi * (u1 - p1) * (p2 - l2) + (p2 - l2) ** 2))
    m = b + c
    p_exact = min(1.0, 2 * sum(math.comb(m, k) for k in range(min(b, c) + 1)) / 2 ** m) if m else 1.0
    return {"tasks": n, "both": a, "only_candidate": b, "only_reference": c, "neither": d,
            "difference_pp": round((p1 - p2) * 100, 1), "ci95_pp": [round(lo * 100, 1), round(hi * 100, 1)],
            "mcnemar_exact_p": round(p_exact, 3)}


def quality_constrained(arms: dict) -> dict | None:
    if QCE_REFERENCE not in arms:
        return None
    ref = arms[QCE_REFERENCE]["success_by_task"]
    ids = sorted(ref)
    rows = []
    for arm in ARMS:
        if arm not in arms:
            continue
        s = arms[arm]["summary"]
        row = {"arm": arm, "successes": s["successes"], "tasks": s["tasks"], "executed_writes": s["writes_executed"],
               "dropped_actions": s["dropped_actions"], "silent_failures": s["silent_failures"],
               "local_compute_s_per_task": s["local_compute_s_per_task"], "local_compute_s_per_success": s["local_compute_s_per_success"],
               "wall_ms_p50": s["wall_ms_p50"], "wall_ms_p95": s["wall_ms_p95"], "heavy_calls_per_task": s["heavy_calls_per_task"],
               "heavy_input_tokens_per_heavy_call": s["heavy_input_tokens_per_heavy_call"],
               "heavy_schema_tokens_per_heavy_call": s["heavy_schema_tokens_per_heavy_call"]}
        if arm != QCE_REFERENCE:
            pdiff = paired_difference([arms[arm]["success_by_task"][i] for i in ids], [ref[i] for i in ids])
            row["vs_reference"] = pdiff
            row["margin_needed_pp"] = round(max(0.0, -pdiff["ci95_pp"][0]), 1)
            row["quality_gate"] = "inconclusive: no non-inferiority margin has been agreed"
        row["safety_gate"] = "pass: 0 executed writes" if s["writes_executed"] == 0 else "FAIL: executed writes"
        rows.append(row)
    return {"reference": QCE_REFERENCE, "rows": rows, "arm_map": [list(t) for t in QCE_ARM_MAP],
            "protocol": "docs/quality-constrained-efficiency-v06.md", "added_after_run": True}


def _qce_markdown(q: dict) -> list[str]:
    L = ["### Quality-constrained efficiency view (added after the run)", "",
         "This view follows [`docs/quality-constrained-efficiency-v06.md`](../../docs/quality-constrained-efficiency-v06.md), "
         "merged in PR #4 after v0.6 was frozen. It re-reads the same traces and changes no score, success count or prediction verdict. "
         "The reference is the heavy-only agent (A). The protocol asks for non-inferiority against it within a margin agreed in advance. "
         "No margin has been agreed, so **no arm passes the quality gate**. The table shows the margin each arm would need, "
         "i.e. how much worse than A its 95% interval still allows.", "",
         "Quality and safety gates (paired on the same 30 tasks):", "",
         "| Arm | Success | Difference vs A | 95% CI (paired, Newcombe) | Won / lost vs A | Exact McNemar p | Margin it would need | Executed writes | Dropped actions | Silent failures |",
         "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in q["rows"]:
        v = r.get("vs_reference")
        if v:
            L.append(f"| {r['arm']} | {r['successes']}/{r['tasks']} | {v['difference_pp']:+.1f} pp | {v['ci95_pp'][0]:+.1f} to {v['ci95_pp'][1]:+.1f} pp | "
                     f"{v['only_candidate']} / {v['only_reference']} | {v['mcnemar_exact_p']} | {r['margin_needed_pp']} pp | "
                     f"{r['executed_writes']} | {r['dropped_actions']} | {r['silent_failures']} |")
        else:
            L.append(f"| {r['arm']} (reference) | {r['successes']}/{r['tasks']} | - | - | - | - | - | {r['executed_writes']} | "
                     f"{r['dropped_actions']} | {r['silent_failures']} |")
    L += ["", "Efficiency (meaningful only once a quality gate passes). Cost is local CPU time, because no provider was billed:", "",
          "| Arm | Local compute per attempted task | p50 / p95 latency | Heavy calls per task | Heavy input tokens per heavy call | of which tool schemas | Local compute per resolved task (secondary) |",
          "|---|---:|---:|---:|---:|---:|---:|"]
    fmt = lambda v, suf="": "n/a" if v is None else f"{v:,}{suf}"
    for r in q["rows"]:
        L.append(f"| {r['arm']} | {r['local_compute_s_per_task']} s | {r['wall_ms_p50'] / 1000:.1f} s / {r['wall_ms_p95'] / 1000:.1f} s | "
                 f"{r['heavy_calls_per_task']} | {fmt(r['heavy_input_tokens_per_heavy_call'])} | {fmt(r['heavy_schema_tokens_per_heavy_call'])} | "
                 f"{fmt(r['local_compute_s_per_success'], ' s')} |")
    L += ["", "Tool-schema tokens: for the heavy-only agent, its system prompt plus native tool schemas. That prefix is in context on "
          "every call and is served from the KV cache after the first. For the other arms, it is the `tool_catalog` prompt block when "
          "the context step selected it.", "",
          "How the protocol's arms map onto what v0.6 ran (the letters are the protocol's, not v0.6's arm labels):", "",
          "| Protocol arm | v0.6 arm | Status |", "|---|---|---|"]
    L += [f"| {a} | {b} | {c} |" for a, b, c in q["arm_map"]]
    L.append("")
    return L


def render_markdown(r: dict) -> str:
    L = ["# v0.6 results: decision-driven control vs a heavy-only agent", "",
         "Generated by `python -m turnwise_lab.agent.bench --report` from the recorded traces in `reports/v06/traces/`.",
         "Pre-registration: [`docs/preregistration-v0.6.md`](../../docs/preregistration-v0.6.md). All inference was real and local "
         "(CPU, onnxruntime); no hosted provider was called, so `provider_cost_usd` is null everywhere.", "",
         "**Status: exploratory and inconclusive.** This is a bounded synthetic test with a 0.8B \"heavy\" model. "
         "[`audit.md`](audit.md) is a post-hoc reading of the same traces, added after the owner review. It covers full token accounting, "
         "including the controller's own scoring; why the escalation gate did not help; a failure taxonomy; and a blinded adjudication "
         "of the investigation answers.", ""]
    for set_name, arms in r["sets"].items():
        if not arms:
            continue
        title = "Held-out set (30 scenarios, independent author) - the evidence" if set_name == "heldout" else \
            "Development set (author-written; used for development and the demo, NOT evidence)"
        L += [f"## {title}", "",
              "| Arm | Success | Silent failures | Dropped actions | False clarifications | Wrong-arg calls | Heavy calls | Heavy tokens | Light calls | Decision calls | p50 / p95 latency | Local compute per success |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for arm in ARMS:
            if arm not in arms:
                continue
            s = arms[arm]["summary"]
            L.append(f"| {ARM_LABELS[arm]} | {s['successes']}/{s['tasks']} | {s['silent_failures']} | {s['dropped_actions']} | "
                     f"{s['false_clarifications']} | {s['wrong_argument_calls']} | {s['heavy_calls']} | {s['heavy_tokens']:,} | {s['light_calls']} | "
                     f"{s['decision_calls']} | {s['wall_ms_p50'] / 1000:.1f} s / {s['wall_ms_p95'] / 1000:.1f} s | "
                     f"{s['local_compute_s_per_success'] if s['local_compute_s_per_success'] is not None else 'n/a'} s |")
        L += ["", "Escalation and verification (decision-driven arms):", "",
              "| Arm | Unsafe write attempts (held) | Escalations | Unnecessary escalations | Verification requests | Recovered after request | Heavy answered despite missing evidence | Unnecessary heavy tasks | Under-provisioned |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for arm in ARMS:
            if arm in arms:
                s = arms[arm]["summary"]
                L.append(f"| {arm} | {s['unsafe_write_attempts']} | {s['escalations']} | {s['unnecessary_escalations']} | {s['verification_requests']} | "
                         f"{s['verification_recovered']} | {s['heavy_missed_evidence_gaps']} | {s['unnecessary_heavy_tasks']} | {s['under_provisioned']} |")
        cats = sorted({c for v in arms.values() for c in v["by_category"]})
        L += ["", "Success by category:", "", "| Category | " + " | ".join(a for a in ARMS if a in arms) + " |",
              "|---|" + "---:|" * sum(1 for a in ARMS if a in arms)]
        for c in cats:
            L.append(f"| {c} | " + " | ".join(f"{arms[a]['by_category'][c]['successes']}/{arms[a]['by_category'][c]['tasks']}"
                                               for a in ARMS if a in arms) + " |")
        L.append("")
        if set_name == "heldout" and r.get("predictions"):
            L += ["### Pre-registered predictions (verdicts computed by code)", "", "| ID | Prediction | Observed | Verdict |", "|---|---|---|---|"]
            for pr in r["predictions"]:
                L.append(f"| {pr['id']} | {pr['prediction']} | `{json.dumps(pr['observed'])}` | **{pr['verdict']}** |")
            L += ["", "P2 counts heavy *generation* tokens as pre-registered: new prompt, cache-reused prompt and completion. It does not count the "
                  "controller's own scoring on the same model. Counting the tokens the model actually computed, the decision-driven arm "
                  "processed more than the heavy-only agent; see [`audit.md`](audit.md) section 1. P1's \"within 3 tasks\" was a comparability "
                  "rule, not an agreed non-inferiority margin.", ""]
        if set_name == "heldout" and r.get("quality_constrained"):
            L += _qce_markdown(r["quality_constrained"])
        L += [f"### Every failure ({set_name})", ""]
        for arm in ARMS:
            if arm not in arms:
                continue
            L.append(f"**{arm}**")
            for f in arms[arm]["failures"]:
                L.append(f"- `{f['id']}` ({f['category']}): {f['why']}; final `{f['kind']}`: \u201c{f['text']}\u201d")
            if not arms[arm]["failures"]:
                L.append("- none")
            L.append("")
    L += ["## Not run", ""] + [f"- **{k}**: {v}" for k, v in r["arms_not_run"].items()]
    L += ["", "Post-freeze changes: " + ("; ".join(r.get("post_freeze_changes", [])) or "none") + ".", ""]
    return "\n".join(L)


def _failure_reason(sc: dict, e: dict) -> str:
    bits = []
    if sc["missing_facts"]:
        bits.append("missing evidence " + ", ".join(sc["missing_facts"]))
    if sc["dropped_action"]:
        bits.append("action request not raised")
    if sc["false_clarify"]:
        bits.append("clarified instead of answering")
    if sc["forbidden_requested"]:
        bits.append("requested a forbidden action")
    if e["outcome"] == "clarify" and sc["final_kind"] != "clarify":
        bits.append("should have clarified")
    if not bits:
        bits.append("answer failed the content check" if sc["final_kind"] in ("answer", "verified") else f"ended as {sc['final_kind']}")
    return "; ".join(bits)


POST_FREEZE_CHANGES: list[str] = [
    "Reporting-only metric added after the held-out run started: unsafe_write_attempts (side-effect requests made in tasks "
    "that did not ask for an action; all were held by the host). It does not change success or any prediction verdict.",
    "Reporting-only metric added after the held-out run: heavy_missed_evidence_gaps (the final answer came from the heavy "
    "model although required evidence was missing, and it did not use NEED_MORE_EVIDENCE). It does not change success.",
    "Stored scores in traces recorded before those additions lack the new fields; the report recomputes every score from the "
    "observations, so all arms are scored by the same code.",
    "Analysis added after the held-out run: the quality-constrained efficiency view (paired difference against the heavy-only "
    "agent with a Newcombe interval and an exact McNemar test, compute per attempted task, heavy input and tool-schema tokens "
    "per heavy call), following docs/quality-constrained-efficiency-v06.md from PR #4. It changes no score or verdict.",
]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--set", choices=list(SETS), default="dev")
    p.add_argument("--arms", default="heavy_agent,rules,dm_dynamic")
    p.add_argument("--only", help="comma-separated scenario ids")
    p.add_argument("--limit", type=int)
    p.add_argument("--report", action="store_true")
    p.add_argument("--repeat", type=int, help="repeat --only scenarios N times (latency variability)")
    a = p.parse_args()
    if a.repeat:
        repeat_runs(a.set, a.arms.split(","), a.only.split(","), a.repeat)
        return
    if a.report:
        r = report()
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "summary.json").write_text(json.dumps(r, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        (OUT / "summary.md").write_text(render_markdown(r), encoding="utf-8")
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
