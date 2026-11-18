"""Static parity preflight for independently executed agent-comparison traces.

No external provider calls; does not score answers or establish fairness on its own.
Use a declared setup and event receipts to flag unequal access and hidden work.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "turnwise-comparison-parity/v1"
KINDS = ("decision", "context", "retrieval", "tool", "workflow", "model")
FIXED = (
    "principal", "permissions", "capabilities", "available_documents",
    "available_tool_facts", "host_facts", "approval_policy", "max_tool_calls",
    "max_wall_ms",
)
TREATMENTS = ("document_access_mode", "initial_context_sources", "cache_regime")
TOKEN_KINDS = frozenset({"decision", "context", "model"})


def _normalized(value: Any) -> Any:
    """Only explicitly unordered access lists are normalized for parity."""
    if isinstance(value, list):
        return tuple(sorted(value))
    return value


def audit(manifest: dict[str, Any]) -> dict[str, Any]:
    """Return actionable blockers; no provider/model access or mutation.

    Passing this audit confirms only that declared access/budgets and recorded
    events meet the manifest rules. It cannot prove that receipts are complete,
    an agent's answer was correct, or the experimental arms are equivalent.
    """
    blockers: list[str] = []
    treatments: list[str] = []
    summaries: dict[str, dict[str, Any]] = {}
    if manifest.get("schema_version") != SCHEMA_VERSION:
        blockers.append(f"schema_version must be {SCHEMA_VERSION}")
    arms = manifest.get("arms")
    if not isinstance(arms, list) or len(arms) < 2:
        return {"structural_parity_passed": False, "blockers": blockers + ["at least two arms required"],
                "declared_treatments": treatments, "arm_summaries": summaries}
    if any(not isinstance(a, dict) for a in arms):
        return {"structural_parity_passed": False, "blockers": blockers + ["each arm must be an object"],
                "declared_treatments": treatments, "arm_summaries": summaries}
    ids = [a.get("id") for a in arms]
    if not all(isinstance(i, str) and i.strip() for i in ids) or len(set(ids)) != len(ids):
        blockers.append("arm ids must be unique, non-empty strings")
    label = lambda a: a.get("id") if isinstance(a.get("id"), str) else "<unnamed>"
    base = arms[0]
    allowed: dict[str, str] = {}
    declarations = manifest.get("declared_treatments", [])
    if not isinstance(declarations, list):
        blockers.append("declared_treatments must be a list")
        declarations = []
    for declaration in declarations:
        if not isinstance(declaration, dict):
            blockers.append("declared_treatments entries must be objects")
            continue
        field, reason = declaration.get("field"), declaration.get("reason")
        if field not in TREATMENTS or not isinstance(reason, str) or not reason.strip():
            blockers.append("treatment needs a permitted field and a non-empty predeclared reason")
        elif field in allowed:
            blockers.append(f"duplicate treatment declaration for {field}")
        else:
            allowed[field] = reason

    for a in arms:
        name = label(a)
        for field in FIXED + TREATMENTS:
            if field not in a:
                blockers.append(f"{name}: missing setup field {field}")
        for field in ("permissions", "capabilities", "available_documents", "available_tool_facts", "host_facts", "initial_context_sources"):
            if not isinstance(a.get(field), list) or any(not isinstance(v, str) for v in a.get(field, [])):
                blockers.append(f"{name}: {field} must be an array of source/permission ids")
        for field in ("max_tool_calls", "max_wall_ms"):
            if type(a.get(field)) is not int or a[field] <= 0:
                blockers.append(f"{name}: {field} must be a positive integer")
        if a is not base:
            for field in FIXED:
                if _normalized(a.get(field)) != _normalized(base.get(field)):
                    blockers.append(f"{name}: non-negotiable parity mismatch in {field} vs {label(base)}")
            for field in TREATMENTS:
                if _normalized(a.get(field)) != _normalized(base.get(field)):
                    if field in allowed:
                        entry = f"{name}: {field} differs from {label(base)} (predeclared: {allowed[field]})"
                        treatments.append(entry)
                    else:
                        blockers.append(f"{name}: {field} differs without a declared treatment")
        events = a.get("events")
        counts = a.get("declared_event_counts")
        if not isinstance(events, list) or not isinstance(counts, dict) or set(counts) != set(KINDS):
            blockers.append(f"{name}: events and complete declared_event_counts ({', '.join(KINDS)}) required")
            continue
        for kind in KINDS:
            if type(counts.get(kind)) is not int or counts[kind] < 0:
                blockers.append(f"{name}: declared_event_counts.{kind} must be a nonnegative integer")
        visible = set(a.get("host_facts", [])) | set(a.get("initial_context_sources", []))
        permitted_sources = (set(a.get("host_facts", [])) | set(a.get("available_documents", []))
                             | set(a.get("available_tool_facts", [])))
        observed: Counter = Counter()
        computed, cached, output = 0, 0, 0
        documented_duration = 0.0
        billed_sum = 0.0
        billed_complete = True
        for i, event in enumerate(events):
            context = f"{name}: event[{i}]"
            if not isinstance(event, dict):
                blockers.append(f"{context} must be an object")
                continue
            kind = event.get("kind")
            if kind not in KINDS:
                blockers.append(f"{context}: invalid work kind {kind!r}")
                continue
            observed[kind] += 1
            ms = event.get("duration_ms")
            if isinstance(ms, bool) or not isinstance(ms, (int, float)) or not 0 <= ms < float("inf"):
                blockers.append(f"{context}: finite nonnegative duration_ms required")
            else:
                documented_duration += ms
            usd = event.get("billed_usd", "<missing>")
            if usd == "<missing>" or usd is None:
                billed_complete = False
            elif isinstance(usd, bool) or not isinstance(usd, (float, int)) or not 0 <= usd < float("inf"):
                blockers.append(f"{context}: billed_usd must be a nonnegative number or null")
            else:
                billed_sum += usd
            if kind in TOKEN_KINDS:
                for key in ("input_tokens_new", "input_tokens_cached", "output_tokens"):
                    val = event.get(key)
                    if type(val) is not int or val < 0:
                        blockers.append(f"{context}: {key} must be a nonnegative integer (0 for rules)")
                computed += event.get("input_tokens_new", 0) if type(event.get("input_tokens_new")) is int else 0
                cached += event.get("input_tokens_cached", 0) if type(event.get("input_tokens_cached")) is int else 0
                output += event.get("output_tokens", 0) if type(event.get("output_tokens")) is int else 0
            if kind in ("retrieval", "tool", "workflow"):
                sources = event.get("source_ids")
                if not isinstance(sources, list) or any(not isinstance(s, str) for s in sources):
                    blockers.append(f"{context}: source_ids must be a list (possibly empty)")
                else:
                    unexpected = set(sources) - permitted_sources
                    if unexpected:
                        blockers.append(f"{context}: unknown/unavailable source ids {sorted(unexpected)}")
                    visible.update(sources)
            if kind == "model":
                sources = event.get("prompt_source_ids")
                if not isinstance(sources, list) or any(not isinstance(s, str) for s in sources):
                    blockers.append(f"{context}: model prompt_source_ids must be a list")
                else:
                    unreceived = set(sources) - visible
                    if unreceived:
                        blockers.append(f"{context}: model saw sources without earlier retrieval/tool/initial-context receipt: {sorted(unreceived)}")
        for kind in KINDS:
            if type(counts.get(kind)) is int and observed[kind] != counts[kind]:
                blockers.append(f"{name}: {kind} receipt count {observed[kind]} != declared {counts[kind]}")
        if isinstance(a.get("max_tool_calls"), int) and observed["tool"] + observed["workflow"] > a["max_tool_calls"]:
            blockers.append(f"{name}: observed tool/workflow calls exceed max_tool_calls")
        wall = a.get("wall_ms")
        if isinstance(wall, bool) or not isinstance(wall, (int, float)) or not 0 <= wall < float("inf"):
            blockers.append(f"{name}: finite nonnegative wall_ms required")
        elif isinstance(a.get("max_wall_ms"), int) and wall > a["max_wall_ms"]:
            blockers.append(f"{name}: wall_ms exceeds max_wall_ms")
        summaries[name] = {"recorded_events": dict(observed), "input_tokens_new": computed,
                           "input_tokens_cached": cached, "output_tokens": output,
                           "sum_event_durations_ms_not_wall": round(documented_duration, 3),
                           "billed_usd_if_complete": round(billed_sum, 8) if billed_complete else None,
                           "wall_ms": wall}
    return {"structural_parity_passed": not blockers, "blockers": blockers,
            "declared_treatments": treatments, "arm_summaries": summaries}


def main() -> None:
    parser = argparse.ArgumentParser(description="Preflight parity of declared agent benchmark arms/receipts")
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    report = audit(json.loads(args.manifest.read_text(encoding="utf-8")))
    print(json.dumps(report, indent=2, sort_keys=True))
    if not report["structural_parity_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
