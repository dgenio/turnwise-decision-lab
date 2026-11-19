"""Run the same agent twice -- conventional, then under Turnwise Core -- and print who controlled each step.

    python -m examples.architecture.run_demo                         # OpenAI Agents SDK, main scenario
    python -m examples.architecture.run_demo --framework llamaindex
    python -m examples.architecture.run_demo --scenario all --handoff

Offline by default: the frameworks run for real, the model is SIMULATED, and
nothing is sent over the network. ``--live`` switches to real OpenAI models
(needs OPENAI_API_KEY, costs money; never run or tested by the authors or CI).
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


def run_pair(framework: str, task: str, *, live: bool, handoff: bool) -> list[RunResult]:
    """Fresh models and a fresh host for every run, so runs cannot influence each other."""
    run_conventional, choose, run_turnwise = _load(framework)
    m = choose(live=live)
    results = [run_conventional(task, m.heavy, model_label=m.label)]
    m = choose(live=live)
    results.append(run_turnwise(task, m.heavy, m.light, model_label=m.label)[0])
    if handoff:
        m = choose(live=live)
        results.append(run_turnwise(task, m.heavy, m.light, model_label=m.label, policy=HandoffPolicy())[0])
    return results


def header(framework: str, scenario: str, live: bool) -> str:
    name, dist = FRAMEWORKS[framework]
    try:
        ver = version(dist)
    except PackageNotFoundError:
        ver = "not installed"
    mode = ("LIVE: real model calls (provider costs apply)." if live else
            "OFFLINE: the framework code is real; the model is SIMULATED (no inference, no network, no cost).")
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
    parser.add_argument("--brief", action="store_true", help="print only the side-by-side controller view")
    parser.add_argument("--live", action="store_true",
                        help="use real OpenAI models (explicit opt-in; costs money; never run or tested)")
    args = parser.parse_args(argv)

    frameworks = list(FRAMEWORKS) if args.framework == "all" else [args.framework]
    scenarios = list(TASKS) if args.scenario == "all" else [args.scenario]
    if args.live:  # fail before any paid call if any selected framework cannot run live
        for framework in frameworks:
            _load(framework)[1](live=True)
    blocks: list[str] = []
    for framework in frameworks:
        for scenario in scenarios:
            results = run_pair(framework, TASKS[scenario], live=args.live, handoff=args.handoff)
            parts = [header(framework, scenario, args.live)]
            if not args.brief:
                parts += [render(r) for r in results]
            parts.append(render_side_by_side(results[0], results[1]))
            blocks.append("\n\n".join(parts))
    print("\n\n".join(blocks))


if __name__ == "__main__":
    main()
