"""Run the same task under each configuration and print the per-step traces.

    python -m turnwise_lab.control_demo                 # deterministic, network-free
    python -m turnwise_lab.control_demo --remediation   # the model also proposes an unrequested rollback
    python -m turnwise_lab.control_demo --json          # machine-readable traces

The native configurations run only if their optional framework is installed
(``pip install "turnwise-decision-lab[demo-openai]"`` and/or ``[demo-llamaindex]``);
each is skipped otherwise. The Turnwise configuration needs no dependency.
"""
from __future__ import annotations

import argparse
import json

from .model import IncidentModel
from .trace import render
from .turnwise import run_turnwise

REQUEST = "Could the latest checkout deployment explain the increase in errors?"


def run_all(request: str = REQUEST, *, remediation: bool = False) -> list:
    """Each configuration gets a fresh host and the same model rules; nothing is shared between runs."""
    from . import native_llamaindex, native_openai
    runs = []
    if native_openai.available():
        runs.append(native_openai.run_native_openai(request, model=IncidentModel(propose_remediation=remediation)))
    if native_llamaindex.available():
        runs.append(native_llamaindex.run_native_llamaindex(request, model=IncidentModel(propose_remediation=remediation)))
    runs.append(run_turnwise(request, model=IncidentModel(propose_remediation=remediation)))
    return runs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--request", default=REQUEST)
    ap.add_argument("--remediation", action="store_true", help="scripted model also proposes an unrequested rollback")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    runs = run_all(args.request, remediation=args.remediation)
    if args.json:
        print(json.dumps([r.as_json() for r in runs], indent=1, sort_keys=True))
        return 0
    from . import native_llamaindex, native_openai
    for mod, extra, label in ((native_openai, "demo-openai", "OpenAI Agents SDK"),
                              (native_llamaindex, "demo-llamaindex", "LlamaIndex")):
        if not mod.available():
            print(f"({label} configuration skipped: pip install \"turnwise-decision-lab[{extra}]\")")
    print("\n\n".join(render(r) for r in runs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
