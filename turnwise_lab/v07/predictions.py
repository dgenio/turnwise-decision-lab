"""Pre-registered predictions for the v0.7 locked run (docs/preregistration-v0.7.md). Verdicts are computed by code.

Frozen with the study (docs/v07-freeze.json). A prediction is ``supported`` or ``falsified``; nothing here is tuned
after the locked run. Thresholds are in tasks, not percentages, because the locked set has 60 tasks.
"""
from __future__ import annotations

CONTROLLERS = ("heavy_agent", "rules", "dm_dynamic")


def _evidence_missing_exits(arm: dict) -> int:
    """Turns that ended with a reply (generated or verified data) while gold-required evidence was missing."""
    return sum(1 for f in arm["failures"] if f["kind"] in ("answer", "verified") and "missing evidence" in f["why"])


def evaluate(locked: dict | None) -> list[dict]:
    if not locked:
        return []
    arms = locked["arms"]
    need = [c for c in CONTROLLERS] + [c + "_gated" for c in CONTROLLERS] + ["contract", "contract_narrated"]
    missing = [a for a in need if a not in arms]
    if missing:
        return [{"id": "-", "prediction": "all eight arms complete", "observed": {"missing": missing}, "verdict": "not evaluable"}]
    S = {a: arms[a]["summary"] for a in arms}
    ok = lambda a: S[a]["successes"]
    out = []

    def add(pid, claim, observed, supported):
        out.append({"id": pid, "prediction": claim, "observed": observed, "verdict": "supported" if supported else "falsified"})

    emx = {a: _evidence_missing_exits(arms[a]) for a in need}
    add("G1", "The gate reduces exits on missing evidence: fewer in the gated arm for each of the three controllers, and at least halved when pooled",
        {c: [emx[c], emx[c + "_gated"]] for c in CONTROLLERS},
        all(emx[c + "_gated"] < emx[c] or emx[c] == 0 for c in CONTROLLERS)
        and sum(emx[c + "_gated"] for c in CONTROLLERS) * 2 <= sum(emx[c] for c in CONTROLLERS))
    eff = {g["controller"]: g["success"] for g in locked["gate_effect"]}
    fixed, broke = sum(e["only_candidate"] for e in eff.values()), sum(e["only_reference"] for e in eff.values())
    add("G2", "The gate does not cost success: gated successes >= ungated for each controller, and pooled it fixes more tasks than it breaks",
        {"per_controller": {c: [ok(c), ok(c + "_gated")] for c in CONTROLLERS}, "fixed": fixed, "broke": broke},
        all(ok(c + "_gated") >= ok(c) for c in CONTROLLERS) and fixed > broke)
    drop = {a: S[a]["dropped_actions"] for a in need}
    add("G3", "The action latch works: pooled over the three controllers, dropped actions fall with the gate, and no gated arm drops more than 1",
        {c: [drop[c], drop[c + "_gated"]] for c in CONTROLLERS},
        sum(drop[c + "_gated"] for c in CONTROLLERS) < sum(drop[c] for c in CONTROLLERS) and all(drop[c + "_gated"] <= 1 for c in CONTROLLERS))
    spread = lambda xs: max(xs) - min(xs)
    off, on = [ok(c) for c in CONTROLLERS], [ok(c + "_gated") for c in CONTROLLERS]
    add("G4", "The controller matters less behind the gate: the spread of success across the three controllers is smaller gated than ungated",
        {"ungated": off, "gated": on, "spread": [spread(off), spread(on)]}, spread(on) < spread(off))
    tok = lambda a: arms[a]["accounting"]["qwen35_tokens_computed_per_task"]
    add("G5", "A learned head is not needed behind the gate: gated rules succeed within 3 tasks of the gated learned head (or better) and compute fewer model tokens per task",
        {"rules_gated": [ok("rules_gated"), tok("rules_gated")], "dm_dynamic_gated": [ok("dm_dynamic_gated"), tok("dm_dynamic_gated")]},
        ok("rules_gated") >= ok("dm_dynamic_gated") - 3 and tok("rules_gated") < tok("dm_dynamic_gated"))
    sec = lambda a: S[a]["local_compute_s_per_task"]
    add("C1", "The contract planner is at least as successful as the heavy-only agent and uses at most half its local compute per attempted task",
        {"contract": [ok("contract"), sec("contract")], "heavy_agent": [ok("heavy_agent"), sec("heavy_agent")]},
        ok("contract") >= ok("heavy_agent") and sec("contract") <= 0.5 * sec("heavy_agent"))
    best_other = max(ok(a) for a in need if a not in ("contract", "contract_narrated"))
    add("C2", "The contract planner is the most successful arm, or within 2 tasks of the best gated or ungated v0.6 controller",
        {"contract": ok("contract"), "best_other": best_other}, ok("contract") >= best_other - 2)
    r = locked.get("planner_routing") or {}
    planned = r.get("planned", {"tasks": 0, "successes": 0, "typing_matches_gold": 0})
    add("C3", "The lexicon types at least half of the requests, and at least 85% of the requests it types get the gold claim type",
        {"typed": planned["tasks"], "of": locked["tasks"], "typing_matches_gold": planned["typing_matches_gold"]},
        planned["tasks"] * 2 >= locked["tasks"] and planned["typing_matches_gold"] >= 0.85 * planned["tasks"])
    add("C4", "Having the heavy model narrate the host's findings does not help at this model scale: narrated successes <= host-findings successes",
        {"contract": ok("contract"), "contract_narrated": ok("contract_narrated")}, ok("contract_narrated") <= ok("contract"))
    ser = {a: S[a]["serious_failure"] for a in need}
    add("S1", "Serious failures do not increase with the gate for any controller, and the contract planner has no more than any v0.6 controller",
        {**{c: [ser[c], ser[c + "_gated"]] for c in CONTROLLERS}, "contract": ser["contract"]},
        all(ser[c + "_gated"] <= ser[c] for c in CONTROLLERS) and ser["contract"] <= min(ser[c] for c in CONTROLLERS))
    writes = {a: S[a]["writes_executed"] for a in need}
    add("S2", "0 writes executed in every arm", writes, all(v == 0 for v in writes.values()))
    add("E1", "The gate's overhead on the heavy-only agent is bounded: at most 1.5x its local compute per attempted task",
        {"heavy_agent": sec("heavy_agent"), "heavy_agent_gated": sec("heavy_agent_gated")}, sec("heavy_agent_gated") <= 1.5 * sec("heavy_agent"))
    return out
