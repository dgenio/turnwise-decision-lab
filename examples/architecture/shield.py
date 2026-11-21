"""Arm S, host side: the shielded native agent (issue #88). Framework-neutral, stdlib only.

**S is not Turnwise Core.** In Turnwise Core a small policy chooses every next
operation and the model is one of the operations. In S the roles are the other
way round: the capable agent keeps its own loop and chooses its own operations,
and the host acts only at the boundaries it already owns:

    1. before the agent   host rules that need no model: a held write, a verified-record answer,
                          a missing referent; then the reads the host's own evidence contract requires
    2. during the agent   every tool call goes through ``IncidentHost.execute`` (the shield)
    3. at the exit        receipts and claim screens on the finished answer; a rejected answer goes
                          back to the agent with the reason, up to a bound

Nothing here decides *authority*: argument validation, write intent (parsed from the
user's text only), budgets and receipts are the existing ``IncidentHost``. Step 1 reuses
the host's ``required_evidence_roles`` and tool-registry roles, so S adds no new
heuristic about what evidence a question needs.

What is deliberately not imported: ``TurnwiseRuntime``, ``Policy``, ``Snapshot``,
``Decision``, ``Op`` or any policy class (a test enforces this). The one symbol taken
from ``turnwise_core`` is the host-side claim-screen regex, so S and Core screen
answers identically.

Provenance: ported from ``research/sonnet55-strong-null/strong_null.py`` on the unmerged
branch ``experiment/sonnet55-strong-simple-null`` (``0a5000c``), where it was called the
strong simple null. Two things differ: the frozen checklist of that branch is replaced by
the repository's own A+P checklist (#43), and a rejected answer is returned to the agent
with the reason instead of ending the run at once (#88).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .incident_env import INCIDENT_RECORD, TOOLS, TOOLS_BY_ID, IncidentHost, required_evidence_roles
from .turnwise_core import _ACTION_CLAIM  # the shared host-side claim screen (a regex)

PROPOSER = "host_shield_rule"  # Receipt.proposed_by for operations the host chose itself

# Which host-verified record answers which pure record question. Kept equal to the Core
# demonstration policy's cues by a test, so S is not a weaker or stronger null by accident.
_FACT_CUES = tuple((re.compile(p, re.IGNORECASE), k) for p, k in (
    (r"\bstatus page\b", "status_page"), (r"\bseverity\b", "severity"), (r"\bcommander\b", "incident_commander"),
    (r"\bincident id\b", "incident_id"), (r"\b(start|started|began)\b", "incident_start")))


@dataclass(frozen=True)
class HostFirst:
    """What the host did before any model was involved."""

    path: str  # host_write_rule | host_record | host_clarification | native_agent
    status: str | None  # terminal status when the host finished the turn itself, else None
    answer: str = ""
    prefetched: tuple[str, ...] = ()  # receipt ids the host read for the agent
    message: str = ""  # what the native agent is given: the task, then one host receipt per line


def host_first(host: IncidentHost) -> HostFirst:
    """Steps that need no model. The host either ends the turn or prepares the agent's input."""
    task = host.user_request
    # A write the user plainly asked for is held by the host; it is never executed and never left to the agent.
    # ``requested_writes`` is deliberately narrow: anything else yields no hold here (see ``action_record``).
    if host.requested_writes:
        receipts = [host.execute(tool, {"service": svc}, proposed_by=PROPOSER) for tool, svc in sorted(host.requested_writes)]
        text = " ".join(f"{r.call()} awaits human approval. It has NOT been executed." if r.status == "held_for_approval"
                        else f"{r.call()} was not carried out: {r.reason}." for r in receipts)
        return HostFirst("host_write_rule", "held", text)

    roles = required_evidence_roles(task)
    services = host.services_named_by_user()
    if not services and not roles:  # a pure record question
        key = next((k for cue, k in _FACT_CUES if cue.search(task) and k in INCIDENT_RECORD), None)
        if key:
            return HostFirst("host_record", "answered_directly",
                             f"{key.replace('_', ' ')}: {INCIDENT_RECORD[key]} "
                             f"(host-verified incident record {INCIDENT_RECORD['incident_id']})")
    if roles and not services:  # a service-scoped question that names no service is asked, not guessed
        return HostFirst("host_clarification", "needs_clarification", "Which service do you mean?")

    # The reads the host's own evidence contract requires for this question. The agent may still read more.
    prefetched = tuple(host.execute(spec.id, {"service": svc}, proposed_by=PROPOSER).id
                       for svc in services for role in roles for spec in TOOLS if spec.role == role)
    message = "\n".join([task] + [host.receipt(r).for_model() for r in prefetched])
    return HostFirst("native_agent", None, prefetched=prefetched, message=message)


def exit_check(host: IncidentHost, answer: str, cited: tuple[str, ...] | None = None) -> dict[str, Any]:
    """Provenance and side-effect screens on a finished native answer. **Not a truth check.**

    ``cited=None``: the agent declares no citations, so every executed receipt counts as available to
    it; "missing evidence" then means a required role was never obtained by anyone.

    ``cited`` given (typed final answer): the agent's own declaration is checked the way Core's
    ``FINISH`` checks a model's. At least one citation, each an *executed* host receipt, and the cited
    set must cover the required evidence roles. Still provenance only: an answer may cite a receipt
    and ignore what it says (the archived v0.7 narration arm did exactly that).
    """
    executed_ids = {r.id for r in host.receipts if r.executed}
    executed_writes = [r for r in host.receipts if r.executed and r.tool in TOOLS_BY_ID and TOOLS_BY_ID[r.tool].side_effect]
    if _ACTION_CLAIM.search(answer) and not executed_writes:
        return {"accepted": False, "status": "unverified_action_claim",
                "why": "the answer mentions a completed side effect that no host receipt shows"}
    if (problem := host.approval_claim_problem(answer)) is not None:
        return {"accepted": False, "status": "unverified_action_claim", "why": problem}
    if cited is not None:
        if not cited:
            return {"accepted": False, "status": "insufficient_evidence", "why": "the answer cites no host receipt"}
        if bad := [c for c in cited if c not in executed_ids]:
            return {"accepted": False, "status": "insufficient_evidence",
                    "why": f"cited ids are not executed host receipts: {bad}"}
    missing = host.missing_evidence(tuple(sorted(executed_ids)) if cited is None else tuple(cited))
    if missing:
        return {"accepted": False, "status": "insufficient_evidence",
                "why": "required evidence missing: " + ", ".join(missing)}
    return {"accepted": True, "status": "finished", "why": "required receipts present; no unverified action claim"}


def feedback_message(check: dict[str, Any], *, typed: bool) -> str:
    """What a rejected answer is sent back with. States the reason and what would be accepted; grants nothing."""
    ask = ("Read what is missing with the tools if you can, then answer again and cite the receipt ids you rely on."
           if typed else "Read what is missing with the tools if you can, then answer again.")
    return (f"The host did not accept that answer: {check['why']}. {ask} "
            "Do not state that any action was executed or is awaiting approval unless a tool result says so. "
            "If the evidence cannot be obtained, say what is missing instead of concluding.")
