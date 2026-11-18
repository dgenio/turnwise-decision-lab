"""Deterministic, faithful rendering of verified tool output for generation prompts.

Used identically by the decision-driven loop (evidence blocks) and by the
heavy-only baseline (tool responses), so presentation is not a confound. It
restates fields; it never adds a conclusion that is not in the data.
"""
from __future__ import annotations

import json


def render_fact(key: str, v) -> str:
    kind = key.split(":")[0]
    try:
        if kind == "errors":
            trend = f"increase starting {v['change_point']}" if v.get("change_point") else "no increase"
            return f"[{key}] error rate {v['before_pct']}% -> {v['after_pct']}% over {v['window']} ({trend})"
        if kind == "deploys":
            if not v["deploys"]:
                return f"[{key}] no deployments of {v['service']} in the {v['window']}"
            return f"[{key}] " + "; ".join(f"deploy {d['id']} at {d['at'][11:16]} approved by {d['approved_by']}: {d['change']}" for d in v["deploys"])
        if kind == "health":
            return f"[{key}] status {v['status']}, error rate {v['error_rate_pct']}%, p95 {v['p95_ms']} ms"
        if kind == "config":
            if v["matches_baseline"]:
                return f"[{key}] configuration matches the approved baseline"
            return f"[{key}] drifted from baseline: " + "; ".join(f"{k} {d['current']} (baseline {d['baseline']})" for k, d in v["drifted"].items())
        if kind == "owner":
            return f"[{key}] owning team {v['team']}, on-call {v['oncall']}"
        if kind == "smoke":
            return f"[{key}] failed checks: {', '.join(v['failed']) or 'none'}; all checks: {json.dumps(v['checks'], sort_keys=True)}"
        if kind == "doc":
            return f"[{key}] {v['title']}: {v['body']}"
    except (KeyError, TypeError):
        pass
    return f"[{key}] {json.dumps(v, sort_keys=True)}"


def render_facts(facts: dict) -> str:
    return "\n".join(render_fact(k, v) for k, v in facts.items())
