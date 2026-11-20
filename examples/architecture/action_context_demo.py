"""Three small, entirely offline #55 traces; no SDK keys or paid inference.

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
from turnwise_lab.world import named_services


class QueryExtractionPolicy:
    """A didactic light-extraction route: a model formulates ONE free-text argument.

    The only argument a model may formulate here is a ``query`` for a registered
    read tool (``search_docs``). Service targets are never model-resolved: the
    host parses them from the user's own text, and its FINISH evidence gate
    relies on that. Host registration/argument/permission checks stay independent.
    """
    name = "query-extraction-policy (offline only)"

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
                proposal, spec = latest.proposal, s.tool(latest.proposal.tool)
                if (spec is not None and not spec.side_effect and spec.param == "query"
                        and not s.attempted(proposal.tool, proposal.arguments)):
                    return Decision(op_for(spec), "model formulated a free-text query; host validates it",
                                    target=proposal.tool, arguments=dict(proposal.arguments),
                                    adopted_from=latest.id)
                return Decision(Op.CLARIFY, "proposal is not a free-text read this route may adopt",
                                message="What should I look up?")
            return Decision(Op.CLARIFY, "model could not formulate a grounded query",
                            message="What should I look up?")
        executed = tuple(r.id for r in s.receipts if r.executed)
        if executed:
            return Decision(Op.CALL_LIGHT, "summarize executed host evidence", context=executed)
        query_tools = tuple(t.id for t in s.tools if t.param == "query" and not t.side_effect)
        return Decision(Op.CALL_LIGHT, "formulate one free-text read argument; do not execute it",
                        may_propose=query_tools)


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
            services = named_services(packet["task"])
            if not services:
                return {"kind": "needs_evidence", "text": "The request names nothing to look up.",
                        "tool": None, "arguments_json": None, "cited_receipts": []}
            query = json.dumps({"query": f"{services[0]} error rate runbook"})
            return {"kind": "tool_proposal", "text": "A runbook search answers this request.",
                    "tool": "search_docs", "arguments_json": query, "cited_receipts": []}
        if "summarize-evidence" in selected and packet.get("evidence"):
            receipt = packet["evidence"][0]
            titles = ", ".join(sorted(v["title"] for v in receipt["facts"].values()))
            return {"kind": "answer_candidate", "text": f"Relevant documents: {titles}.",
                    "tool": None, "arguments_json": None,
                    "cited_receipts": [receipt["receipt"]]}
        return self.brain.typed_step(packet)

    def handoff(self, task_text, max_turns):
        raise AssertionError("native agent handoff is not part of this experiment")


LIGHT_TASK = "What do our runbooks say about checkout errors?"


def run_case(name: str, task: str, policy):
    port = OfflineModelPort()
    runtime = ScopedContextRuntime(IncidentHost(task), policy, port)
    result = runtime.run()
    return result, runtime, port


def main() -> None:
    cases = (
        ("deterministic host answer", TASKS["severity"], TriagePolicy(), "answered_directly"),
        ("light argument extraction", LIGHT_TASK, QueryExtractionPolicy(), "finished"),
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
