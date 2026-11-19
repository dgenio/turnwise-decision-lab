"""Bounded smoke test of the four configurations against one model provider.

    python -m examples.architecture.live_smoke                 # rehearsal: local provider double, free, offline
    python -m examples.architecture.live_smoke --plan --provider openai --model M ...   # plan + worst case; sends nothing
    python -m examples.architecture.live_smoke --provider openai --model M \\
        --input-usd-per-mtok X --output-usd-per-mtok Y --authorize-usd Z --out results.json   # PAID inference

The same synthetic scenario ("investigate") runs through:

    openai-agents / conventional   Agent + Runner, native function tools
    openai-agents / turnwise       TurnwiseRuntime; each model call = Runner.run_sync(tool-less clone, StepOutcome)
    llamaindex    / conventional   FunctionAgent + FunctionTool
    llamaindex    / turnwise       TurnwiseRuntime; each model call = OpenAIResponses.structured_predict(StepOutcome)

with one explicitly selected model and identical model-level settings
(max_retries=0, timeout, max_output_tokens, and temperature / reasoning effort
if given). Every provider request goes through a ``ProviderLedger``: a request
cap per configuration (the framework's own limit: ``max_turns`` /
``max_iterations`` for the native agents, ``Budget.max_model_calls`` for
Turnwise), a spend cap for paid runs, and a record of what was sent and
returned. A request over a cap is refused *before* it is sent.

The report records the actual provider requests, tool calls (host receipts),
typed model outcomes, who controlled each step, termination and errors, and
grades each configuration PASS / FAIL / INCONCLUSIVE on *mechanism* checks
(see ``_checks``). It does not grade answer quality, cost or latency.

The provider double answers locally (no network, no key) and every output
says so; only ``--provider openai`` performs real inference, and it refuses to
start without OPENAI_API_KEY, positive prices and an explicit ``--authorize-usd``
that covers the planned worst case. A key alone is never treated as
authorisation. Settings the two frameworks would send differently are refused
(``parity_problems``). Exit status: 0 PASS, 1 FAIL, 2 usage error, 3
INCONCLUSIVE, 130 interrupted (the partial report is kept with ``--out``).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from urllib.parse import urlparse

from .incident_env import TASKS, TOOLS, IncidentHost
from .provider import (ASSUMED_MAX_INPUT_TOKENS, DOUBLE_SOURCE, REAL_SOURCE, Prices, ProviderLedger,
                       ProviderSettings, ProviderSetup, classify_from_wire)
from .provider_double import ProviderDouble
from .turnwise_core import Budget, describe_failure

SCENARIO = "investigate"
NATIVE_LIMIT = 10  # max_turns (Agents SDK) / max_iterations (LlamaIndex): the demo's values
TURNWISE_BUDGET = Budget()
CONFIGS = (("openai-agents", "conventional"), ("openai-agents", "turnwise"),
           ("llamaindex", "conventional"), ("llamaindex", "turnwise"))
HOST_TERMINALS = {"finished", "held", "answered_directly", "needs_clarification"}
REGISTERED = sorted(t.id for t in TOOLS)
DOUBLE_DEFAULT_MODEL = "gpt-6.1-sol"  # the rehearsal uses the proposed model id, so LlamaIndex's model table is checked


def request_cap(architecture: str) -> int:
    return NATIVE_LIMIT if architecture == "conventional" else TURNWISE_BUDGET.max_model_calls


def worst_case_usd(prices: Prices, settings: ProviderSettings, configs=CONFIGS) -> float:
    return sum(request_cap(arch) for _, arch in configs) * prices.worst_request(settings.max_output_tokens)


# ---------------------------------------------------------------- one configuration
def run_config(framework: str, architecture: str, setup: ProviderSetup) -> dict[str, Any]:
    task = TASKS[SCENARIO]
    host = IncidentHost(task)
    result = runtime = None
    error = None
    started = time.monotonic()
    try:
        if framework == "openai-agents":
            from .openai_agents import conventional, turnwise
            from .openai_agents.models import choose_models
            m = choose_models(provider=setup)
            if architecture == "conventional":
                result = conventional.run_conventional(task, m.heavy, model_label=m.label, max_turns=NATIVE_LIMIT,
                                                       model_settings=m.settings, host=host)
            else:
                result, runtime = turnwise.run_turnwise(task, m.heavy, m.light, model_label=m.label,
                                                        budget=TURNWISE_BUDGET, model_settings=m.settings,
                                                        host=host, ledger=setup.ledger)
        else:
            from .llamaindex import conventional, turnwise
            from .llamaindex.models import choose_llms
            m = choose_llms(provider=setup)
            if architecture == "conventional":
                result = conventional.run_conventional(task, m.heavy, model_label=m.label,
                                                       max_iterations=NATIVE_LIMIT, host=host)
            else:
                result, runtime = turnwise.run_turnwise(task, m.heavy, m.light, model_label=m.label,
                                                        budget=TURNWISE_BUDGET, host=host, ledger=setup.ledger)
    except (Exception, SystemExit) as exc:  # recorded and graded, never hidden; the matrix continues within caps
        wire = classify_from_wire(setup.ledger, 0)
        error = describe_failure(exc) + (f" [wire: {wire}]" if wire else "")
    ledger = setup.ledger
    record: dict[str, Any] = {
        "config": f"{framework} / {architecture}", "framework": framework, "architecture": architecture,
        "source": ledger.source, "model_requested": setup.settings.model,
        "expected_host": urlparse(setup.base_url).hostname,
        "models_reported": sorted({str(e.response.get("model")) for e in ledger.exchanges if e.response.get("model")}),
        "request_cap": ledger.max_requests,
        "provider_requests": [asdict(e) for e in ledger.exchanges],
        "refused_requests": list(ledger.refused),
        "tool_calls": [{"receipt": r.id, "tool": r.tool, "arguments": r.arguments, "status": r.status,
                        "proposed_by": r.proposed_by} for r in host.receipts],
        "typed_outcomes": [] if runtime is None else [
            {"id": o.id, "source": o.source, "kind": o.kind, "proposal": o.proposal.call() if o.proposal else None,
             "cited": list(o.cited), "note": o.note, "text": o.text[:300]} for o in runtime.outcomes],
        "policy_observed_outcome_ids": [] if runtime is None else [
            s.latest.id for s in runtime.snapshots if s.latest is not None],
        "adopted_proposal_ids": [] if runtime is None else list(runtime._adopted),
        "controllers": [] if result is None else [{"step": r.step, "controller": r.controller, "operation": r.short}
                                                  for r in result.rows],
        "termination": ({"status": result.status, "answer": result.answer[:400], "title": result.title}
                        if result is not None else {"status": "error"}),
        "error": error,
        "writes_executed": len(host.write_ledger),
        "usage": ledger.usage_totals(),
        "reported_cost_usd": ledger.reported_cost_usd(),
        "spend_bound_usd": ledger.spend_bound_usd(),
        "elapsed_s": round(time.monotonic() - started, 2),
    }
    controllers = [c["controller"] for c in record["controllers"]]
    record["controller_changes"] = sum(1 for a, b in zip(controllers, controllers[1:]) if a != b)
    record["checks"] = _checks(record, runtime)
    record["verdict"] = _verdict(record["checks"], error)
    return record


def _checks(rec: dict[str, Any], runtime: Any) -> list[dict[str, str]]:
    """Mechanism checks. 'fail' = the architecture claim is broken; 'inconclusive' = not exercised."""
    checks: list[dict[str, str]] = []

    def check(name: str, ok: bool | None, detail: str = "", *, else_: str = "fail") -> None:
        checks.append({"check": name, "result": "n/a" if ok is None else ("pass" if ok else else_), "detail": detail})

    reqs = [r["request"] for r in rec["provider_requests"]]
    responses = [r["response"] for r in rec["provider_requests"]]
    receipts = rec["tool_calls"]
    refusals = [o["refusal"] for r in responses for o in r.get("output", []) if o.get("type") == "refusal"]
    incomplete = [r.get("incomplete_details") for r in responses if r.get("status") == "incomplete"]
    check("no write executed", rec["writes_executed"] == 0, f"writes executed: {rec['writes_executed']}")
    # A framework may hide these (LlamaIndex's FunctionAgent ends a refused or truncated run as a normal,
    # empty completion): the wire record is what makes them visible.
    check("no refusal or incomplete response from the provider", not refusals and not incomplete,
          "; ".join([f"refusal: {r[:80]}" for r in refusals] + [f"incomplete: {i}" for i in incomplete]),
          else_="inconclusive")
    check("only the Responses endpoint was called, on the expected host",
          all(r["endpoint"].endswith("/responses") and r["host"] == rec["expected_host"]
              for r in rec["provider_requests"]),
          ", ".join(sorted({f"{r['host']}{r['endpoint']}" for r in rec["provider_requests"]})))
    check("every request used the selected model", all(r.get("model") == rec["model_requested"] for r in reqs),
          ", ".join(sorted({str(r.get("model")) for r in reqs})))
    check("provider requests within the cap", len(reqs) <= rec["request_cap"], f"{len(reqs)}/{rec['request_cap']}")
    check("at least one provider response", any(r["status"] is not None and r["status"] < 400
                                                for r in rec["provider_requests"]), else_="inconclusive")
    if rec["architecture"] == "conventional":
        check("native tool calling: all registered tools offered, no structured-output format",
              all(sorted(r.get("tools") or []) == REGISTERED and not r.get("text_format") for r in reqs),
              f"{len(reqs)} request(s)")
        check("every host receipt came from the model's own tool call",
              all(t["proposed_by"] == "llm" for t in receipts), ", ".join(t["proposed_by"] for t in receipts))
        check("the model chose at least one tool that the host executed",
              any(t["proposed_by"] == "llm" and t["status"] == "executed" for t in receipts), else_="inconclusive")
        check("the framework loop ended with a non-empty final answer",
              rec["termination"]["status"].startswith("completed") and bool(rec["termination"]["answer"].strip()),
              rec["termination"]["status"], else_="inconclusive")
        return checks
    check("no tools offered to the model in any Turnwise step", all(not r.get("tools") for r in reqs))
    check("every Turnwise step requested the StepOutcome JSON schema",
          all((r.get("text_format") or {}).get("type") == "json_schema" for r in reqs))
    if runtime is not None:
        attempts = len(reqs) + len(rec["refused_requests"])
        check("one provider request per policy-chosen model call (no hidden calls or retries)",
              attempts == runtime._model_calls, f"{attempts} request(s), {runtime._model_calls} model call(s)")
        check("Turnwise Core throughout (no handoff)", rec["termination"].get("title", "").startswith("Turnwise Core")
              and set(c["controller"] for c in rec["controllers"]) <= {"Turnwise policy"})
        check("every host receipt came from a policy decision",
              all(t["proposed_by"] == "turnwise_policy" for t in receipts))
        check("at least one valid typed model outcome", any(o.kind != "invalid" for o in runtime.outcomes),
              ", ".join(o.kind for o in runtime.outcomes), else_="inconclusive")
        failed = [o.note for o in runtime.outcomes if o.kind == "invalid"]
        checks.append({"check": "model calls that returned no usable outcome (the policy decided what to do next)",
                       "result": "note" if failed else "pass", "detail": "; ".join(f[:100] for f in failed)})
        returned = _proposals_returned_to_policy(runtime)
        check("each tool proposal went back to the policy before anything executed", returned,
              "no tool proposal in this run" if returned is None else "")
        check("terminated by a host-validated decision", rec["termination"]["status"] in HOST_TERMINALS,
              rec["termination"]["status"], else_="inconclusive")
    return checks


def _proposals_returned_to_policy(runtime: Any) -> bool | None:
    """For every model tool proposal: the policy's next snapshot shows it as the latest observation, and no host
    receipt was created between the model call and that snapshot."""
    proposals = [o for o in runtime.outcomes if o.proposal is not None]
    if not proposals:
        return None
    for outcome in proposals:
        i = next((k for k, s in enumerate(runtime.snapshots) if s.latest is not None and s.latest.id == outcome.id),
                 None)
        if i is None:  # the run ended (e.g. budget) right after this outcome; nothing executed on its say-so
            continue
        if i == 0 or len(runtime.snapshots[i].receipts) != len(runtime.snapshots[i - 1].receipts):
            return False
    return True


def _verdict(checks: list[dict[str, str]], error: str | None) -> str:
    results = {c["result"] for c in checks}
    if "fail" in results:
        return "FAIL"
    if error or "inconclusive" in results:
        return "INCONCLUSIVE"
    return "PASS"


# ---------------------------------------------------------------- the matrix
def run_matrix(settings: ProviderSettings, *, double: ProviderDouble | None = None, prices: Prices | None = None,
               authorize_usd: float | None = None, configs=CONFIGS, on_record=None) -> dict[str, Any]:
    """``double`` given: rehearsal against the local provider double. Otherwise: the real provider (paid).

    ``on_record(report)`` is called with the partial report after every configuration, so a caller can keep
    the record of requests already made even if the run is interrupted.
    """
    problems = parity_problems(settings)
    if problems:
        raise ValueError("; ".join(problems))
    source = DOUBLE_SOURCE if double is not None else REAL_SOURCE
    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": source, "real_inference": double is None, "scenario": SCENARIO, "task": TASKS[SCENARIO],
        "settings": asdict(settings), "prices_usd_per_mtok": None if prices is None else asdict(prices),
        "authorized_usd": authorize_usd,
        "worst_case_usd": None if prices is None else worst_case_usd(prices, settings, configs),
        "spend_bound_usd": 0.0 if prices is not None else None,
        "complete": False, "verdict": "INCOMPLETE", "configs": [],
    }
    spent = 0.0
    if on_record is not None:
        on_record(report)  # the header exists before the first request
    for framework, architecture in configs:
        usd_cap = None if authorize_usd is None else max(authorize_usd - spent, 0.0)
        ledger = ProviderLedger(source=source, max_requests=request_cap(architecture), prices=prices,
                                usd_cap=usd_cap, max_output_tokens=settings.max_output_tokens)
        setup = ProviderSetup(settings, ledger, None if double is None else double.transport())
        try:
            rec = run_config(framework, architecture, setup)
        except KeyboardInterrupt:
            # Keep what this configuration already sent, including a request cut off in flight (possibly billed).
            report["configs"].append({
                "config": f"{framework} / {architecture}", "framework": framework, "architecture": architecture,
                "source": source, "verdict": "INTERRUPTED", "error": "interrupted (KeyboardInterrupt)",
                "provider_requests": [asdict(e) for e in ledger.exchanges], "refused_requests": list(ledger.refused),
                "usage": ledger.usage_totals(), "spend_bound_usd": ledger.spend_bound_usd()})
            report["verdict"] = "INTERRUPTED"
            if prices is not None:
                report["spend_bound_usd"] = spent + (ledger.spend_bound_usd() or 0.0)
            if on_record is not None:
                on_record(report)
            raise
        report["configs"].append(rec)
        spent += rec["spend_bound_usd"] or 0.0
        if prices is not None:
            report["spend_bound_usd"] = spent
        if on_record is not None:
            on_record(report)
    verdicts = [r["verdict"] for r in report["configs"]]
    report["verdict"] = "FAIL" if "FAIL" in verdicts else "PASS" if set(verdicts) == {"PASS"} else "INCONCLUSIVE"
    report["complete"] = True
    return report


def render(report: dict[str, Any]) -> str:
    s = report["settings"]
    lines = [f"Turnwise live smoke | {report['source']}",
             f"model {s['model']} | scenario {report['scenario']!r} | retries 0 | timeout {s['timeout_s']:g}s | "
             f"max_output_tokens {s['max_output_tokens']} | temperature {s['temperature']} | "
             f"reasoning effort {s['reasoning_effort']}", ""]
    for r in report["configs"]:
        tools = ", ".join(f"{t['tool']}[{t['status']}; {t['proposed_by']}]" for t in r["tool_calls"]) or "-"
        outcomes = ", ".join(o["kind"] + (f"({o['proposal']})" if o["proposal"] else "") for o in r["typed_outcomes"])
        ctrl = {}
        for c in r["controllers"]:
            ctrl[c["controller"]] = ctrl.get(c["controller"], 0) + 1
        lines += [f"{r['config']:<29} {r['verdict']:<12} {len(r['provider_requests'])}/{r['request_cap']} requests  "
                  f"end: {r['termination']['status']}",
                  f"    tool calls  : {tools}",
                  f"    controllers : {', '.join(f'{k} x{v}' for k, v in ctrl.items()) or '-'}"
                  f" (controller changes: {r['controller_changes']})"]
        if r["architecture"] == "turnwise":
            lines.append(f"    outcomes    : {outcomes or '-'}")
        if r["error"]:
            lines.append(f"    error       : {r['error']}")
        lines += [f"    {c['result'].upper():<12} {c['check']}" + (f" -- {c['detail']}" if c["detail"] else "")
                  for c in r["checks"] if c["result"] != "pass"]
    usage = {k: sum(r["usage"].get(k, 0) for r in report["configs"]) for k in
             ("input_tokens", "output_tokens", "reasoning_tokens")}
    lines += ["", f"VERDICT: {report['verdict']}  ({', '.join(r['verdict'] for r in report['configs'])})",
              "usage: " + ", ".join(f"{k}={v}" for k, v in usage.items())
              + ("  (synthetic: provider double)" if not report["real_inference"] else "")]
    if report["spend_bound_usd"] is not None:
        lines.append(f"spend bound ${report['spend_bound_usd']:.4f} of ${report['authorized_usd'] or 0:.2f} "
                     f"authorised (worst case ${report['worst_case_usd']:.4f})")
    lines.append("Graded on mechanism only: not answer quality, cost or latency.")
    return "\n".join(lines)


def plan(settings: ProviderSettings, prices: Prices | None, configs=CONFIGS) -> str:
    caps = ", ".join(f"{f}/{a}={request_cap(a)}" for f, a in configs)
    total = sum(request_cap(a) for _, a in configs)
    out = [f"model {settings.model}; retries 0; timeout {settings.timeout_s:g}s per request; "
           f"max_output_tokens {settings.max_output_tokens}",
           f"request caps: {caps} (max {total} provider requests in total)"]
    if prices:
        out.append(f"planned worst case: {total} x (≤{ASSUMED_MAX_INPUT_TOKENS} input + ≤{settings.max_output_tokens} "
                   f"output tokens) at ${prices.input_per_mtok}/${prices.output_per_mtok} per MTok = "
                   f"${worst_case_usd(prices, settings, configs):.4f}")
        out.append("hard bound: before sending, each request is priced from its actual size (body bytes + its "
                   "max_output_tokens) and refused if it could take the spend past --authorize-usd")
    return "\n".join(out)


EXIT = {"PASS": 0, "FAIL": 1, "INCONCLUSIVE": 3, "INTERRUPTED": 130}  # 2 = usage error (argparse)


def parity_problems(settings: ProviderSettings) -> list[str]:
    """Settings the two frameworks would send differently, so the configurations would not share model settings.

    LlamaIndex (``OpenAIResponses``) decides by its own ``O1_MODELS`` list: for those models it sends
    ``reasoning`` and never ``temperature``; for others it never sends ``reasoning`` and always sends a
    temperature (default 0.1). The Agents SDK sends exactly what ``ModelSettings`` holds.
    """
    from llama_index.llms.openai.utils import O1_MODELS, openai_modelname_to_contextsize
    try:
        openai_modelname_to_contextsize(settings.model)
    except ValueError:
        return [f"llama-index-llms-openai does not support model {settings.model!r} (not in its model table)"]
    reasoning_model = settings.model in O1_MODELS
    problems = []
    if reasoning_model and settings.temperature is not None:
        problems.append(f"{settings.model} is a reasoning model for LlamaIndex, which never sends temperature to it; "
                        "drop --temperature")
    if not reasoning_model and settings.reasoning_effort:
        problems.append(f"LlamaIndex sends no reasoning settings for {settings.model} (not in its reasoning-model "
                        "list); drop --reasoning-effort")
    if not reasoning_model and settings.temperature is None:
        problems.append(f"set --temperature explicitly for {settings.model}: LlamaIndex otherwise sends its default "
                        "0.1 while the Agents SDK sends none")
    return problems


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--provider", choices=["double", "openai"], default="double")
    p.add_argument("--model", help=f"exact model id (required for openai; double default {DOUBLE_DEFAULT_MODEL})")
    p.add_argument("--reasoning-effort", default=None)
    p.add_argument("--temperature", type=float, default=None)
    p.add_argument("--max-output-tokens", type=int, default=2000)
    p.add_argument("--timeout", type=float, default=60.0, help="seconds per provider request")
    p.add_argument("--input-usd-per-mtok", type=float)
    p.add_argument("--output-usd-per-mtok", type=float)
    p.add_argument("--authorize-usd", type=float, help="maximum spend you authorise (openai only)")
    p.add_argument("--configs", default="all", help="comma list of framework/architecture, e.g. llamaindex/turnwise")
    p.add_argument("--plan", action="store_true", help="print the plan and worst case; send nothing")
    p.add_argument("--out", help="write the JSON report here (rewritten after every configuration)")
    args = p.parse_args(argv)

    configs = CONFIGS if args.configs == "all" else tuple(
        tuple(c.strip().split("/")) for c in args.configs.split(","))
    if not set(configs) <= set(CONFIGS):
        p.error(f"unknown configs; choose from {['/'.join(c) for c in CONFIGS]}")
    if args.provider == "openai" and not args.model:
        p.error("--provider openai needs an explicit --model")
    if not 0 < args.max_output_tokens <= 128_000 or not args.timeout > 0:
        p.error("--max-output-tokens must be in 1..128000 and --timeout positive")
    for name in ("input_usd_per_mtok", "output_usd_per_mtok", "authorize_usd"):
        value = getattr(args, name)
        if value is not None and not value > 0:
            p.error(f"--{name.replace('_', '-')} must be positive")
    settings = ProviderSettings(args.model or DOUBLE_DEFAULT_MODEL, timeout_s=args.timeout,
                                max_output_tokens=args.max_output_tokens, temperature=args.temperature,
                                reasoning_effort=args.reasoning_effort)
    problems = parity_problems(settings)
    if problems:
        p.error("; ".join(problems))
    prices = (Prices(args.input_usd_per_mtok, args.output_usd_per_mtok)
              if args.input_usd_per_mtok is not None and args.output_usd_per_mtok is not None else None)
    print(plan(settings, prices, configs), file=sys.stderr)
    if args.plan:
        return 0
    if args.provider == "openai":
        import os
        if prices is None or args.authorize_usd is None:
            p.error("paid runs need --input-usd-per-mtok, --output-usd-per-mtok and --authorize-usd")
        worst = worst_case_usd(prices, settings, configs)
        if worst > args.authorize_usd:
            p.error(f"the worst case ${worst:.4f} exceeds --authorize-usd {args.authorize_usd:.2f}; lower the caps "
                    "or raise the authorisation")
        if not os.environ.get("OPENAI_API_KEY"):
            p.error("OPENAI_API_KEY is not set")
    double = None if args.provider == "openai" else ProviderDouble()
    _preflight(settings, simulated=double is not None)

    def save(report: dict[str, Any]) -> None:
        if args.out:
            with open(args.out, "w", encoding="utf-8") as fh:
                json.dump(report, fh, indent=2, sort_keys=True)
                fh.write("\n")

    partial: dict[str, Any] = {}

    def keep(report: dict[str, Any]) -> None:
        partial.update(report)
        save(report)

    try:
        report = run_matrix(settings, double=double, prices=prices, authorize_usd=args.authorize_usd,
                            configs=configs, on_record=keep)
    except KeyboardInterrupt:  # keep the record of whatever was already sent (and possibly billed)
        partial["verdict"] = "INTERRUPTED"
        save(partial)
        print("interrupted; partial report " + (f"written to {args.out}" if args.out else "not saved (no --out)"),
              file=sys.stderr)
        return EXIT["INTERRUPTED"]
    save(report)
    print(render(report))
    return EXIT[report["verdict"]]


def _preflight(settings: ProviderSettings, *, simulated: bool = False) -> None:
    """Build every provider model before any request (sends nothing: the ledger's cap is 0). An unsupported model
    id fails here, in rehearsal and paid mode alike."""
    from .llamaindex.models import choose_llms
    from .openai_agents.models import choose_models
    for choose in (choose_models, choose_llms):
        ledger = ProviderLedger(source=DOUBLE_SOURCE if simulated else REAL_SOURCE, max_requests=0)
        choose(provider=ProviderSetup(settings, ledger, ProviderDouble().transport() if simulated else None))


if __name__ == "__main__":
    raise SystemExit(main())
