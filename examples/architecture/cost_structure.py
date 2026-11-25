"""Cost structure of the two architectures on the showcase task. SIMULATED, structural; offline (#85).

    python -m examples.architecture.cost_structure
    python -m examples.architecture.cost_structure --framework openai-agents --json-out cost-structure.json
    python -m examples.architecture.cost_structure --scenario all     # the four demo scenarios and their aggregate

"Model calls" is not a unit of cost. This command runs the showcase task against the
local provider double (no network, no key, no inference) and reports what each
arm actually *sends*: how many requests, how large each one is, and how much of
each request is an exact prefix of the previous one, which is what a prompt
cache can reuse. It then prices those shapes under stated billing assumptions.

Three arms per framework, with the same task, tools, host and simulated model:

* **A**   the conventional agent; the simulated model asks for one tool per response;
* **A'**  the same agent when the model asks for its evidence reads in ONE response
          (parallel tool calls, which tool-calling APIs support);
* **B**   the same agent under Turnwise Core.

What this is not: a measurement. Token counts are the double's synthetic
``bytes // 4``, replies are simulated, and a real model may batch differently or
not at all. The output shows which way each billing assumption pushes the
comparison, and that the sign depends on the assumption.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from typing import Any

from .cost_accounting import (ASSUMPTIONS, NO_CACHING, STRUCTURAL_LABEL, PriceCard, RequestShape,
                              breakeven_cache_read_multiplier, shapes_from_exchanges, structural_cost)
from .incident_env import TASKS
from .provider import DOUBLE_SOURCE, ProviderLedger, ProviderSettings, ProviderSetup
from .provider_double import ProviderDouble
from .simulated_model import SimulatedInvestigator

FRAMEWORKS = ("openai-agents", "llamaindex")
BATCHED = "A'"
# (key, architecture run by live_smoke.run_config, simulated model batches its evidence reads?)
ARMS = (("A", "conventional", False), (BATCHED, "conventional", True), ("B", "turnwise", False))
ARM_NAMES = {"A": "conventional agent", BATCHED: "conventional agent, batched reads", "B": "Turnwise Core"}
# The price card this repository recorded for its proposed smoke model. Operator-supplied; verify before reuse.
RECORDED_CARD = PriceCard(2.00, 0.10, 2.50, 10.00,
                          source="docs/live-smoke-decision-packet.md (gpt-6.1-sol; prices read 2026-11-19)")
DEFAULT_STABLE_PREFIX_TOKENS = (0, 5_000, 20_000)
DEFAULT_MIN_CACHEABLE_TOKENS = 1_024

# ---- #85's pre-declared falsifier, made operational BEFORE any four-scenario number was computed.
# Issue #85: "Falsified if the structural estimate at realistic prefix size shows B at least 15% below A' in
# billed cost, aggregated over the four demo scenarios." The words "realistic prefix size" and "billed cost"
# are fixed here as follows, and are not to be changed after seeing results:
FALSIFIER_THRESHOLD_PCT = -15.0
REALISTIC_STABLE_PREFIX_TOKENS = (5_000, 20_000)
FALSIFIER_RULE = (
    "Issue #85's pre-declared falsifier: H (Turnwise Core has no input-cost advantage over a batching native agent) "
    "is falsified if, at realistic prefix size, B is at least 15% below A' in billed cost aggregated over the four "
    "demo scenarios. Operationalised before the four-scenario numbers were computed: realistic prefix size means the "
    "5,000- and 20,000-token stable-prefix rows; billed cost means both cache-aware assumptions with the minimum "
    "cacheable length applied. Per framework, the verdict is FALSIFIED if B vs A' is at or below -15% in every one "
    "of those rows, CONSISTENT if it is above -15% in every one, and MIXED otherwise. No-caching rows are reported "
    "but do not decide.")


def run_arm(framework: str, architecture: str, *, batch_reads: bool, model: str,
            scenario: str | None = None) -> dict[str, Any]:
    """Run one arm of one demo scenario against a fresh provider double and return the smoke record."""
    from .live_smoke import SCENARIO, request_cap, run_config

    settings = ProviderSettings(model=model)
    ledger = ProviderLedger(source=DOUBLE_SOURCE, max_requests=request_cap(architecture),
                            max_output_tokens=settings.max_output_tokens)
    double = ProviderDouble(SimulatedInvestigator(batch_reads=batch_reads))
    return run_config(framework, architecture, ProviderSetup(settings, ledger, double.transport()),
                      scenario=scenario or SCENARIO)


def batching_label(shapes: list[RequestShape]) -> str:
    """How the arm issued tool calls, read from the wire record (never from a setting)."""
    most = max((s.tool_calls for s in shapes), default=0)
    if most == 0:
        return "no native tool calls (the model only proposes)"
    return "sequential (1 tool call per response)" if most == 1 else f"batched (up to {most} tool calls per response)"


def cost_rows(arms: dict[str, list[RequestShape]], card: PriceCard, stable_prefix_tokens: tuple[int, ...],
              min_cacheable_tokens: int) -> list[dict[str, Any]]:
    rows = []
    for stable in stable_prefix_tokens:
        for assumption in ASSUMPTIONS:
            minimums = [0] if assumption == NO_CACHING else (
                [0, min_cacheable_tokens] if stable == 0 else [min_cacheable_tokens])
            for minimum in minimums:
                usd = {key: structural_cost(shapes, card, assumption, stable_prefix_tokens=stable,
                                            min_cacheable_tokens=minimum) for key, shapes in arms.items()}
                rows.append({"stable_prefix_tokens": stable, "assumption": assumption,
                             "min_cacheable_tokens": None if assumption == NO_CACHING else minimum, "usd": usd,
                             "b_vs_a_pct": _pct(usd.get("B"), usd.get("A")),
                             "b_vs_a_batched_pct": _pct(usd.get("B"), usd.get(BATCHED))})
    return rows


def build_report(frameworks: tuple[str, ...] = FRAMEWORKS, *, card: PriceCard = RECORDED_CARD,
                 stable_prefix_tokens: tuple[int, ...] = DEFAULT_STABLE_PREFIX_TOKENS,
                 min_cacheable_tokens: int = DEFAULT_MIN_CACHEABLE_TOKENS,
                 model: str | None = None, scenario: str | None = None) -> dict[str, Any]:
    from .live_smoke import DOUBLE_DEFAULT_MODEL, SCENARIO

    scenario = scenario or SCENARIO
    report: dict[str, Any] = {"label": STRUCTURAL_LABEL, "scenario": scenario, "source": DOUBLE_SOURCE,
                              "real_inference": False, "price_card": asdict(card),
                              "min_cacheable_tokens": min_cacheable_tokens, "frameworks": {}}
    for framework in frameworks:
        arms, shapes_by_arm = [], {}
        for key, architecture, batch in ARMS:
            record = run_arm(framework, architecture, batch_reads=batch, model=model or DOUBLE_DEFAULT_MODEL,
                             scenario=scenario)
            shapes = shapes_from_exchanges(record["provider_requests"])
            shapes_by_arm[key] = shapes
            arms.append({
                "arm": key, "name": ARM_NAMES[key], "architecture": architecture, "verdict": record["verdict"],
                "termination": record["termination"]["status"], "error": record["error"],
                "requests": len(shapes), "tool_call_batching": batching_label(shapes),
                "max_tool_calls_per_response": max((s.tool_calls for s in shapes), default=0),
                "host_tool_calls": [t["tool"] for t in record["tool_calls"] if t["status"] == "executed"],
                "request_chars": [s.chars for s in shapes],
                "shared_prefix_share": [round(s.shared_share, 3) for s in shapes],
                "input_tokens": [s.input_tokens for s in shapes],
                "output_tokens": [s.output_tokens for s in shapes],
                "billing": record["billing"]})
        report["frameworks"][framework] = {
            "arms": arms,
            "costs": cost_rows(shapes_by_arm, card, stable_prefix_tokens, min_cacheable_tokens),
            # Undefined when an arm sends nothing (the host answered without a model): no price makes them equal.
            "breakeven_cache_read_multiplier_b_vs_a": _round(
                breakeven_cache_read_multiplier(shapes_by_arm["A"], shapes_by_arm["B"])
                if shapes_by_arm["A"] and shapes_by_arm["B"] else None, 3)}
    return report


# ------------------------------------------------------------- the four demo scenarios together
def aggregate_costs(reports: dict[str, dict[str, Any]], framework: str) -> list[dict[str, Any]]:
    """Sum each arm's structural USD over the scenarios, row by row (same stable prefix, assumption, minimum)."""
    scenarios = list(reports)
    base = reports[scenarios[0]]["frameworks"][framework]["costs"]
    rows = []
    for i, row in enumerate(base):
        key = (row["stable_prefix_tokens"], row["assumption"], row["min_cacheable_tokens"])
        usd: dict[str, float | None] = {}
        for arm in ("A", BATCHED, "B"):
            values = []
            for s in scenarios:
                other = reports[s]["frameworks"][framework]["costs"][i]
                if (other["stable_prefix_tokens"], other["assumption"], other["min_cacheable_tokens"]) != key:
                    raise ValueError(f"cost rows of scenario {s!r} do not line up with {scenarios[0]!r}")
                values.append(other["usd"].get(arm))
            usd[arm] = None if any(v is None for v in values) else sum(values)
        rows.append({"stable_prefix_tokens": key[0], "assumption": key[1], "min_cacheable_tokens": key[2], "usd": usd,
                     "b_vs_a_pct": _pct(usd["B"], usd["A"]), "b_vs_a_batched_pct": _pct(usd["B"], usd[BATCHED]),
                     "per_scenario_b_vs_a_batched_pct": {
                         s: reports[s]["frameworks"][framework]["costs"][i]["b_vs_a_batched_pct"] for s in scenarios}})
    return rows


def falsifier_verdict(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply FALSIFIER_RULE to aggregated cost rows of one framework."""
    deciding = [r for r in rows if r["stable_prefix_tokens"] in REALISTIC_STABLE_PREFIX_TOKENS
                and r["assumption"] != NO_CACHING and r["min_cacheable_tokens"]]
    values = [r["b_vs_a_batched_pct"] for r in deciding]
    if not deciding or any(v is None for v in values):
        verdict = "NOT EVALUABLE"
    else:
        hits = [v <= FALSIFIER_THRESHOLD_PCT for v in values]
        verdict = "FALSIFIED" if all(hits) else "CONSISTENT" if not any(hits) else "MIXED"
    return {"verdict": verdict, "threshold_pct": FALSIFIER_THRESHOLD_PCT,
            "deciding_rows": [{"stable_prefix_tokens": r["stable_prefix_tokens"], "assumption": r["assumption"],
                               "min_cacheable_tokens": r["min_cacheable_tokens"],
                               "b_vs_a_batched_pct": r["b_vs_a_batched_pct"]} for r in deciding]}


def build_scenarios_report(frameworks: tuple[str, ...] = FRAMEWORKS, scenarios: tuple[str, ...] = tuple(TASKS), *,
                           card: PriceCard = RECORDED_CARD,
                           stable_prefix_tokens: tuple[int, ...] = DEFAULT_STABLE_PREFIX_TOKENS,
                           min_cacheable_tokens: int = DEFAULT_MIN_CACHEABLE_TOKENS,
                           model: str | None = None) -> dict[str, Any]:
    """One structural report per demo scenario, their per-row sums, and #85's falsifier applied to the sums."""
    reports = {s: build_report(frameworks, card=card, stable_prefix_tokens=stable_prefix_tokens,
                               min_cacheable_tokens=min_cacheable_tokens, model=model, scenario=s) for s in scenarios}
    aggregate = {}
    for framework in frameworks:
        rows = aggregate_costs(reports, framework)
        aggregate[framework] = {"costs": rows, "falsifier": falsifier_verdict(rows)}
    return {"label": STRUCTURAL_LABEL, "source": DOUBLE_SOURCE, "real_inference": False,
            "price_card": asdict(card), "min_cacheable_tokens": min_cacheable_tokens, "scenarios": list(scenarios),
            "falsifier_rule": FALSIFIER_RULE, "per_scenario": reports, "aggregate": aggregate}


def render(report: dict[str, Any]) -> str:
    card = report["price_card"]
    lines = ["Cost structure of the showcase task | " + report["source"], report["label"],
             f"scenario {report['scenario']!r} | price card: input ${card['input_per_mtok']:g}, cached input "
             f"${card['cached_input_per_mtok']:g}, cache write ${card['cache_write_per_mtok']:g}, output "
             f"${card['output_per_mtok']:g} per MTok ({card['source']})", ""]
    for framework, data in report["frameworks"].items():
        lines += [f"=== {framework}: what each arm sends ==="]
        for arm in data["arms"]:
            shares = ", ".join("-" if i == 0 else f"{share:.0%}" for i, share in enumerate(arm["shared_prefix_share"]))
            lines += [f"{arm['arm']:<3}{arm['name']}",
                      f"     requests            : {arm['requests']}  ({arm['tool_call_batching']})",
                      f"     request chars       : {', '.join(str(c) for c in arm['request_chars'])}",
                      f"     prefix of previous  : {shares}",
                      f"     input tokens (synth): {', '.join(_show(t) for t in arm['input_tokens'])}"
                      f"  | output tokens (synth): {_show(_total(arm['output_tokens']))}"]
            if arm["verdict"] != "PASS":
                lines.append(f"     NOTE: mechanism verdict {arm['verdict']} ({arm['error'] or arm['termination']})")
        multiplier = data["breakeven_cache_read_multiplier_b_vs_a"]
        lines += ["", f"=== {framework}: the same shapes under each billing assumption (USD, arithmetic) ===",
                  f"{'stable prefix':>13} | {'assumption':<66} | {'min cacheable':>13} | "
                  f"{'A':>9} {'A-batched':>9} {'B':>9} | {'B vs A':>7} {'B vs A-b':>8}"]
        for row in data["costs"]:
            minimum = row["min_cacheable_tokens"]
            usd = row["usd"]
            lines.append(
                f"{row['stable_prefix_tokens']:>13} | {row['assumption']:<66} | "
                f"{'n/a' if minimum is None else 'ignored' if minimum == 0 else minimum:>13} | "
                f"{_usd(usd.get('A')):>9} {_usd(usd.get(BATCHED)):>9} {_usd(usd.get('B')):>9} | "
                f"{_signed(row['b_vs_a_pct']):>7} {_signed(row['b_vs_a_batched_pct']):>8}")
        if multiplier is not None:
            lines.append(f"Input-only break-even: B's input costs less than A's only if a cache read costs more than "
                         f"{multiplier:.2f}x the fresh input price (no write premium, minimum ignored).")
        lines.append("")
    lines += ["How to read this: 'stable prefix' adds the same stable tokens (a larger system prompt and tool "
              "catalogue) to every request of every arm.",
              "'min cacheable' is a provider's minimum cacheable prompt length; below it nothing is read from cache.",
              "Latency is not modelled: fewer round trips is a real advantage over a sequential agent and none over "
              "one that batches.",
              "Nothing here measures answer quality, real cost or real latency."]
    return "\n".join(lines)


def render_scenarios(report: dict[str, Any]) -> str:
    card = report["price_card"]
    scenarios = report["scenarios"]
    lines = ["Cost structure over the demo scenarios | " + report["source"], report["label"],
             f"scenarios {', '.join(scenarios)} | price card: input ${card['input_per_mtok']:g}, cached input "
             f"${card['cached_input_per_mtok']:g}, cache write ${card['cache_write_per_mtok']:g}, output "
             f"${card['output_per_mtok']:g} per MTok ({card['source']})", "", report["falsifier_rule"], ""]
    for framework, data in report["aggregate"].items():
        lines += [f"=== {framework}: what each arm did, per scenario (requests; how the run ended; mechanism verdict) ==="]
        for s in scenarios:
            arms = {a["arm"]: a for a in report["per_scenario"][s]["frameworks"][framework]["arms"]}
            cells = [f"{key} {arms[key]['requests']} req, {arms[key]['termination']}, {arms[key]['verdict']}"
                     for key in ("A", BATCHED, "B")]
            lines.append(f"{s:<12} | " + " | ".join(cells))
        lines += ["(B with 0 requests: the host answered or held the request without a model call. A mechanism "
                  "verdict of INCONCLUSIVE there only means no provider response was exercised.)", "",
                  f"=== {framework}: summed over the {len(scenarios)} scenarios (USD, arithmetic) ===",
                  f"{'stable prefix':>13} | {'assumption':<66} | {'min cacheable':>13} | "
                  f"{'A':>9} {'A-batched':>9} {'B':>9} | {'B vs A':>7} {'B vs A-b':>8} | B vs A-b per scenario"]
        for row in data["costs"]:
            minimum = row["min_cacheable_tokens"]
            usd = row["usd"]
            per = ", ".join(f"{s} {_signed(v)}" for s, v in row["per_scenario_b_vs_a_batched_pct"].items())
            lines.append(
                f"{row['stable_prefix_tokens']:>13} | {row['assumption']:<66} | "
                f"{'n/a' if minimum is None else 'ignored' if minimum == 0 else minimum:>13} | "
                f"{_usd(usd.get('A')):>9} {_usd(usd.get(BATCHED)):>9} {_usd(usd.get('B')):>9} | "
                f"{_signed(row['b_vs_a_pct']):>7} {_signed(row['b_vs_a_batched_pct']):>8} | {per}")
        f = data["falsifier"]
        lines += ["", f"#85 falsifier, {framework}: {f['verdict']} (deciding rows, B vs A-batched: "
                  + ", ".join(f"{r['stable_prefix_tokens']} prefix / {r['assumption']}: {_signed(r['b_vs_a_batched_pct'])}"
                              for r in f["deciding_rows"]) + ")", ""]
    lines += ["Nothing here measures answer quality, real cost or real latency. Token counts are synthetic and every "
              "reply is simulated; a real model may batch differently or not at all."]
    return "\n".join(lines)


def _pct(value: float | None, reference: float | None) -> float | None:
    return None if value is None or not reference else round(100 * (value / reference - 1), 1)


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


def _total(values: list[int | None]) -> int | None:
    return None if any(v is None for v in values) else sum(values)


def _show(value: int | None) -> str:
    return "unknown" if value is None else str(value)


def _usd(value: float | None) -> str:
    return "unknown" if value is None else f"{value:.5f}"


def _signed(value: float | None) -> str:
    return "unknown" if value is None else f"{value:+.0f}%"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--framework", choices=("all",) + FRAMEWORKS, default="all")
    p.add_argument("--scenario", choices=(*TASKS, "all"), default="investigate",
                   help="one demo scenario, or 'all' for every scenario plus their sum and #85's falsifier")
    p.add_argument("--input-usd-per-mtok", type=float, default=RECORDED_CARD.input_per_mtok)
    p.add_argument("--cached-input-usd-per-mtok", type=float, default=RECORDED_CARD.cached_input_per_mtok)
    p.add_argument("--cache-write-usd-per-mtok", type=float, default=RECORDED_CARD.cache_write_per_mtok)
    p.add_argument("--output-usd-per-mtok", type=float, default=RECORDED_CARD.output_per_mtok)
    p.add_argument("--min-cacheable-tokens", type=int, default=DEFAULT_MIN_CACHEABLE_TOKENS)
    p.add_argument("--stable-prefix-tokens", default=",".join(str(n) for n in DEFAULT_STABLE_PREFIX_TOKENS),
                   help="comma list of stable-prefix sizes to add to every request (sensitivity)")
    p.add_argument("--json-out", help="also write the report as JSON here")
    args = p.parse_args(argv)
    prices = (args.input_usd_per_mtok, args.cached_input_usd_per_mtok, args.cache_write_usd_per_mtok,
              args.output_usd_per_mtok)
    recorded = (RECORDED_CARD.input_per_mtok, RECORDED_CARD.cached_input_per_mtok,
                RECORDED_CARD.cache_write_per_mtok, RECORDED_CARD.output_per_mtok)
    try:
        card = RECORDED_CARD if prices == recorded else PriceCard(*prices, source="command line")
        stable = tuple(int(part) for part in args.stable_prefix_tokens.split(",") if part.strip())
        if args.min_cacheable_tokens < 0 or any(n < 0 for n in stable) or not stable:
            raise ValueError("token counts must be nonnegative, and at least one stable-prefix size is needed")
    except ValueError as exc:
        p.error(str(exc))
    frameworks = FRAMEWORKS if args.framework == "all" else (args.framework,)
    try:
        if args.scenario == "all":
            report = build_scenarios_report(frameworks, card=card, stable_prefix_tokens=stable,
                                            min_cacheable_tokens=args.min_cacheable_tokens)
        else:
            report = build_report(frameworks, card=card, stable_prefix_tokens=stable,
                                  min_cacheable_tokens=args.min_cacheable_tokens, scenario=args.scenario)
    except ImportError as exc:
        print(f"The cost-structure report runs the real SDK provider classes offline and needs them installed "
              f"({exc}).\n    pip install -r examples/architecture/requirements.txt", file=sys.stderr)
        return 2
    print(render_scenarios(report) if args.scenario == "all" else render(report))
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)
            handle.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
