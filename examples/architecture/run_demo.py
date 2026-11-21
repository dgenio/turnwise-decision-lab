"""Run the same agent twice -- conventional, then under Turnwise Core -- and print who controlled each step.

    python -m examples.architecture.run_demo                         # OpenAI Agents SDK, main scenario
    python -m examples.architecture.run_demo --framework llamaindex
    python -m examples.architecture.run_demo --scenario all --handoff
    python -m examples.architecture.run_demo --shielded              # also arm S: the shielded native agent

Offline: the frameworks run for real, the model is SIMULATED, and nothing is
sent over the network. Real-provider runs go only through the bounded smoke
test, ``python -m examples.architecture.live_smoke`` (request, tool, timeout and
spend caps; an explicit spend authorisation; see the guide).
"""
from __future__ import annotations

import argparse
from importlib.metadata import PackageNotFoundError, version

from .incident_env import TASKS
from .policies import HandoffPolicy
from .trace import RunResult, render, render_side_by_side

FRAMEWORKS = {"openai-agents": ("OpenAI Agents SDK", "openai-agents"),
              "llamaindex": ("LlamaIndex", "llama-index-core")}


def _load(framework: str):
    try:
        if framework == "openai-agents":
            from .openai_agents.conventional import run_conventional
            from .openai_agents.models import choose_models as choose
            from .openai_agents.turnwise import run_turnwise
        else:
            from .llamaindex.conventional import run_conventional
            from .llamaindex.models import choose_llms as choose
            from .llamaindex.turnwise import run_turnwise
    except ImportError as exc:
        if (exc.name or "").split(".")[0] not in {"agents", "llama_index", "pydantic"}:
            raise
        raise SystemExit(f"{FRAMEWORKS[framework][0]} is missing or not the pinned version ({exc.name}). "
                         "Run: pip install -r examples/architecture/requirements.txt") from exc
    return run_conventional, choose, run_turnwise


LIVE_REDIRECT = ("run_demo is offline only. Real-provider runs go through the bounded smoke test, which caps "
                 "model calls, tool calls, timeouts and spend and needs an explicit authorisation: "
                 "python -m examples.architecture.live_smoke --help")


SHIELDED_ONLY = "Arm S (the shielded native agent) is implemented for the OpenAI Agents SDK pair only."


def run_pair(framework: str, task: str, *, live: bool = False, handoff: bool,
             checklist_null: bool = False, shielded: bool = False) -> list[RunResult]:
    """Fresh models and a fresh host for every run, so runs cannot influence each other. Simulated model only."""
    if live:
        raise SystemExit(LIVE_REDIRECT)
    run_conventional, choose, run_turnwise = _load(framework)
    m = choose()
    results = [run_conventional(task, m.heavy, model_label=m.label)]
    m = choose()
    results.append(run_turnwise(task, m.heavy, m.light, model_label=m.label)[0])
    if handoff:
        m = choose()
        results.append(run_turnwise(task, m.heavy, m.light, model_label=m.label, policy=HandoffPolicy())[0])
    if checklist_null:
        m = choose()  # A+P uses a fresh native model, same task/tools/host policy as A
        results.append(run_conventional(task, m.heavy, model_label=m.label, checklist=True))
    if shielded:  # arm S: the native agent keeps its loop; the host acts before it, on every call and at exit
        if framework != "openai-agents":
            raise SystemExit(SHIELDED_ONLY)
        from .openai_agents.shielded import run_shielded
        m = choose()
        results.append(run_shielded(task, m.heavy, model_label=m.label)[0])
    return results


def header(framework: str, scenario: str) -> str:
    name, dist = FRAMEWORKS[framework]
    try:
        ver = version(dist)
    except PackageNotFoundError:
        ver = "not installed"
    mode = "OFFLINE: the framework code is real; the model is SIMULATED (no inference, no network, no cost)."
    return "\n".join([
        "#" * 100,
        f"# Turnwise architecture demo | framework: {name} {ver} | scenario: {scenario}",
        f"# {mode}",
        "# A and B share the task, tools, data, host, permissions, base instructions and capable model.",
        "# What differs is who decides each next operation, and so what the model is shown (see the guide's parity notes).",
        "#" * 100])


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--framework", choices=[*FRAMEWORKS, "all"], default="openai-agents")
    parser.add_argument("--scenario", choices=[*TASKS, "all"], default="investigate")
    parser.add_argument("--handoff", action="store_true",
                        help="also run the HANDOFF_AGENT contrast (a different architecture from Turnwise Core)")
    parser.add_argument("--checklist-null", action="store_true",
                        help="also run A+P, native agent with frozen checklist prompt (offline, not an efficacy result)")
    parser.add_argument("--shielded", action="store_true",
                        help="also run arm S, the shielded native agent: host rules, the unmodified agent loop, a "
                             "host exit gate (OpenAI Agents SDK only; NOT Turnwise Core; offline, not an efficacy result)")
    parser.add_argument("--brief", action="store_true", help="print only the side-by-side controller view")
    parser.add_argument("--live", action="store_true",
                        help="not supported here: real-provider runs go through examples.architecture.live_smoke")
    args = parser.parse_args(argv)
    if args.live:  # before anything is built or sent
        raise SystemExit(LIVE_REDIRECT)

    frameworks = list(FRAMEWORKS) if args.framework == "all" else [args.framework]
    if args.shielded and frameworks != ["openai-agents"]:  # before anything is run
        raise SystemExit(SHIELDED_ONLY)
    scenarios = list(TASKS) if args.scenario == "all" else [args.scenario]
    blocks: list[str] = []
    for framework in frameworks:
        for scenario in scenarios:
            results = run_pair(framework, TASKS[scenario], handoff=args.handoff,
                               checklist_null=args.checklist_null, shielded=args.shielded)
            parts = [header(framework, scenario)]
            if not args.brief:
                parts += [render(r) for r in results]
            parts.append(render_side_by_side(results[0], results[1]))
            if args.brief and args.shielded:
                s = results[-1]
                parts.append("S shielded native agent (SIMULATED, NOT Turnwise Core, no efficacy claim): "
                             f"{s.status}; " + "; ".join(f"{k}={v}" for k, v in s.counts.items()))
            if args.brief and args.checklist_null:
                null = results[-2] if args.shielded else results[-1]
                parts.append(f"A+P checklist-prompted native null (SIMULATED, no efficacy claim): "
                             f"{null.status}; model_calls={null.counts['model_calls']}; "
                             f"host_tool_requests={null.counts['host_tool_requests']}")
            blocks.append("\n\n".join(parts))
    print("\n\n".join(blocks))


if __name__ == "__main__":
    main()
