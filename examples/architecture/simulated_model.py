"""SIMULATED model behaviour for offline runs. This is NOT inference.

``SimulatedInvestigator`` is a small deterministic stand-in for a capable
generative model. It exists so that both control architectures can be run and
tested without credentials, network access or provider cost. It is plugged
into each framework through that framework's *own official test double*:

* OpenAI Agents SDK: ``agents.testing.ScriptedModel`` + ``ModelStep.respond``;
* LlamaIndex: ``llama_index.core.llms.mock.MockFunctionCallingLLM``.

The framework itself (its agent loop, tool dispatch, structured output
parsing) runs for real; only the text a model would have generated is
simulated. Every trace printed by the demo says so.

It reads only what a real model would be given -- the instructions, the user
task, the tool results the framework fed back, or the Turnwise context packet
-- and reacts to them. It never sees the expected trace, labels or fixtures.
Its behaviour is *the same* under both architectures: what it wants next
depends on the evidence in front of it, not on who is in control.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable

from turnwise_lab.world import named_services

SIMULATED_LABEL = "SIMULATED model (deterministic stand-in; no inference performed)"

# The evidence this simulated investigator wants before answering each kind of question.
_NEEDS = {
    "diagnostic": ("error_trend", "recent_deploys", "validate_config"),
    "status": ("service_health",),
}
_DIAGNOSTIC = re.compile(r"\b(explain|cause[ds]?|why|because|responsible|behind)\b", re.IGNORECASE)
_STATUS = re.compile(r"\b(healthy|health|status|up|down)\b", re.IGNORECASE)
_ROLLBACK = re.compile(r"\b(roll\s*back|revert)\b", re.IGNORECASE)
_FACT_WORDS = {"severity": "severity", "commander": "incident_commander", "started": "incident_start",
               "status page": "status_page", "incident id": "incident_id"}
_INCIDENT_RECORD = re.compile(r"Incident record \(host-verified\): (\{.*\})")


@dataclass(frozen=True)
class NativeAction:
    """What the model emits in a native tool-calling loop: one tool call, or a final answer."""

    kind: str  # "tool_call" | "answer"
    tool: str | None = None
    arguments: dict[str, Any] | None = None
    text: str = ""


class SimulatedInvestigator:
    """Deterministic, evidence-reactive stand-in for a capable model.

    ``rogue_write=True`` makes it additionally attempt an *unrequested*
    rollback once it has gathered evidence, to show that the host -- not the
    model or the policy -- decides whether a side effect may happen.
    """

    name = "simulated-capable-model"

    def __init__(self, *, rogue_write: bool = False):
        self.rogue_write = rogue_write

    # ------------------------------------------------ native tool-calling loop
    def native_step(self, *, instructions: str, task: str, tool_results: Iterable[str],
                    tools: Iterable[str]) -> NativeAction:
        """One turn of a conventional agent: call another tool, or answer."""
        seen = [_parse_result(r) for r in tool_results]
        attempted = {r["tool"] for r in seen if r}
        evidence = {r["tool"]: r for r in seen if r and r.get("status") == "executed"}
        available = set(tools)
        services = named_services(task)
        intent = _intent(task)
        if intent == "rollback":
            if "rollback_deploy" not in attempted and services and "rollback_deploy" in available:
                return NativeAction("tool_call", "rollback_deploy", {"service": services[0]})
            return NativeAction("answer", text=_rollback_answer(seen, services))
        if intent == "fact":
            return NativeAction("answer", text=_fact_answer(task, _record_from(instructions)))
        if not services:
            return NativeAction("answer", text="Which service do you mean?")
        svc = services[0]
        for tool in _NEEDS.get(intent, ()):
            if tool not in attempted and tool in available:
                return NativeAction("tool_call", tool, {"service": svc})
        if self.rogue_write and "rollback_deploy" not in attempted and "rollback_deploy" in available:
            return NativeAction("tool_call", "rollback_deploy", {"service": svc})
        text, _ = _compose(intent, svc, evidence)
        return NativeAction("answer", text=text)

    # ------------------------------------------- one Turnwise-controlled model step
    def typed_step(self, packet: dict[str, Any]) -> dict[str, Any]:
        """One bounded model call under Turnwise: return a typed StepOutcome, execute nothing."""
        task = str(packet.get("task", ""))
        receipts = [r for r in packet.get("evidence", []) if isinstance(r, dict)]
        evidence = {r["tool"]: r for r in receipts if r.get("status") == "executed"}
        may_propose = {t.get("name") for t in packet.get("tools_you_may_propose", []) if isinstance(t, dict)}
        services = named_services(task)
        intent = _intent(task)
        if intent in {"rollback", "fact"} or not services:
            return _outcome("needs_evidence", "This step cannot answer the task from the evidence provided.")
        svc = services[0]
        for tool in _NEEDS.get(intent, ()):
            if tool not in evidence:
                if tool in may_propose:
                    return _outcome("tool_proposal", f"I need {tool} evidence before I can answer.",
                                    tool=tool, arguments={"service": svc})
                return _outcome("needs_evidence", f"I need {tool} evidence, which I may not request here.")
        if self.rogue_write:
            # Proposes a write it was never asked for, whether or not it was offered.
            return _outcome("tool_proposal", "Roll the deploy back now.", tool="rollback_deploy",
                            arguments={"service": svc})
        text, cited = _compose(intent, svc, evidence)
        return _outcome("answer_candidate", text, cited=cited)


# ---------------------------------------------------------------- helpers
def _intent(task: str) -> str:
    if _ROLLBACK.search(task) and not _DIAGNOSTIC.search(task):
        return "rollback"
    if any(w in task.lower() for w in _FACT_WORDS):
        return "fact"
    if _DIAGNOSTIC.search(task):
        return "diagnostic"
    if _STATUS.search(task):
        return "status"
    return "other"


def _parse_result(text: str) -> dict[str, Any] | None:
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("tool"), str) else None


def _record_from(instructions: str) -> dict[str, Any]:
    match = _INCIDENT_RECORD.search(instructions or "")
    return json.loads(match.group(1)) if match else {}


def _fact_answer(task: str, record: dict[str, Any]) -> str:
    for word, key in _FACT_WORDS.items():
        if word in task.lower() and key in record:
            return f"The current incident ({record.get('incident_id', 'unknown')}) has {key.replace('_', ' ')} {record[key]}."
    return "I do not have that information."


def _rollback_answer(seen: list[dict[str, Any] | None], services: tuple[str, ...]) -> str:
    receipt = next((r for r in seen if r and r["tool"] == "rollback_deploy"), None)
    if receipt is None:
        return "Which service should be rolled back?" if not services else "I could not request the rollback."
    if receipt["status"] == "held_for_approval":
        return (f"The rollback of {receipt['arguments'].get('service')} is held for human approval. "
                "It has NOT been executed.")
    return f"The rollback was not performed: {receipt.get('reason', receipt['status'])}."


def _compose(intent: str, svc: str, evidence: dict[str, dict[str, Any]]) -> tuple[str, list[str]]:
    """Answer text derived only from the evidence in front of the model, plus the receipts it used."""
    if intent == "status" and "service_health" in evidence:
        r = evidence["service_health"]
        h = r["facts"][f"health:{svc}"]
        return (f"{svc} is {h['status']}: error rate {h['error_rate_pct']}%, p95 {h['p95_ms']} ms "
                f"(observed {h['observed_at']})."), [r["receipt"]]
    if intent != "diagnostic" or not {"error_trend", "recent_deploys"} <= set(evidence):
        return "I do not have enough evidence to answer.", []
    trend = evidence["error_trend"]["facts"][f"trend:{svc}"]
    deploys = evidence["recent_deploys"]["facts"][f"deploys:{svc}"]["deploys"]
    cited = [evidence["error_trend"]["receipt"], evidence["recent_deploys"]["receipt"]]
    before, after = trend["error_rate_before_pct"], trend["error_rate_after_pct"]
    if not deploys:
        return (f"No: there is no recent {svc} deployment on record, so a deployment cannot explain "
                f"the error rate ({after}%)."), cited
    d = deploys[0]
    if after < before * 1.5 or after - before < 0.5:
        return (f"Unlikely: {svc}'s error rate barely changed around deploy {d['id']} "
                f"({before}% -> {after}%)."), cited
    text = (f"Plausibly yes. {svc}'s error rate rose from {before}% to {after}% around deploy {d['id']} "
            f"({d['at']}: {d['change']}).")
    if "validate_config" in evidence:
        cfg = evidence["validate_config"]["facts"][f"config:{svc}"]
        cited.append(evidence["validate_config"]["receipt"])
        if cfg["drifted"]:
            text += " Configuration validation shows drift from the approved baseline: " + ", ".join(
                f"{k} {v['current']} (baseline {v['baseline']})" for k, v in cfg["drifted"].items()) + "."
        else:
            text += " Its configuration matches the approved baseline."
    text += " The timing is consistent with the deploy causing the errors, but this is correlation, not proof."
    return text, cited


def _outcome(kind: str, text: str, *, tool: str | None = None, arguments: dict[str, Any] | None = None,
             cited: list[str] | None = None) -> dict[str, Any]:
    return {"kind": kind, "text": text, "tool": tool,
            "arguments_json": json.dumps(arguments, sort_keys=True) if arguments is not None else None,
            "cited_receipts": list(cited or [])}
