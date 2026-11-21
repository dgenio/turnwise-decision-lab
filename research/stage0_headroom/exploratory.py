"""POST HOC and exploratory. Not part of PROTOCOL.md, written after the evaluation run, not used for the verdict.

Two descriptive questions about the liberal oracle D1 on the primary analysis set (see RESULTS.md, "Exploratory"):

1. How much of the cost D1 removes is the text the model wrote next to a deleted tool call, billed as output?
   That text may be reasoning the agent needed, so this part of D1 is the most optimistic.
2. What does D1 remove when only read tools are deleted? D1 as frozen also deletes determinable write calls.

    python -I research/stage0_headroom/exploratory.py --tau-bench-root /path/to/tau-bench

Same data handling as headroom.py: JSON and Python literals are parsed, nothing from the clone is imported or run.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location("stage0_headroom", Path(__file__).resolve().with_name("headroom.py"))
h = importlib.util.module_from_spec(_SPEC)
sys.modules["stage0_headroom"] = h
_SPEC.loader.exec_module(h)


def describe(trajectories: list, rules: dict, card) -> dict:
    """P1 shares for D1 and its read-tool subset, and where the removed cost comes from."""
    original = with_d1 = with_d1_reads = 0.0
    narration = call = tool_turns = narrated = 0
    for traj in trajectories:
        d1 = h.selections(traj, rules[traj.domain])["D1"]
        reads = frozenset(i for i in d1 if h.is_read_tool(traj.messages[i].tool))
        original += h.cost(traj, card)
        with_d1 += h.cost(traj, card, deleted=d1)
        with_d1_reads += h.cost(traj, card, deleted=reads)
        for index, m in enumerate(traj.messages):
            if m.is_tool_turn:
                tool_turns += 1
                narrated += m.tokens > m.call_tokens
            if index in d1:
                narration += m.tokens - m.call_tokens
                call += m.call_tokens
    removed = original - with_d1
    if original <= 0 or removed <= 0:
        return {"trajectories": len(trajectories)}
    as_usd = card.output / 1_000_000
    return {"trajectories": len(trajectories),
            "d1": round(1 - with_d1 / original, 4),
            "d1_read_tools_only": round(1 - with_d1_reads / original, 4),
            "share_of_d1_removed_that_is_narration_output": round(narration * as_usd / removed, 4),
            "share_of_d1_removed_that_is_call_output": round(call * as_usd / removed, 4),
            "tool_turns": tool_turns, "tool_turns_with_narration": narrated}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--tau-bench-root", required=True, type=Path)
    p.add_argument("--json-out", type=Path)
    args = p.parse_args(argv)
    rules = h.mine_rules(h.load(args.tau_bench_root, "train")[0])
    primary = [t for t in h.load(args.tau_bench_root, "eval")[0] if t.reward == 1]
    card = h.CARDS[h.PRIMARY_CARD]
    scopes = {d: [t for t in primary if t.domain == d] for d in h.DOMAINS}
    scopes.update({f"{model}-{domain}": [t for t in primary if t.domain == domain and t.model == model]
                   for domain, model, _ in h.FILES.values()})
    report = {"label": "POST HOC, exploratory; not part of the protocol; not used for the verdict",
              "set": "eval-split trajectories with reward == 1", "card": h.PRIMARY_CARD,
              "scopes": {name: describe(ts, rules, card) for name, ts in scopes.items()}}
    print(report["label"])
    for name, s in report["scopes"].items():
        print(f"{name:<22} D1 {100 * s['d1']:.1f}% | D1 read tools only {100 * s['d1_read_tools_only']:.1f}% | "
              f"of the cost D1 removes: narration output {100 * s['share_of_d1_removed_that_is_narration_output']:.0f}%, "
              f"call output {100 * s['share_of_d1_removed_that_is_call_output']:.0f}% | "
              f"tool turns with narration {s['tool_turns_with_narration']}/{s['tool_turns']}")
    if args.json_out:
        args.json_out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
