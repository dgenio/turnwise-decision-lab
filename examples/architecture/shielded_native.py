"""Arm S: a shielded native agent. NOT Turnwise Core.

The capable agent keeps its own loop and chooses every operation. The host acts only at the boundaries::

    before the agent   host rules: a requested write is held, a pure record question is answered from the
                       verified record, a service-scoped question that names no service is asked back, and
                       the evidence the host's own contract already requires is read.            No model.
    during the loop    every tool call the agent makes goes through ``IncidentHost.execute``, as in arm A.
    at exit            the finished answer is checked against host receipts. A rejected answer goes back to
                       the agent with the reason, up to a bound, and is otherwise withheld.

This is the "simple host rules + the same capable agent" null that ``AGENTS.md`` requires next to any
Turnwise Core comparison (#88). There is no per-step controller here, by construction: this module imports
no policy, runtime, snapshot or decision type. The only symbol taken from ``turnwise_core`` is the host-side
claim screen, so both architectures use the identical regex. A test enforces both statements.

Nothing here decides authority. Write intent, argument validation, the tool budget, receipts and the evidence
contract are the existing ``IncidentHost``; the prefetch reuses ``required_evidence_roles`` and the registry's
role metadata, so the arm adds no heuristic of its own about what a question needs.

This module is framework-neutral and stdlib-only. A framework supplies the native agent run
(``openai_agents/shielded.py``).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .incident_env import INCIDENT_RECORD, TOOLS, TOOLS_BY_ID, IncidentHost, Receipt, required_evidence_roles
from .turnwise_core import _ACTION_CLAIM  # the shared host-side claim screen (a regex); nothing else

ARM = "Shielded native agent (arm S; the agent controls its own loop; NOT Turnwise Core)"
HOST_RULE = "host rule (before the agent)"  # controller label in traces
EXIT_GATE = "host exit gate"
PROPOSER = "host_rule"  # Receipt.proposed_by for operations the host chose itself

ACCEPTED = frozenset({"finished", "answered_directly"})  # terminal statuses that carry an accepted answer

# Which host-verified record answers which pure record question. A copy of the cues in ``policies.py`` (this
# module must not import a policy); a test asserts the two agree, so the null is not weakened.
_FACT_CUES = tuple((re.compile(pattern, re.IGNORECASE), key) for pattern, key in (
    (r"\bstatus page\b", "status_page"), (r"\bseverity\b", "severity"), (r"\bcommander\b", "incident_commander"),
    (r"\bincident id\b", "incident_id"), (r"\b(start|started|began)\b", "incident_start")))


@dataclass(frozen=True)
class Disposition:
    """A run the host settled before the agent was called. No model was involved."""

    status: str  # held | answered_directly | needs_clarification
    answer: str
    rule: str  # write | record | clarification
    receipts: tuple[Receipt, ...] = ()


@dataclass(frozen=True)
class ExitVerdict:
    accepted: bool
    status: str  # finished | insufficient_evidence | unverified_action_claim
    why: str  # host-authored; safe to show the user
    detail: str = ""  # may quote ids the agent declared; for the trace and for the agent, never for the user


@dataclass
class ShieldReport:
    """What happened in one arm-S run, for tests and reports. Counts are observed, never asserted."""

    status: str
    path: str  # host_write_rule | host_record | host_clarification | native_agent
    native_called: bool = False
    native_answer: str | None = None  # the agent's last raw answer, kept for inspection even when withheld
    model_calls: int = 0  # every model response in every attempt, as the SDK reports them
    prefetched: tuple[str, ...] = ()  # receipt ids the host read before the agent ran
    cited: tuple[str, ...] | None = None  # receipt ids the agent declared (typed final answer only)
    verdicts: list[ExitVerdict] = field(default_factory=list)  # one per exit check, in order
    exit_returns: int = 0  # how many times a rejected answer went back to the agent
    failure: str | None = None


def fact_key(task: str) -> str | None:
    return next((key for cue, key in _FACT_CUES if cue.search(task) and key in INCIDENT_RECORD), None)


def host_rules(host: IncidentHost) -> Disposition | None:
    """Settle the run without a model where the host can. ``None`` means: the agent is needed."""
    task = host.user_request
    # 1. A write the *user* asked for. Authority is host-parsed from the user's own text; the host holds it.
    if host.requested_writes:
        receipts = tuple(host.execute(tool, {"service": svc}, proposed_by=PROPOSER)
                         for tool, svc in sorted(host.requested_writes))
        text = " ".join(
            f"{r.call()} awaits human approval. It has NOT been executed." if r.status == "held_for_approval"
            else f"{r.call()} was not carried out: {r.reason}." for r in receipts)
        return Disposition("held", text, "write", receipts)
    roles, services = required_evidence_roles(task), host.services_named_by_user()
    # 2. A pure record question: no service, no diagnosis or status cue.
    if not services and not roles and (key := fact_key(task)):
        return Disposition("answered_directly",
                           f"{key.replace('_', ' ')}: {INCIDENT_RECORD[key]} "
                           f"(host-verified incident record {INCIDENT_RECORD['incident_id']})", "record")
    # 3. A service-scoped question that names no service is ambiguous, not answerable.
    if roles and not services:
        return Disposition("needs_clarification", "Which service do you mean?", "clarification")
    return None


def prefetch(host: IncidentHost) -> tuple[Receipt, ...]:
    """Read the evidence roles the host's own contract requires for this question, through ``host.execute``."""
    roles = required_evidence_roles(host.user_request)
    return tuple(host.execute(spec.id, {"service": svc}, proposed_by=PROPOSER)
                 for svc in host.services_named_by_user() for role in roles for spec in TOOLS if spec.role == role)


def first_message(host: IncidentHost, receipts: tuple[Receipt, ...]) -> str:
    """What the agent receives: the task, then one host receipt per line (the format ``HANDOFF_AGENT`` uses)."""
    return "\n".join([host.user_request] + [r.for_model() for r in receipts])


def exit_check(host: IncidentHost, answer: str, cited: tuple[str, ...] | None = None) -> ExitVerdict:
    """Provenance and side-effect screens on a finished native answer. Not a truth check.

    ``cited=None``: the agent declared no citations, so every executed receipt counts as available to it (the
    same weak provenance Turnwise records for a ``HANDOFF_AGENT`` answer). "Missing evidence" then means a
    required role was never obtained by anyone.

    ``cited`` given (a typed final answer): the agent's own declaration is checked the way ``FINISH`` checks a
    model's: at least one citation, each an executed host receipt (the host returns every result to the agent,
    so every executed receipt was shown), and the cited set must satisfy the host's evidence contract. Still
    provenance only: an answer may cite a receipt and ignore what it says.
    """
    executed = {r.id for r in host.receipts if r.executed}
    writes_done = any(r.executed and TOOLS_BY_ID[r.tool].side_effect for r in host.receipts if r.tool in TOOLS_BY_ID)
    if _ACTION_CLAIM.search(answer) and not writes_done:
        return ExitVerdict(False, "unverified_action_claim",
                           "the answer mentions a completed side effect that no host receipt shows")
    if (problem := host.approval_claim_problem(answer)) is not None:
        return ExitVerdict(False, "unverified_action_claim", problem)
    if cited is not None:
        if not cited:
            return ExitVerdict(False, "insufficient_evidence", "the answer cites no host receipt")
        if bad := [c for c in cited if c not in executed]:
            return ExitVerdict(False, "insufficient_evidence", "the answer cites ids that are not executed host receipts",
                               detail=f"not executed host receipts: {bad}")
    missing = host.missing_evidence(tuple(sorted(executed)) if cited is None else tuple(cited))
    if missing:
        return ExitVerdict(False, "insufficient_evidence", "required evidence missing: " + ", ".join(missing))
    return ExitVerdict(True, "finished", "required receipts present; no unverified action claim")


def return_message(verdict: ExitVerdict) -> str:
    """What the host tells the agent when it sends a rejected answer back. Host-authored, plus declared ids."""
    return ("The host did not accept your answer: " + verdict.why + (f" ({verdict.detail})" if verdict.detail else "")
            + ". If evidence is missing, obtain it with the available tools, then answer again and cite only "
              "receipts of tool results that were executed.")


def withheld_answer(verdict: ExitVerdict) -> str:
    """The run's answer when the last exit check failed. Never the agent's text."""
    return f"Unresolved: the host did not accept the agent's answer ({verdict.why})."


def counts(report: ShieldReport, host: IncidentHost) -> dict[str, Any]:
    return {"model_calls": report.model_calls, "host_tool_requests": len(host.receipts),
            "host_rule_reads": len(report.prefetched), "exit_gate_checks": len(report.verdicts),
            "exit_gate_returns": report.exit_returns}
