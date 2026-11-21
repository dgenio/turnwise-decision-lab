"""Cost structure of the two architectures on the showcase task. SIMULATED, structural; offline (#85).

    python -m examples.architecture.cost_structure
    python -m examples.architecture.cost_structure --framework openai-agents --json-out cost-structure.json

"Model calls" is not a unit of cost. This command runs the showcase task against the
local provider double (no network, no key, no inference) and reports what each
arm actually *sends*: how many requests, how large each one is, and how much of
each request is an exact prefix of the previous one, which is what a prompt
cache can reuse. It then prices those shapes under stated billing assumptions.

Three arms per framework, with the same task, tools, host and simulated model:

* **A**   the conventional agent; the simulated model asks for one tool per response;
* **A'**  the same agent when the model asks for its evidence reads in ONE response
          (parallel tool calls, which tool-calling APIs support);
* **B**   the same agent under Turnwise Core;
* **S**   the same agent, shielded: host rules and evidence reads first, then the unmodified
          agent loop, then a host exit gate on its typed, cited answer. The agent keeps control,
          so this is NOT Turnwise Core. OpenAI Agents SDK only (#88).

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

from .cost_accounting import (ASSUMPTIONS, NO_CACHING, STRUCTURAL_LABEL, PriceCard, RequestShape, billing_totals,
                              breakeven_cache_read_multiplier, shapes_from_exchanges, structural_cost)
from .provider import DOUBLE_SOURCE, ProviderLedger, ProviderSettings, ProviderSetup
from .provider_double import ProviderDouble
from .simulated_model import SimulatedInvestigator

FRAMEWORKS = ("openai-agents", "llamaindex")
BATCHED = "A'"
# (key, architecture run by live_smoke.run_config, simulated model batches its evidence reads?)
ARMS = (("A", "conventional", False), (BATCHED, "conventional", True), ("B", "turnwise", False))
SHIELDED = "S"
SHIELDED_FRAMEWORKS = ("openai-agents",)  # arm S exists for this pair only
ARM_NAMES = {"A": "conventional agent", BATCHED: "conventional agent, batched reads", "B": "Turnwise Core",
             SHIELDED: "shielded native agent (the agent keeps control; NOT Turnwise Core)"}
# The price card this repository recorded for its proposed smoke model. Operator-supplied; verify before reuse.
RECORDED_CARD = PriceCard(2.00, 0.10, 2.50, 10.00,
                          source="docs/live-smoke-decision-packet.md (gpt-6.1-sol; prices read 2026-11-19)")
DEFAULT_STABLE_PREFIX_TOKENS = (0, 5_000, 20_000)
DEFAULT_MIN_CACHEABLE_TOKENS = 1_024


def run_arm(framework: str, architecture: str, *, batch_reads: bool, model: str) -> dict[str, Any]:
    """Run one arm of the showcase against a fresh provider double and return the smoke record."""
    from .live_smoke import request_cap, run_config

    settings = ProviderSettings(model=model)
    ledger = ProviderLedger(source=DOUBLE_SOURCE, max_requests=request_cap(architecture),
                            max_output_tokens=settings.max_output_tokens)
    double = ProviderDouble(SimulatedInvestigator(batch_reads=batch_reads))
    return run_config(framework, architecture, ProviderSetup(settings, ledger, double.transport()))


def run_shielded_arm(*, model: str) -> dict[str, Any]:
    """Arm S on the showcase against a fresh provider double. It is not a smoke-matrix configuration, so it is
    run here and graded on mechanism only: a host-accepted answer, no executed write, no refused request."""
    from .incident_env import TASKS, IncidentHost
    from .live_smoke import NATIVE_LIMIT, SCENARIO, request_cap
    from .openai_agents.models import choose_models
    from .openai_agents.shielded import run_shielded

    settings = ProviderSettings(model=model)
    ledger = ProviderLedger(source=DOUBLE_SOURCE, max_requests=request_cap("conventional"),
                            max_output_tokens=settings.max_output_tokens)
    double = ProviderDouble(SimulatedInvestigator())
    m = choose_models(provider=ProviderSetup(settings, ledger, double.transport()))
    host = IncidentHost(TASKS[SCENARIO])
    result, report = run_shielded(TASKS[SCENARIO], m.heavy, model_label=m.label, max_turns=NATIVE_LIMIT,
                                  model_settings=m.settings, host=host)
    passed = result.status == "finished" and not host.write_ledger and not ledger.refused
    return {"provider_requests": [asdict(e) for e in ledger.exchanges],
            "tool_calls": [{"receipt": r.id, "tool": r.tool, "arguments": r.arguments, "status": r.status,
                            "proposed_by": r.proposed_by} for r in host.receipts],
            "termination": {"status": result.status}, "error": report.failure,
            "verdict": "PASS" if passed else "FAIL", "usage": ledger.usage_totals(),
            "billing": billing_totals([e.usage for e in ledger.exchanges], basis="synthetic: provider double"),
            "exit_gate": {"checks": len(report.verdicts), "returns": report.exit_returns,
                          "declared_citations": None if report.cited is None else list(report.cited)}}


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
                             "b_vs_a_batched_pct": _pct(usd.get("B"), usd.get(BATCHED)),
                             "b_vs_s_pct": _pct(usd.get("B"), usd.get(SHIELDED))})
    return rows


def build_report(frameworks: tuple[str, ...] = FRAMEWORKS, *, card: PriceCard = RECORDED_CARD,
                 stable_prefix_tokens: tuple[int, ...] = DEFAULT_STABLE_PREFIX_TOKENS,
                 min_cacheable_tokens: int = DEFAULT_MIN_CACHEABLE_TOKENS,
                 model: str | None = None) -> dict[str, Any]:
    from .live_smoke import DOUBLE_DEFAULT_MODEL, SCENARIO

    report: dict[str, Any] = {"label": STRUCTURAL_LABEL, "scenario": SCENARIO, "source": DOUBLE_SOURCE,
                              "real_inference": False, "price_card": asdict(card),
                              "min_cacheable_tokens": min_cacheable_tokens, "frameworks": {}}
    for framework in frameworks:
        arms, shapes_by_arm = [], {}
        specs = ARMS + (((SHIELDED, "shielded", False),) if framework in SHIELDED_FRAMEWORKS else ())
        for key, architecture, batch in specs:
            if key == SHIELDED:
                record = run_shielded_arm(model=model or DOUBLE_DEFAULT_MODEL)
            else:
                record = run_arm(framework, architecture, batch_reads=batch, model=model or DOUBLE_DEFAULT_MODEL)
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
            "breakeven_cache_read_multiplier_b_vs_a": _round(
                breakeven_cache_read_multiplier(shapes_by_arm["A"], shapes_by_arm["B"]), 3)}
    return report


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
                  f"{'A':>9} {'A-batched':>9} {'B':>9} {'S':>9} | {'B vs A':>7} {'B vs A-b':>8} {'B vs S':>7}"]
        for row in data["costs"]:
            minimum = row["min_cacheable_tokens"]
            usd = row["usd"]
            lines.append(
                f"{row['stable_prefix_tokens']:>13} | {row['assumption']:<66} | "
                f"{'n/a' if minimum is None else 'ignored' if minimum == 0 else minimum:>13} | "
                f"{_usd(usd.get('A')):>9} {_usd(usd.get(BATCHED)):>9} {_usd(usd.get('B')):>9} "
                f"{_usd(usd[SHIELDED]) if SHIELDED in usd else 'not run':>9} | "
                f"{_signed(row['b_vs_a_pct']):>7} {_signed(row['b_vs_a_batched_pct']):>8} "
                f"{_signed(row['b_vs_s_pct']) if SHIELDED in usd else 'not run':>7}")
        if multiplier is not None:
            lines.append(f"Input-only break-even: B's input costs less than A's only if a cache read costs more than "
                         f"{multiplier:.2f}x the fresh input price (no write premium, minimum ignored).")
        lines.append("")
    lines += ["How to read this: 'stable prefix' adds the same stable tokens (a larger system prompt and tool "
              "catalogue) to every request of every arm.",
              "'min cacheable' is a provider's minimum cacheable prompt length; below it nothing is read from cache.",
              "Latency is not modelled: fewer round trips is a real advantage over a sequential agent and none over "
              "one that batches.",
              "S is the shielded native agent (host rules, the unmodified agent loop, a host exit gate); it is "
              "'not run' where that arm is not implemented.",
              "Nothing here measures answer quality, real cost or real latency."]
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
    try:
        report = build_report(FRAMEWORKS if args.framework == "all" else (args.framework,), card=card,
                              stable_prefix_tokens=stable, min_cacheable_tokens=args.min_cacheable_tokens)
    except ImportError as exc:
        print(f"The cost-structure report runs the real SDK provider classes offline and needs them installed "
              f"({exc}).\n    pip install -r examples/architecture/requirements.txt", file=sys.stderr)
        return 2
    print(render(report))
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)
            handle.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
