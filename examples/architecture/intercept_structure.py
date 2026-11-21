"""How the model is asked, held apart from who controls: arms A, A', B and B' for k = 1, 2, 3 (#87).

    python -m examples.architecture.intercept_structure
    python -m examples.architecture.intercept_structure --stable-prefix-tokens 20000 --json-out intercept.json

SIMULATED, structural, offline. Runs the showcase task against the local provider double (no network, no key,
no inference) through the real OpenAI Agents SDK provider classes and reports what each arm *sends*:

* **A**    the conventional agent; the simulated model asks for one tool per response;
* **A'**   the same agent when the model asks for its evidence reads in one response;
* **S**    the same agent, shielded: host rules and the evidence the host's contract requires first, then the
           unmodified agent loop, then a host exit gate. The agent keeps control, so NOT Turnwise Core (#88);
* **B**    Turnwise Core: one typed ``StepOutcome`` per model call, no tools attached;
* **B'**   the same loop and policy with the native-intercept port: a real tools field, an append-only
           conversation, every tool call returned to the policy as a proposal. Reported twice, because whether
           a model batches is not something this repository can know: once with the simulated model asking
           for one tool per response (**B' seq**), once with it asking for all of them (**B' batch**).

**k** is the number of evidence reads the *model* chooses under the Turnwise arms. The task needs three reads.
The policy's playbook reads ``3 - k`` of them first, so k = 1 is the default ``TriagePolicy`` and k = 3 is a
playbook that reads nothing. Arms A and A' have no policy: the model always chooses all three, so they do not
vary with k. Arm S does not vary either: its host rules always read the two roles the evidence contract
requires, which leaves the model one read (the same split as k = 1).

What this is not: a measurement. Token counts are the double's synthetic ``bytes // 4``, replies are
simulated, and a real model may batch differently, ignore the step contract, or behave differently when a call
is declined. It shows request counts and prefix reuse under stated conditions, nothing about quality.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from typing import Any

from .cost_accounting import (ASSUMPTIONS, STRUCTURAL_LABEL, PriceCard, RequestShape, shapes_from_exchanges,
                              structural_cost)
from .cost_structure import (ARM_NAMES, DEFAULT_MIN_CACHEABLE_TOKENS, RECORDED_CARD, SHIELDED, batching_label,
                             run_arm, run_shielded_arm)
from .provider import DOUBLE_SOURCE, ProviderLedger, ProviderSettings, ProviderSetup
from .provider_double import ProviderDouble
from .simulated_model import SimulatedInvestigator

KS = (1, 2, 3)
PLAYBOOK_ROLES = ("symptom", "change")  # the default TriagePolicy playbook for a causal question, in order
NATIVE = (("A", "conventional agent", False), ("A'", "conventional agent, batched reads", True))
TURNWISE = (("B", "Turnwise Core (typed step, no tools)", "typed", False),
            ("B' seq", "B' native-intercept port, model asks for one tool per response", "intercept", False),
            ("B' batch", "B' native-intercept port, model asks for its reads in one response", "intercept", True))
DEFAULT_STABLE_PREFIX_TOKENS = 5_000


def policy_for(k: int):
    """``TriagePolicy`` with a playbook that leaves ``k`` of the three evidence reads to the model."""
    from .policies import TriagePolicy

    roles = PLAYBOOK_ROLES[:3 - k]
    return type("TriagePolicyPlaybook", (TriagePolicy,), {
        "PLAYBOOK": {**TriagePolicy.PLAYBOOK, "diagnostic": roles},
        "name": f"TriagePolicy, playbook reads {len(roles)} of 3 (k={k})"})()


def run_turnwise_arm(port: str, *, k: int, batch_reads: bool, model: str) -> dict[str, Any]:
    """One Turnwise arm on the showcase against a fresh provider double. Graded on mechanism only."""
    from .incident_env import TASKS, IncidentHost
    from .live_smoke import SCENARIO, TURNWISE_BUDGET, request_cap
    from .openai_agents.models import choose_models
    from .openai_agents.native_intercept import run_native_intercept
    from .openai_agents.turnwise import run_turnwise

    settings = ProviderSettings(model=model)
    ledger = ProviderLedger(source=DOUBLE_SOURCE, max_requests=request_cap("turnwise"),
                            max_output_tokens=settings.max_output_tokens)
    double = ProviderDouble(SimulatedInvestigator(batch_reads=batch_reads))
    m = choose_models(provider=ProviderSetup(settings, ledger, double.transport()))
    host = IncidentHost(TASKS[SCENARIO])
    runner = run_native_intercept if port == "intercept" else run_turnwise
    result, runtime = runner(TASKS[SCENARIO], m.heavy, m.light, model_label=m.label, policy=policy_for(k),
                             budget=TURNWISE_BUDGET, model_settings=m.settings, host=host, ledger=ledger)
    proposals = [o for o in runtime.outcomes if o.proposal is not None]
    adopted = set(runtime._adopted)
    passed = (result.status == "finished" and not host.write_ledger and not ledger.refused
              # every model-proposed read that ran was adopted by the policy first, and nothing else ran
              and all(r.proposed_by == "turnwise_policy" for r in host.receipts)
              and not getattr(runtime.model, "unexpected_invocations", []))
    return {"provider_requests": [asdict(e) for e in ledger.exchanges],
            "termination": result.status, "verdict": "PASS" if passed else "FAIL",
            "policy_decisions": len(runtime.snapshots), "model_proposals": len(proposals),
            "proposals_adopted": len([o for o in proposals if o.id in adopted]),
            "host_tool_calls": [r.tool for r in host.receipts if r.executed]}


def _arm_entry(key: str, name: str, k: int | None, shapes: list[RequestShape], extra: dict[str, Any], *,
               card: PriceCard, stable: int, minimum: int) -> dict[str, Any]:
    later = [s.shared_share for s in shapes[1:]]
    return {"arm": key, "name": name, "k": k, "requests": len(shapes),
            "tool_call_batching": batching_label(shapes),
            "max_tool_calls_per_response": max((s.tool_calls for s in shapes), default=0),
            "request_chars": [s.chars for s in shapes],
            "shared_prefix_share": [round(s.shared_share, 3) for s in shapes],
            "min_later_prefix_share": round(min(later), 3) if later else None,
            "input_tokens_total": (None if any(s.input_tokens is None for s in shapes)
                                   else sum(s.input_tokens for s in shapes)),
            "usd": {a: structural_cost(shapes, card, a, stable_prefix_tokens=stable, min_cacheable_tokens=minimum)
                    for a in ASSUMPTIONS}, **extra}


def build_report(*, card: PriceCard = RECORDED_CARD, stable_prefix_tokens: int = DEFAULT_STABLE_PREFIX_TOKENS,
                 min_cacheable_tokens: int = DEFAULT_MIN_CACHEABLE_TOKENS, model: str | None = None) -> dict[str, Any]:
    from .live_smoke import DOUBLE_DEFAULT_MODEL, SCENARIO

    model = model or DOUBLE_DEFAULT_MODEL
    common = dict(card=card, stable=stable_prefix_tokens, minimum=min_cacheable_tokens)
    native = []
    for key, name, batch in NATIVE:
        record = run_arm("openai-agents", "conventional", batch_reads=batch, model=model)
        native.append(_arm_entry(key, name, None, shapes_from_exchanges(record["provider_requests"]), {
            "verdict": record["verdict"], "termination": record["termination"]["status"],
            "host_tool_calls": [t["tool"] for t in record["tool_calls"] if t["status"] == "executed"]}, **common))
    record = run_shielded_arm(model=model)  # arm S next to A and Core in every comparison table (#88)
    native.append(_arm_entry(SHIELDED, ARM_NAMES[SHIELDED], None, shapes_from_exchanges(record["provider_requests"]), {
        "verdict": record["verdict"], "termination": record["termination"]["status"],
        "host_tool_calls": [t["tool"] for t in record["tool_calls"] if t["status"] == "executed"]}, **common))
    by_k = {}
    for k in KS:
        arms = []
        for key, name, port, batch in TURNWISE:
            record = run_turnwise_arm(port, k=k, batch_reads=batch, model=model)
            shapes = shapes_from_exchanges(record.pop("provider_requests"))
            arms.append(_arm_entry(key, name, k, shapes, record, **common))
        by_k[str(k)] = arms
    return {"label": STRUCTURAL_LABEL, "scenario": SCENARIO, "source": DOUBLE_SOURCE, "real_inference": False,
            "framework": "openai-agents", "price_card": asdict(card), "stable_prefix_tokens": stable_prefix_tokens,
            "min_cacheable_tokens": min_cacheable_tokens, "native": native, "turnwise_by_k": by_k,
            "predeclared_offline_check": predeclared_check(by_k)}


def predeclared_check(by_k: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """The offline halves of #87's pre-declared outcomes, evaluated as written, per simulated batching behaviour.

    Adopt B' "if offline it needs fewer provider requests than B whenever k >= 2 and reuses at least as much
    prefix". Keep B "if B' shows no request or token advantage at k >= 2". The live halves (invalid-outcome
    rate, executed-without-decision events, task success) cannot be evaluated offline.
    """
    out: dict[str, Any] = {}
    for variant in ("B' seq", "B' batch"):
        fewer, reuse, tokens = [], [], []
        for k in (2, 3):
            arms = {a["arm"]: a for a in by_k[str(k)]}
            ours, theirs = arms[variant], arms["B"]
            fewer.append(ours["requests"] < theirs["requests"])
            reuse.append((ours["min_later_prefix_share"] or 0.0) >= (theirs["min_later_prefix_share"] or 0.0))
            tokens.append(None if None in (ours["input_tokens_total"], theirs["input_tokens_total"])
                          else ours["input_tokens_total"] < theirs["input_tokens_total"])
        fewer_tokens = None if None in tokens else all(tokens)
        out[variant] = {"fewer_requests_at_every_k_ge_2": all(fewer), "at_least_as_much_prefix_reuse": all(reuse),
                        "fewer_input_tokens_at_every_k_ge_2": fewer_tokens,
                        "adopt_condition_met": all(fewer) and all(reuse),
                        # "no request or token advantage": unknown tokens leave this unknown, never False
                        "keep_b_condition_met": (None if fewer_tokens is None and not all(fewer)
                                                 else not (all(fewer) or bool(fewer_tokens)))}
    adopt = {v["adopt_condition_met"] for v in out.values() if isinstance(v, dict)}
    keep = {v["keep_b_condition_met"] for v in out.values() if isinstance(v, dict)}
    if adopt == {True}:
        reading = "the offline half of ADOPT B' is met under both simulated batching behaviours; the live half is untested"
    elif keep == {True}:
        reading = "the offline half of KEEP B is met under both simulated batching behaviours"
    else:
        reading = ("the offline half of ADOPT B' is met only when the simulated model batches its tool calls, and "
                   "the offline half of KEEP B is not met in either case. Whether a model batches is something only a "
                   "real model can show: INCONCLUSIVE offline; both ports go forward as arms")
    out["reading"] = reading
    return out


def render(report: dict[str, Any]) -> str:
    card, stable = report["price_card"], report["stable_prefix_tokens"]
    lines = ["How the model is asked, held apart from who controls | " + report["source"], report["label"],
             f"scenario {report['scenario']!r} | framework {report['framework']} | price card: input "
             f"${card['input_per_mtok']:g}, cached input ${card['cached_input_per_mtok']:g}, cache write "
             f"${card['cache_write_per_mtok']:g}, output ${card['output_per_mtok']:g} per MTok ({card['source']})",
             f"cost columns: the same stable {stable}-token prefix added to every request of every arm; minimum "
             f"cacheable length {report['min_cacheable_tokens']} tokens. Arithmetic, NOT a cost measurement.", ""]
    header = (f"{'arm':<9} | {'k':>3} | {'requests':>8} | {'calls/response':>14} | {'prefix of previous':<22} | "
              f"{'policy decisions':>16} | {'no caching':>10} | {'cache reads':>11} | {'reads + write price':>19}")

    def row(arm: dict[str, Any]) -> str:
        shares = ", ".join("-" if i == 0 else f"{s:.0%}" for i, s in enumerate(arm["shared_prefix_share"]))
        usd = arm["usd"]
        k = arm["k"] if arm["k"] is not None else "1*" if arm["arm"] == SHIELDED else "all"
        return (f"{arm['arm']:<9} | {k:>3} | {arm['requests']:>8} | "
                f"{arm['max_tool_calls_per_response']:>14} | {shares:<22} | "
                f"{arm.get('policy_decisions', 'none'):>16} | {_usd(usd[ASSUMPTIONS[0]]):>10} | "
                f"{_usd(usd[ASSUMPTIONS[1]]):>11} | {_usd(usd[ASSUMPTIONS[2]]):>19}"
                + ("" if arm["verdict"] == "PASS" else f"   NOTE: mechanism verdict {arm['verdict']} ({arm['termination']})"))

    lines += ["=== arms where the agent keeps its own loop (no policy). A and A': the model chooses all three "
              "reads. S: the host reads two first ===", header]
    lines += [row(a) for a in report["native"]]
    for k, arms in report["turnwise_by_k"].items():
        lines += ["", f"=== k = {k}: the model chooses {k} of the three reads; the policy's playbook reads "
                      f"{3 - int(k)} first ===", header]
        lines += [row(a) for a in arms]
    check = report["predeclared_offline_check"]
    lines += ["", "Pre-declared outcomes in #87, offline halves only. ADOPT B': fewer provider requests than B "
                  "whenever k >= 2, and at least as much prefix reuse. KEEP B: no request or token advantage at k >= 2."]
    for variant in ("B' seq", "B' batch"):
        c = check[variant]
        lines.append(f"  {variant:<9}: fewer requests: {_yes(c['fewer_requests_at_every_k_ge_2'])}; prefix reuse at "
                     f"least B's: {_yes(c['at_least_as_much_prefix_reuse'])}; fewer input tokens: "
                     f"{_yes(c['fewer_input_tokens_at_every_k_ge_2'])} | ADOPT B' met: "
                     f"{_yes(c['adopt_condition_met'])}; KEEP B met: {_yes(c['keep_b_condition_met'])}")
    lines += [f"  Reading: {check['reading']}.", "",
              "'calls/response' is the most tool calls any one model response carried. Under B a model call carries "
              "none: it can only propose one, as text.",
              "S is the shielded native agent; '1*' means its host rules read two of the three first, by the "
              "evidence contract, not by a policy.",
              "Under B' every tool call came back to the policy as a proposal; the policy adopted it and the host "
              "executed it. No model call executed anything.",
              "Nothing here measures answer quality, real cost, real latency, or how a real model behaves."]
    return "\n".join(lines)


def _usd(value: float | None) -> str:
    return "unknown" if value is None else f"{value:.5f}"


def _yes(value: bool | None) -> str:
    return "unknown" if value is None else "yes" if value else "no"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input-usd-per-mtok", type=float, default=RECORDED_CARD.input_per_mtok)
    p.add_argument("--cached-input-usd-per-mtok", type=float, default=RECORDED_CARD.cached_input_per_mtok)
    p.add_argument("--cache-write-usd-per-mtok", type=float, default=RECORDED_CARD.cache_write_per_mtok)
    p.add_argument("--output-usd-per-mtok", type=float, default=RECORDED_CARD.output_per_mtok)
    p.add_argument("--min-cacheable-tokens", type=int, default=DEFAULT_MIN_CACHEABLE_TOKENS)
    p.add_argument("--stable-prefix-tokens", type=int, default=DEFAULT_STABLE_PREFIX_TOKENS,
                   help="stable tokens (system prompt, tool catalogue) added to every request for the cost columns")
    p.add_argument("--json-out", help="also write the report as JSON here")
    args = p.parse_args(argv)
    prices = (args.input_usd_per_mtok, args.cached_input_usd_per_mtok, args.cache_write_usd_per_mtok,
              args.output_usd_per_mtok)
    recorded = (RECORDED_CARD.input_per_mtok, RECORDED_CARD.cached_input_per_mtok,
                RECORDED_CARD.cache_write_per_mtok, RECORDED_CARD.output_per_mtok)
    try:
        card = RECORDED_CARD if prices == recorded else PriceCard(*prices, source="command line")
        if args.min_cacheable_tokens < 0 or args.stable_prefix_tokens < 0:
            raise ValueError("token counts must be nonnegative")
    except ValueError as exc:
        p.error(str(exc))
    try:
        report = build_report(card=card, stable_prefix_tokens=args.stable_prefix_tokens,
                              min_cacheable_tokens=args.min_cacheable_tokens)
    except ImportError as exc:
        print(f"This report runs the real SDK provider classes offline and needs them installed ({exc}).\n"
              "    pip install -r examples/architecture/requirements.txt", file=sys.stderr)
        return 2
    print(render(report))
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)
            handle.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
