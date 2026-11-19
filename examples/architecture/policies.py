"""Decision policies: the replaceable part of Turnwise Core.

A policy is anything with ``decide(snapshot) -> Decision``. It could be a
learned head, a decision service such as Jev/System One, a small LLM or, as
here, a few readable rules. Swapping the policy changes *which* operations
are chosen; it never changes who is allowed to execute them (the host).

``TriagePolicy`` is a small hand-written policy for incident questions. It is
state-driven: every branch reads the snapshot (the task, host-parsed referents
and permissions, receipts, the latest model outcome, remaining budget). It does
not read expected traces, evaluation labels, gold facts or fixture ids, and it
has no notion of "the" scenario: change what a tool or the model returns and
it decides differently. It is a demonstration policy, not a tuned or
evaluated one.
"""
from __future__ import annotations

import re

from .incident_env import Receipt, ToolSpec
from .turnwise_core import Decision, ModelOutcome, Op, Snapshot

_DIAGNOSTIC = re.compile(r"\b(explain|cause[ds]?|why|because|responsible|behind)\b", re.IGNORECASE)
_STATUS = re.compile(r"\b(healthy|health|status|up|down)\b", re.IGNORECASE)
# Which host-verified record answers which kind of question.
_FACT_CUES = tuple((re.compile(pattern, re.IGNORECASE), key) for pattern, key in (
    (r"\bstatus page\b", "status_page"), (r"\bseverity\b", "severity"), (r"\bcommander\b", "incident_commander"),
    (r"\bincident id\b", "incident_id"), (r"\b(start|started|began)\b", "incident_start")))


def op_for(spec: ToolSpec) -> Op:
    return Op.CALL_WORKFLOW if spec.kind == "workflow" else Op.CALL_TOOL


class TriagePolicy:
    """Cheap evidence first, the capable model for reasoning, the host for authority."""

    name = "TriagePolicy (deterministic rules)"
    architecture = "Turnwise Core"
    # Evidence roles worth reading before asking a model, per kind of question.
    PLAYBOOK = {"diagnostic": ("symptom", "change"), "status": ("current_state",)}

    def decide(self, s: Snapshot) -> Decision:
        last = s.latest

        # 1. A held write ends the run visibly. A hold is not an executed action.
        if isinstance(last, Receipt) and last.status == "held_for_approval":
            return Decision(Op.HOLD, "the host is holding the requested write for a human",
                            message=f"{last.call()} awaits human approval. It has NOT been executed.")

        # 2. Writes the *user* asked for go to the host, which alone decides what happens to them.
        for tool_id, svc in s.requested_writes:
            spec = s.tool(tool_id)
            if spec and not s.attempted(tool_id, {"service": svc}):
                return Decision(op_for(spec), "the user explicitly requested this action; only the host may authorise it",
                                target=tool_id, arguments={"service": svc})
        if s.requested_writes:
            return Decision(Op.HOLD, "the requested action was not accepted by the host",
                            message="The requested action could not be carried out; see the host receipts.")

        # 3. Some questions are answered by a host-verified record: no model, no tool.
        fact = _fact_key(s.task, s.verified_fact_keys)
        if fact:
            return Decision(Op.DIRECT, "a host-verified record answers this question", target=fact)

        # 4. React to the latest model observation. The model proposes; the policy decides.
        note = ""
        if isinstance(last, ModelOutcome):
            if last.kind == "answer_candidate":
                return Decision(Op.FINISH, f"{last.id} is an answer candidate; ask the host to accept it",
                                candidate=last.id)
            if last.kind == "tool_proposal":
                adopted, note = self._consider(s, last)
                if adopted:
                    return adopted
                if _proposed_before(s, last):
                    return Decision(Op.HOLD, note + "the model repeats a proposal the policy will not adopt",
                                    message=f"Unresolved: the model keeps asking for {last.proposal.call()}, "
                                            "which the policy will not run.")
            elif last.kind == "needs_evidence":
                return Decision(Op.HOLD, f"{last.id} reports missing evidence that no permitted tool provides",
                                message=f"Unresolved: {last.text}")
            else:
                note = f"{last.id} was {last.kind}; "
        elif isinstance(last, Receipt) and last.status == "rejected":
            note = f"the host rejected {last.id}; "

        # 5. Everything below needs to know which service the user means.
        if not s.services:
            return Decision(Op.CLARIFY, note + "the request names no service",
                            message="Which service do you mean?")
        svc, intent = s.services[0], _intent(s.task)

        # 6. Cheap evidence first: registered reads, chosen by their registry role.
        if s.budget_left["tool_calls"] > 0:
            for role in self.PLAYBOOK.get(intent, ()):
                spec = s.tool_for_role(role)
                if spec and not s.attempted(spec.id, {"service": svc}):
                    return Decision(op_for(spec), note + f"{role.replace('_', ' ')} evidence is a cheap read and still missing",
                                    target=spec.id, arguments={"service": svc})

        # 7. A model step, with the policy choosing the tier, the context and what the model may ask for.
        if s.budget_left["model_calls"] <= 0:
            return Decision(Op.HOLD, note + "model budget exhausted",
                            message="Unresolved: the model budget ran out before a host-accepted answer.")
        context = tuple(r.id for r in s.receipts if r.executed)
        if intent == "status":
            return Decision(Op.CALL_LIGHT, note + "one observation to phrase; a cheaper model suffices",
                            context=context)
        executed = {r.tool for r in s.receipts if r.executed}
        may_propose = tuple(t.id for t in s.tools if not t.side_effect and t.id not in executed)
        return Decision(Op.CALL_HEAVY, note + "the question needs reasoning over the evidence; use the capable model",
                        context=context, may_propose=may_propose)

    @staticmethod
    def _consider(s: Snapshot, outcome: ModelOutcome) -> tuple[Decision | None, str]:
        p = outcome.proposal
        spec = s.tool(p.tool)
        if spec is None:
            return None, f"declined {outcome.id}'s proposal {p.call()}: not a registered tool; "
        if spec.side_effect:
            return None, f"declined {outcome.id}'s proposal {p.call()}: a write the user did not request; "
        if s.attempted(p.tool, p.arguments):
            return None, f"declined {outcome.id}'s proposal {p.call()}: already done; "
        if s.budget_left["tool_calls"] <= 0:
            return None, f"declined {outcome.id}'s proposal {p.call()}: tool budget exhausted; "
        return Decision(op_for(spec), f"adopt {outcome.id}'s proposal: a registered read that has not been done",
                        target=p.tool, arguments=dict(p.arguments), adopted_from=outcome.id), ""


class HandoffPolicy(TriagePolicy):
    """CONTRAST ONLY (arm D): after cheap evidence, hand the rest of the task to the native agent.

    This is not Turnwise Core. While the handoff runs, the native agent decides
    every operation; the policy only regains control when the agent returns.
    """

    name = "HandoffPolicy"
    architecture = "Agent handoff (contrast; NOT Turnwise Core)"

    def decide(self, s: Snapshot) -> Decision:
        d = super().decide(s)
        if d.op is Op.CALL_HEAVY and not s.outcomes:
            return Decision(Op.HANDOFF_AGENT, "cheap evidence gathered; delegate the rest of the task to the native agent",
                            context=d.context)
        if d.op is Op.CALL_HEAVY:
            return Decision(Op.HOLD, "the handoff returned without an acceptable answer",
                            message="Unresolved after the agent handoff.")
        return d


def _intent(task: str) -> str:
    if _DIAGNOSTIC.search(task):
        return "diagnostic"
    if _STATUS.search(task):
        return "status"
    return "other"


def _fact_key(task: str, keys: tuple[str, ...]) -> str | None:
    return next((key for cue, key in _FACT_CUES if cue.search(task) and key in keys), None)


def _proposed_before(s: Snapshot, outcome: ModelOutcome) -> bool:
    return any(o.id != outcome.id and o.proposal == outcome.proposal for o in s.outcomes)
