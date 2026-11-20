"""Four small, entirely offline #55 traces; no SDK keys or paid inference.

    python -m examples.architecture.action_context_demo

These share the existing synthetic IncidentHost and TurnwiseRuntime mechanism.
The model port is intentionally scripted: traces prove selection/control, NOT
reasoning quality, cost, throughput, safety generalization or correctness.
"""
from __future__ import annotations

import json

from .incident_env import IncidentHost, TASKS
from .policies import TriagePolicy, op_for
from .scoped_runtime import ScopedContextRuntime
from .simulated_model import SimulatedInvestigator
from .turnwise_core import Decision, ModelOutcome, Op


class AliasExtractionPolicy:
    """A didactic light-extraction route: ask a cheap model for one read's argument.

    The light model may propose a registered read with an extracted ``service``.
    The policy adopts it only if that service is one the HOST resolved from the
    user's own words (``snapshot.services``). A model's resolution of an alias
    such as "check-out" is a suggestion, never a referent: the policy asks the
    user instead. (The host's FINISH gate would refuse an answer about a service
    the user's words do not name anyway; see the tests.) Host registration,
    argument and permission checks remain independent of this policy.
    """
    name = "alias-extraction-policy (offline only)"

    def decide(self, s):
        if s.last_rejection:
            return Decision(Op.HOLD, f"the host rejected the previous decision ({s.last_rejection})",
                            message="Unresolved: the host did not accept the policy's last decision; see the trace.")
        if s.requested_writes:
            return Decision(Op.HOLD, "this read-only route does not accept writes",
                            message="An approval path, not the extraction demo, is required.")
        latest = s.latest
        if isinstance(latest, ModelOutcome):
            if latest.kind == "answer_candidate":
                return Decision(Op.FINISH, "host checks citations from final candidate", candidate=latest.id)
            if latest.kind == "tool_proposal" and latest.proposal is not None:
                proposal, spec = latest.proposal, s.tool(latest.proposal.tool)
                service = proposal.arguments.get("service") if set(proposal.arguments) == {"service"} else None
                if spec is not None and not spec.side_effect and service in s.services:
                    return Decision(op_for(spec), "the extracted argument is a service the user named; host validates",
                                    target=spec.id, arguments={"service": service}, adopted_from=latest.id)
                # Model-written names are never relayed in the run's message.
                return Decision(Op.CLARIFY, "the proposal's referent is not one the host resolved from the user's words",
                                message="Which service do you mean? Please use its registered name.")
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
            # Scripted "extraction": resolves the alias check-out, or an exact registered name.
            task = packet["task"].lower()
            service = "checkout" if "check-out" in task else next(
                (n for n in ("checkout", "payments", "search", "auth") if n in task), None)
            if service is None:
                return {"kind": "needs_evidence", "text": "The service is ambiguous.",
                        "tool": None, "arguments_json": None, "cited_receipts": []}
            return {"kind": "tool_proposal", "text": f"The request appears to mean {service}.",
                    "tool": "service_health", "arguments_json": json.dumps({"service": service}),
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
        ("light status summary", TASKS["status"], TriagePolicy(), "finished"),
        ("light argument extraction, alias the host cannot resolve", "Is check-out healthy right now?",
         AliasExtractionPolicy(), "needs_clarification"),
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
