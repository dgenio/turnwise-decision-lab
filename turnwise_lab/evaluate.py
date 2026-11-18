"""Offline contract replay. Not a model-quality or economic benchmark."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Callable

from .__main__ import ROOT, request_from_record
from .core import Plan, Request, Planner, shortlist
from .deciders import FixtureDecider


@dataclass(frozen=True)
class ReplaySummary:
    """Counts describe *synthetic route contracts*, not achieved task success."""
    arm: str
    total: int
    route_contract_matches: int
    route_contract_match_rate: float
    proposed_deep_tier_turns: int
    classifier_calls: int
    flow_paths: int
    tool_paths: int
    approval_holds: int
    cases: tuple[dict, ...]

    def as_dict(self) -> dict:
        return {"arm": self.arm, "total": self.total,
                "route_contract_matches": self.route_contract_matches,
                "route_contract_match_rate": self.route_contract_match_rate,
                "proposed_deep_tier_turns": self.proposed_deep_tier_turns,
                "classifier_calls": self.classifier_calls,
                "flow_paths": self.flow_paths, "tool_paths": self.tool_paths,
                "approval_holds": self.approval_holds, "cases": list(self.cases)}


def _deep_plan(request: Request) -> Plan:
    return Plan(path="llm", model_tier="deep", reasons=["always_deep_control"])


def _simple_rules(request: Request) -> Plan:
    """An intentionally clear, dependency-free reference policy.

    It never estimates probabilities or performs any external call.
    Side effects require host approval, regardless of inferred intent.
    """
    if request.direct_answer is not None:
        return Plan(path="direct", model_tier=None,
                    deterministic_answer=request.direct_answer,
                    reasons=["verified_host_answer"])
    for kind, candidates in (("flow", request.flows), ("tool", request.tools)):
        matches = shortlist(request.text + " " + request.task_summary, candidates, 1)
        if not matches:
            continue
        candidate = matches[0]
        if candidate.side_effect and candidate.id not in request.approved_actions:
            return Plan(path="hold", model_tier=None,
                        capability_id=candidate.id, approval_required=True,
                        reasons=["host_approval_required"])
        return Plan(path=kind, model_tier="standard" if kind == "tool" else None,
                    capability_id=candidate.id, reasons=["lexical_match"])
    return Plan(path="llm", model_tier="deep", reasons=["no_rule_match"])


def run_replay(rows: list[dict]) -> dict:
    """Compare reproducible planning outputs against *authored* fixture labels.

    FixtureDecider judgments and their labels come from the same fixture author.
    Consequently its route-match rate is not unbiased model accuracy.
    """
    if not rows or any("expected_label" not in row for row in rows):
        raise ValueError("Expected a nonempty fixture collection with authored labels")
    if len({row["text"] for row in rows}) != len(rows):
        raise ValueError("FixtureDecider keys require unique turn texts")
    fixture = FixtureDecider({row["text"]: row["mock_judgment"] for row in rows})
    strategies: dict[str, Callable[[Request], Plan]] = {
        "always_deep_sanity": _deep_plan,
        "simple_host_rules": _simple_rules,
        "fixture_planner_contract_only": Planner(fixture).plan,
    }
    arms = []
    for name, strategy in strategies.items():
        outcomes = []
        for row in rows:
            plan = strategy(request_from_record(row))
            label = "llm_deep" if plan.path == "llm" and plan.model_tier == "deep" else plan.path
            outcomes.append({"case_id": row["id"], "expected": row["expected_label"],
                             "actual": label, "match": row["expected_label"] == label,
                             "classifier_called": plan.decision_model_called,
                             "deep_tier_proposed": plan.model_tier == "deep",
                             "approval_hold": plan.path == "hold" and plan.approval_required})
        matched = sum(x["match"] for x in outcomes)
        arms.append(ReplaySummary(
            arm=name, total=len(outcomes), route_contract_matches=matched,
            route_contract_match_rate=round(matched / len(outcomes), 4),
            proposed_deep_tier_turns=sum(x["deep_tier_proposed"] for x in outcomes),
            classifier_calls=sum(x["classifier_called"] for x in outcomes),
            flow_paths=sum(x["actual"] == "flow" for x in outcomes),
            tool_paths=sum(x["actual"] == "tool" for x in outcomes),
            approval_holds=sum(x["approval_hold"] for x in outcomes),
            cases=tuple(outcomes)).as_dict())
    return {
        "schema_version": "replay-v1",
        "dataset": "authored synthetic fixture smoke cases",
        "limitations": [
            "FixtureDecider answers are keyed by the exact test turn and authored with the labels; no classifier quality can be inferred.",
            "Route-contract agreement is not end-to-end task correctness, tool argument quality or context completeness.",
            "Deep-tier counts are planning proposals, not actual model calls, money saved or latency.",
            "No hosted LiteLLM/Jev, vLLM, provider-native search or generative LLM was run.",
            "The always-deep control is a sanity baseline, not the competitive comparator.",
        ],
        "arms": arms,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, default=ROOT / "fixtures/scenarios.json")
    parser.add_argument("--output", type=Path, help="Write JSON evidence to an explicit file")
    args = parser.parse_args()
    results = run_replay(json.loads(args.fixtures.read_text(encoding="utf-8")))
    formatted = json.dumps(results, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(formatted, encoding="utf-8")
    else:
        print(formatted, end="")


if __name__ == "__main__":
    main()
