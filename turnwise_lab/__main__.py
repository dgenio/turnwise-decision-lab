"""Run the synthetic, no-credentials demonstration."""
import argparse
import json
from pathlib import Path
from . import Capability, FixtureDecider, JevDecider, Planner, Request, Source

ROOT = Path(__file__).resolve().parent.parent

def request_from_record(row: dict) -> Request:
    return Request(text=row["text"], task_summary=row.get("task_summary", ""),
                   sources=tuple(Source(**s) for s in row.get("sources", [])),
                   tools=tuple(Capability(**c) for c in row.get("tools", [])),
                   flows=tuple(Capability(**c) for c in row.get("flows", [])),
                   sensitivity=row.get("sensitivity", "public"),
                   approved_actions=frozenset(row.get("approved_actions", [])),
                   context_budget_chars=row.get("context_budget_chars", 480),
                   direct_answer=row.get("direct_answer"),
                   allow_external_decider=row.get("allow_external_decider", False))

def main() -> None:
    ap = argparse.ArgumentParser(description="Synthetic turn-level gate/route/context demo. Never executes tools.")
    ap.add_argument("--backend", choices=["fixture", "jev"], default="fixture")
    ap.add_argument("--case", help="Run only this case id")
    ap.add_argument("--confirm-public-data", action="store_true", help="Explicitly permit external Jev calls on the bundled synthetic/public case")
    args = ap.parse_args()
    data = json.loads((ROOT / 'fixtures' / 'scenarios.json').read_text())
    decider = FixtureDecider({r["text"]: r["mock_judgment"] for r in data}) if args.backend == "fixture" else JevDecider()
    planner = Planner(decider)
    for row in data:
        if args.case and row["id"] != args.case:
            continue
        req = request_from_record(row)
        if args.backend == 'jev' and args.confirm_public_data:
            from dataclasses import replace
            req = replace(req, allow_external_decider=True)
        plan = planner.plan(req)
        print(json.dumps({"case_id": row["id"], "expected_label": row.get("expected_label"),
                          "plan": plan.as_json()}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
