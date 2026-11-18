"""Run *real local Python* tool/flow handlers; show explicit LLM handoff.

No remote calls, no model inference, no side effects. This is an executable
closed-world harness, not a synthetic provider-output claim.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import argparse
import json

from .core import Capability, Request, Source
from .evaluate import _simple_rules
from .runtime import HostIdentity, LocalHarness, RegisteredAction

ROOT = Path(__file__).resolve().parents[1]


def _health(_: dict) -> dict:
    return {"service": "checkout-api", "status": "degraded", "error_rate_pct": 6.4,
            "observed_at": "2026-11-01T12:05:00Z", "provenance": "synthetic-health-v1"}


def _baseline(args: dict) -> dict:
    observed = args.get("actual", {"timeout_seconds": 12, "retries": 2})
    expected = {"timeout_seconds": 8, "retries": 2}
    return {"matches_baseline": observed == expected,
            "changed_keys": sorted(k for k in expected if observed.get(k) != expected[k]),
            "provenance": "synthetic-deployment-v1"}


def _publish(_: dict) -> dict:
    # Demonstration guard: even if called, publishing is never implemented.
    raise RuntimeError("publish is not implemented in this offline exhibit")


def actions() -> dict[str, RegisteredAction]:
    return {
        "fetch_service_health": RegisteredAction("fetch_service_health", "Fetch service health", _health),
        "validate_deployment_baseline": RegisteredAction("validate_deployment_baseline", "Validate deployment baseline", _baseline),
        "publish_incident_report": RegisteredAction("publish_incident_report", "Publish incident report", _publish, side_effect=True, required_permission="publish"),
    }


def cases() -> list[dict]:
    root = Source("rollback_cause", "checkout failure caused by rollback timing",
                  "Rollback was delayed by a timeout mismatch during checkout-api deployment.")
    health = Source("checkout_health", "checkout service degraded request error rate",
                    "Checkout service status degraded; measured error rate 6.4 percent.")
    distraction = Source("ux_palette", "design colors icon theme", "Theme palette uses slate and sand.")
    return [
        {"id": "01", "turn": "Show the incident reference number", "direct_answer": "INC-SYN-042", "route": "direct"},
        {"id": "02", "turn": "Validate deployment baseline settings", "flows": (Capability("validate_deployment_baseline", "Validate deployment baseline settings"),), "route": "flow", "args": {"actual": {"timeout_seconds": 12, "retries": 2}}},
        {"id": "03", "turn": "Fetch service health status", "tools": (Capability("fetch_service_health", "Fetch service health status"),), "route": "tool"},
        {"id": "04", "turn": "Explain why the checkout service failed after the release", "sources": (root, health, distraction), "route": "llm"},
        {"id": "05", "turn": "Publish incident report", "flows": (Capability("publish_incident_report", "Publish incident report", side_effect=True),), "route": "hold"},
        {"id": "06", "turn": "Does that rollback explain the outage?", "task_summary": "Prior turns checked checkout health and deployment baseline", "sources": (root, health, distraction), "route": "llm"},
    ]


def run_demo() -> dict:
    harness = LocalHarness(actions())
    identity = HostIdentity(principal="demo-reader", permissions=frozenset({"read"}))
    records = []
    for i, case in enumerate(cases(), 1):
        req = Request(text=case["turn"], direct_answer=case.get("direct_answer"),
                      tools=case.get("tools", ()), flows=case.get("flows", ()),
                      sources=case.get("sources", ()),
                      task_summary=case.get("task_summary", ""), conversation_turns=i)
        plan = _simple_rules(req)
        receipt = harness.run(req, plan, identity=identity, arguments=case.get("args", {}))
        records.append({"turn_id": case["id"], "user_request": case["turn"],
                        "expected_route": case["route"], "proposed_route": plan.path,
                        "receipt": receipt.as_json()})
    return {"schema_version": "live-local-v1", "kind": "actual local Python handler execution",
            "remote_provider_calls": 0, "generative_model_calls": 0,
            "notes": ["Four paths demonstrated with real local execution/handoff; LLM reasoning is not generated.",
                      "All records and timestamps are invented for this self-contained educational fixture.",
                      "SHA-256 receipts are unsigned reproduction fingerprints, not security attestations."],
            "turns": records}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    data = json.dumps(run_demo(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(data, encoding="utf-8")
    else:
        print(data, end="")


if __name__ == "__main__":
    main()
