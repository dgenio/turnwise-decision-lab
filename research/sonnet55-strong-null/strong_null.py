"""Strong Simple Null (SSN): host rules, then the unmodified native agent, then a host exit check.

There is no per-step controller here. The whole architecture is one straight-line function::

    1. host write rule      user asked for a write  -> host.execute (held/rejected), stop. No model.
    2. host verified record pure record question    -> answer from the host's record.    No model.
    3. host clarification   service-scoped question, no service named -> ask.            No model.
    4. host evidence reads  the host's own evidence roles for this question -> prefetch via host.execute.
    5. native agent         the existing conventional agent (OpenAI Agents SDK Agent + Runner loop), with
                            ALL tools, deciding its own operations. It is never called step by step.
    6. host exit check      receipts + claims screen on the finished answer; status is derived, not asserted.

Everything that decides *authority* is the existing ``IncidentHost`` (argument validation, write intent parsed
from the user's text only, tool budget, receipts). Nothing is reimplemented. Step 4 reuses the host's own
``required_evidence_roles`` and tool registry roles, so SSN introduces no new heuristic about what evidence a
question needs. The model is simulated offline; see PROTOCOL.md.

What is deliberately NOT imported: ``TurnwiseRuntime``, ``Policy``, ``Snapshot``, ``Decision``, ``Op`` or any
policy class (a test enforces this). The only symbol taken from ``turnwise_core`` is the host-side claim screen
regex, so both architectures use the identical screen.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from examples.architecture.incident_env import (AGENT_INSTRUCTIONS, INCIDENT_RECORD, TOOLS, TOOLS_BY_ID,
                                                HostSession, IncidentHost, required_evidence_roles)
from examples.architecture.openai_agents.conventional import build_agent, run_conventional
from examples.architecture.turnwise_core import _ACTION_CLAIM  # shared host-side claim screen (a regex)

PROPOSER = "ssn_host_rule"  # Receipt.proposed_by for operations the host chose itself

# Which host-verified record answers which pure record question (same record keys the host exposes).
_FACT_CUES = tuple((re.compile(p, re.IGNORECASE), k) for p, k in (
    (r"\bstatus page\b", "status_page"), (r"\bseverity\b", "severity"), (r"\bcommander\b", "incident_commander"),
    (r"\bincident id\b", "incident_id"), (r"\b(start|started|began)\b", "incident_start")))

# Variant D only. One frozen, provider-neutral checklist, written before any scenario was run and not tuned.
# Any edit changes CHECKLIST_SHA256, which a test pins: change it only as a new, named variant.
CHECKLIST = (
    "Evidence checklist (apply before you answer):\n"
    "1. Confirm which service the user named and what they asked; if no service is named, ask which one.\n"
    "2. For a causal question, obtain both symptom evidence (error trend) and change evidence (recent "
    "deploys) for that service before concluding.\n"
    "3. For a status question, obtain current service health.\n"
    "4. Cite only what tool results returned. If evidence is missing or conflicting, say what is missing "
    "instead of concluding.\n"
    "5. Never state that an action was executed unless a tool result says it was executed. A rollback "
    "request is held for human approval."
)
CHECKLIST_SHA256 = "b8f6e394495569a5542cf0e6174778e6daab7ae2dfc6415bd8b6b6254f93e2cf"


def checklist_sha256() -> str:
    return hashlib.sha256(CHECKLIST.encode("utf-8")).hexdigest()


@dataclass
class SSNResult:
    status: str  # held | answered_directly | needs_clarification | finished | insufficient_evidence |
    #              unverified_action_claim | native_agent_failed
    answer: str  # what the host reports (never a withheld native answer)
    path: str  # host_write_rule | host_record | host_clarification | native_agent
    native_called: bool = False
    native_answer: str | None = None  # the native agent's raw final text, kept for inspection even if withheld
    native_model_calls_reported: int | None = None  # from the SDK result; scenarios count independently too
    prefetched: tuple[str, ...] = ()  # receipt ids the host read before the native agent ran
    exit_check: dict[str, Any] = field(default_factory=dict)
    failure: str | None = None


def run_ssn(task: str, model: Any, *, model_label: str = "", checklist: bool = False,
            host: IncidentHost | None = None, max_turns: int = 10) -> SSNResult:
    """Run one task. ``host`` may be supplied so the caller can read receipts even if the native agent raises."""
    host = host or IncidentHost(task)

    # 1. Host write rule. Authority is host-parsed from the user's own text; the host holds, never executes.
    if host.requested_writes:
        receipts = [host.execute(tool, {"service": svc}, proposed_by=PROPOSER)
                    for tool, svc in sorted(host.requested_writes)]
        held = all(r.status == "held_for_approval" for r in receipts)
        text = " ".join(f"{r.call()} awaits human approval. It has NOT been executed." if r.status == "held_for_approval"
                        else f"{r.call()} was not carried out: {r.reason}." for r in receipts)
        # Same terminal label Turnwise uses: the run stops visibly; the receipts say held vs rejected.
        return SSNResult("held", text, "host_write_rule",
                         exit_check={"write_receipts": [r.id for r in receipts], "all_held": held})

    roles = required_evidence_roles(task)
    services = host.services_named_by_user()

    # 2. Pure record question: no service, no diagnosis/status cue.
    if not services and not roles:
        key = next((k for cue, k in _FACT_CUES if cue.search(task) and k in INCIDENT_RECORD), None)
        if key:
            return SSNResult("answered_directly",
                             f"{key.replace('_', ' ')}: {INCIDENT_RECORD[key]} "
                             f"(host-verified incident record {INCIDENT_RECORD['incident_id']})", "host_record")

    # 3. A service-scoped question that names no service is ambiguous, not answerable.
    if roles and not services:
        return SSNResult("needs_clarification", "Which service do you mean?", "host_clarification")

    # 4. Host reads for the evidence roles the host itself requires for this question.
    prefetched = tuple(host.execute(spec.id, {"service": svc}, proposed_by=PROPOSER).id
                       for svc in services for role in roles for spec in TOOLS if spec.role == role)
    message = "\n".join([task] + [host.receipt(r).for_model() for r in prefetched])

    # 5. Native fallback: the existing agent, its own loop, all tools. Variant D only adds the frozen checklist.
    native_answer, calls, failure = None, None, None
    try:
        if checklist:
            native_answer, calls = _run_native_with_checklist(message, model, host, max_turns)
        else:
            res = run_conventional(message, model, model_label=model_label, max_turns=max_turns, host=host)
            native_answer, calls = res.answer, res.counts["model_calls"]
    except Exception as exc:  # a failed run is a named status, never a success
        failure = f"{type(exc).__name__}: {' '.join(str(exc).split())[:200]}"
    if failure is not None:
        return SSNResult("native_agent_failed", "Unresolved: the native agent did not finish; no answer is claimed.",
                         "native_agent", native_called=True, prefetched=prefetched, failure=failure,
                         exit_check={"checked": False})

    # 6. Host exit check: facts come from host receipts, never from the agent's prose.
    check = exit_check(host, native_answer)
    status = "finished" if check["accepted"] else check["status"]
    answer = native_answer if check["accepted"] else f"Unresolved: the host did not accept the agent's answer ({check['why']})."
    return SSNResult(status, answer, "native_agent", native_called=True, native_answer=native_answer,
                     native_model_calls_reported=calls, prefetched=prefetched, exit_check=check)


def exit_check(host: IncidentHost, answer: str) -> dict[str, Any]:
    """Provenance and side-effect screens on a finished native answer. Not a truth check.

    The native agent declares no citations, so every executed receipt counts as available to it (the same weak
    provenance Turnwise records for a HANDOFF_AGENT answer). Missing evidence therefore means a required role was
    never obtained by anyone, not that the agent ignored what it was given.
    """
    executed_writes = [r for r in host.receipts if r.executed and TOOLS_BY_ID[r.tool].side_effect]
    if _ACTION_CLAIM.search(answer) and not executed_writes:
        return {"accepted": False, "status": "unverified_action_claim",
                "why": "answer mentions a completed side effect that no host receipt shows"}
    if (problem := host.approval_claim_problem(answer)) is not None:
        return {"accepted": False, "status": "unverified_action_claim", "why": problem}
    missing = host.missing_evidence(tuple(r.id for r in host.receipts if r.executed))
    if missing:
        return {"accepted": False, "status": "insufficient_evidence",
                "why": "required evidence missing: " + ", ".join(missing)}
    return {"accepted": True, "status": "finished", "why": "required receipts present; no unverified action claim"}


def _run_native_with_checklist(message: str, model: Any, host: IncidentHost, max_turns: int) -> tuple[str, int]:
    """The same native agent and loop as ``run_conventional``; only its instructions gain the frozen checklist."""
    from agents import RunConfig, Runner  # same SDK entry points as the conventional arm

    agent = build_agent(model).clone(instructions=AGENT_INSTRUCTIONS + "\n\n" + CHECKLIST)
    result = Runner.run_sync(agent, message, context=HostSession(host, actor="llm"), max_turns=max_turns,
                             run_config=RunConfig(tracing_disabled=True))
    return str(result.final_output), len(result.raw_responses)
