"""Three small, entirely offline #55 traces; no SDK keys or paid inference.

    python -m examples.architecture.action_context_demo

These share the existing synthetic IncidentHost and TurnwiseRuntime mechanism.
The model port is intentionally scripted: traces prove selection/control, NOT
reasoning quality, cost, throughput, safety generalization or correctness.
"""
from __future__ import annotations

import json

from .incident_env import IncidentHost, TASKS
from .policies import TriagePolicy
from .scoped_runtime import ScopedContextRuntime
from .simulated_model import SimulatedInvestigator
from .turnwise_core import Decision, ModelOutcome, Op


class AliasExtractionPolicy:
    """A didactic, typed light-extraction route for a known synthetic alias.

    It may adopt the proposal only if the original user request supplies the
    explicit alias 'check-out'; it never fabricates an ambiguous referent.
    Host registration/argument/permission checks are still independent.
    """
    name = "alias-extraction-policy (offline only)"

    def decide(self, s):
        if s.last_rejection:
            return Decision(Op.HOLD, "host rejected a proposal",
                            message="Unresolved: invalid module selection or host action.")
        if s.requested_writes:
            return Decision(Op.HOLD, "this read-only route does not accept writes",
                            message="An approval path, not the extraction demo, is required.")
        latest = s.latest
        if isinstance(latest, ModelOutcome):
            if latest.kind == "answer_candidate":
                return Decision(Op.FINISH, "host checks citations from final candidate", candidate=latest.id)
            if latest.kind == "tool_proposal" and latest.proposal is not None:
                proposal = latest.proposal
                if ("check-out" in s.task.lower() and proposal.tool == "service_health"
                        and proposal.arguments == {"service": "checkout"}):
                    return Decision(Op.CALL_TOOL, "model extracted the explicit alias; host validates",
                                    target="service_health", arguments={"service": "checkout"},
                                    adopted_from=latest.id)
                return Decision(Op.CLARIFY, "proposal not grounded in the original user's referent",
                                message="Which service do you mean?")
            return Decision(Op.CLARIFY, "model could not resolve a grounded referent",
                            message="Which service do you mean?")
        executed = tuple(r.id for r in s.receipts if r.executed)
        if executed:
            return Decision(Op.CALL_LIGHT, "summarize executed host evidence", context=executed)
        return Decision(Op.CALL_LIGHT, "extract one read-only tool argument; do not execute it",
                        may_propose=("service_health",))


class OfflineModelPort:
    label = "SIMULATED (scripted #55 selection paths; no inference)"
    describe = "framework-free typed model double"

    def __init__(self):
        self.packets = []
        self.brain = SimulatedInvestigator()

    def call(self, tier, packet):
        self.packets.append((tier, packet))
        selected = {m["id"] for m in packet.get("instruction_modules", [])}
        if "extract-arguments" in selected:
            if "check-out" not in packet["task"].lower():
                return {"kind": "needs_evidence", "text": "The service is ambiguous.",
                        "tool": None, "arguments_json": None, "cited_receipts": []}
            return {"kind": "tool_proposal", "text": "The user explicitly wrote check-out.",
                    "tool": "service_health", "arguments_json": '{"service":"checkout"}',
                    "cited_receipts": []}
        if "summarize-status" in selected and packet.get("evidence"):
            receipt = packet["evidence"][0]
            return {"kind": "answer_candidate", "text":
                    "The host reports: " + json.dumps(receipt["facts"], sort_keys=True),
                    "tool": None, "arguments_json": None,
                    "cited_receipts": [receipt["receipt"]]}
        return self.brain.typed_step(packet)

    def handoff(self, task_text, max_turns):
        raise AssertionError("native agent handoff is not part of this experiment")


def run_case(name: str, task: str, policy):
    port = OfflineModelPort()
    runtime = ScopedContextRuntime(IncidentHost(task), policy, port)
    result = runtime.run()
    return result, runtime, port


def main() -> None:
    cases = (
        ("deterministic host answer", TASKS["severity"], TriagePolicy(), "answered_directly"),
        ("light argument extraction", "Is check-out healthy right now?", AliasExtractionPolicy(), "finished"),
        ("capable-tier decision (simulated)", TASKS["investigate"], TriagePolicy(), "finished"),
    )
    print("OFFLINE scripted architecture demonstration: no real models, network or billing.")
    for name, task, policy, expected in cases:
        result, runtime, port = run_case(name, task, policy)
        if result.status != expected or result.writes_executed != 0:
            raise AssertionError(f"{name}: unexpected run status {result.status!r}, writes {result.writes_executed}")
        print(f"\n{name}: {result.status} | model calls {len(port.packets)} | writes {result.writes_executed}")
        for row in runtime.rows:
            print(f"  {row.short}")
        for audit in runtime.module_audits:
            print("  modules loaded:", ", ".join(x["id"] for x in audit["included"]))
            print("  modules excluded:", ", ".join(
                f"{x['id']}({x['reason']})" for x in audit["excluded"]))
            print("  receipts loaded:", audit["evidence_included"])
            print("  receipts excluded:", audit["evidence_excluded"])
    print("\nMechanism only; no model-quality, token or performance claim.")


if __name__ == "__main__":
    main()
