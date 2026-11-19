"""Prospective v0.8 action-intent boundary over the frozen v0.7 research runtime.

This is a conservative reference adapter, NOT a production security boundary.
The v0.7 source files and locked study remain immutable. This module is never
loaded by v0.7 trace replay and makes no claims about measured outcomes.

An action may become an approval only when an agent *proposes* a typed call,
the current user's request authorizes that exact action/target, and the host
has independently validated the capability. The exit gate cannot invent it.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import re

from ..agent.contracts import Observation
from ..agent.host import CATALOG_BY_ID, Host, Validation
from ..v07.evidence import (
    detect_action, services_in, strip_quoted, type_claim, unknown_services,
)
from ..v07.gate import ALLOW, CLARIFY, HOLD, ExitGate, Verdict


# A provider assertion is not the same as a host authorization. These are the
# actual typed tool-call sources of the currently supported native agents.
MODEL_TOOL_PROPOSERS = frozenset({"heavy-agent", "hosted-agent"})


def user_history(conversation: list[dict] | None) -> list[dict]:
    """Only explicit user turns may establish a referent for a new action."""
    return [{**m, "content": strip_quoted(m.get("content", ""))}
            for m in (conversation or []) if m.get("role") == "user"]


def action_clauses(message: str, action: str) -> list[str]:
    """Action-bearing clauses; a service in another clause cannot become its target."""
    parts = re.split(r"[.;!?\n,]|\b(?:and then|and|then)\b", strip_quoted(message), flags=re.I)
    return [p.strip() for p in parts if detect_action(p)[0] == action]


@dataclass(frozen=True)
class UserRequest:
    message: str
    conversation: tuple[tuple[str, str], ...]

    @classmethod
    def bind(cls, message: str, conversation: list[dict] | None = None) -> "UserRequest":
        if not isinstance(message, str) or not message.strip():
            raise ValueError("cannot bind an empty user request")
        return cls(message, tuple((m.get("role", ""), m.get("content", "")) for m in conversation or []))

    def previous_users(self) -> list[dict]:
        return [{"role": "user", "content": strip_quoted(content)}
                for role, content in self.conversation if role == "user"]


def _rejected(decision, reason: str) -> Validation:
    return Validation(False, decision, "rejected", "v0.8 intent guard: " + reason)


class IntentBoundHost(Host):
    """Host that denies all unbound/unrequested write proposals; never executes writes.

    Call bind_request() once per user turn before invoking a controller/agent.
    A write proposed by the v0.7 lexical planner or exit gate is intentionally
    rejected, even when it is a valid *suggestion* about what a user might want.
    Legitimate ambiguous requests require clarification or a model-proposed
    typed call and independent host validation.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._user_request: UserRequest | None = None
        self._native_scope = 0

    @contextmanager
    def native_proposal_scope(self):
        """Only a trusted native-agent adapter should enter this scope.

        Decision.provider is descriptive metadata, not authentication. A
        controller may forge 'hosted-agent'; without this independent adapter
        boundary the guard must still deny the request.
        """
        self._native_scope += 1
        try:
            yield self
        finally:
            self._native_scope -= 1

    def bind_request(self, message: str, conversation: list[dict] | None = None) -> None:
        if self._user_request is not None:
            raise RuntimeError("IntentBoundHost must be constructed once per user turn; no rebinding")
        self._user_request = UserRequest.bind(message, conversation)

    def validate(self, decision, executed) -> Validation:
        base = super().validate(decision, executed)
        cap = CATALOG_BY_ID.get(decision.target or "")
        req = self._user_request
        # A factual single-service lookup cannot silently switch to a
        # different service that only the assistant happened to mention.
        # Multi-entity and causal investigations remain unrestricted and
        # must be assessed on their end-to-end evidence, not this guard.
        if (req and cap and not cap.side_effect and base.ok
                and "service" in decision.arguments):
            claim = type_claim(req.message, req.previous_users())
            if (claim.type in ("lookup", "verification")
                    and len(claim.entities) == 1
                    and claim.entity_source in ("message", "conversation")
                    and decision.arguments["service"] != claim.entities[0]):
                return _rejected(decision, "read target disagrees with the user's service referent")
        if not cap or not cap.side_effect or base.status != "approval_required":
            return base
        req = self._user_request
        if req is None:
            return _rejected(decision, "no current user turn is bound")
        if not self._native_scope:
            return _rejected(decision, "no trusted native-model call scope; provider labels are not authority")
        if decision.provider not in MODEL_TOOL_PROPOSERS:
            return _rejected(decision, "the host/lexical router cannot synthesize an approval request")

        message = strip_quoted(req.message)
        # Target authority is scoped to the action clause (below), not all
        # service mentions in a compound read + write request.
        if re.search(r"^\s*(?:can|could|should|would)\s+we\b", message, re.I):
            return _rejected(decision, "question about whether to act is not action authorization")
        if re.search(r"\b(?:actually\s+no|cancel\s+(?:that|it)|never\s+mind|do\s+not|don't|abort\s+that)\b", message, re.I):
            return _rejected(decision, "explicit retraction or negation requires clarification")
        requested, declined = detect_action(req.message)
        if requested != cap.id or declined == cap.id:
            return _rejected(decision, "the current user did not positively request this action")
        # A service in a separate read clause is not the action target.
        # Type the action clause alone, so an otherwise valid compound request
        # does not become ambiguous merely by mentioning another service.
        clauses = action_clauses(req.message, cap.id) if cap.id != "post_status_update" else []
        if cap.id != "post_status_update":
            if len(clauses) != 1:
                return _rejected(decision, "action cannot be isolated to one user-owned clause")
            if unknown_services(clauses[0]):
                return _rejected(decision, "unknown service named in the action clause; ask for clarification")
            if not services_in(clauses[0]) and services_in(message):
                return _rejected(decision, "service in another clause cannot become the action target")
        claim = type_claim(clauses[0] if clauses else req.message, req.previous_users())
        if claim.type != "action" or claim.action != cap.id:
            return _rejected(decision, "action or referent is ambiguous; no inferred approval")
        if cap.id == "post_status_update":
            if not claim.status_text or decision.arguments.get("message") != claim.status_text:
                return _rejected(decision, "status message differs from the user's literal supplied text")
        else:
            # The current explicit mention wins, otherwise the latest
            # unambiguous USER mention. Assistant prose never becomes authority.
            named = services_in(message)
            clause_targets = services_in(clauses[0])
            if len(clause_targets) > 1:
                return _rejected(decision, "action clause names multiple services")
            if clause_targets and clause_targets[0] != decision.arguments.get("service"):
                return _rejected(decision, "service in the action clause differs from proposed target")
            if not clause_targets and (named or not re.search(r"\b(?:it|that|this|them|those|on[- ]?call)\b", clauses[0], re.I)):
                return _rejected(decision, "service in another clause cannot become the action target")
            if len(claim.entities) != 1 or claim.entity_source not in ("message", "conversation"):
                return _rejected(decision, "multiple or unauthenticated service referents")
            if clause_targets and claim.entities[0] != clause_targets[0]:
                return _rejected(decision, "target is inconsistent with the user's action clause")
            if decision.arguments.get("service") != claim.entities[0]:
                return _rejected(decision, "proposed target does not match the user's referent")
        return base

    def execute(self, decision, *, step_index: int, call_id: str, user_text: str) -> Observation:
        """Re-check side-effect authority at the harness boundary.

        The ordinary agent path calls validate() first. Direct callers must
        not bypass the intent/provenance guard or re-use this bound host for
        another turn. This is an in-process invariant, not authentication.
        """
        req = self._user_request
        if req is None or user_text != req.message:
            return Observation(
                step_index, call_id, decision.operation, decision.target,
                dict(decision.arguments), "rejected",
                reason="v0.8 intent guard: unbound host or cross-turn execution",
            )
        cap = CATALOG_BY_ID.get(decision.target or "")
        if cap is not None and cap.side_effect:
            verified = self.validate(decision, [])
            if not verified.ok or verified.status != "approval_required":
                return Observation(
                    step_index, call_id, decision.operation, decision.target,
                    dict(decision.arguments), "rejected", reason=verified.reason,
                )
        return super().execute(decision, step_index=step_index,
                               call_id=call_id, user_text=user_text)


class NoSyntheticHoldGate(ExitGate):
    """Exit-checking adapter that may acquire evidence, clarify or veto, not propose writes."""

    @staticmethod
    def _trusted(conversation: list[dict] | None) -> list[dict]:
        return user_history(conversation)

    def contract(self, message, conversation, observations):
        return super().contract(message, self._trusted(conversation), observations)

    def review(self, *, message, conversation, observations, terminal, text=None, interventions=0) -> Verdict:
        trusted = self._trusted(conversation)
        verdict = super().review(
            message=message, conversation=trusted, observations=observations,
            terminal=terminal, text=text, interventions=interventions,
        )
        # In v0.7 a lexical 'HOLD' manufactures a tool call for approval.
        # This variant NEVER does: only a typed agent proposal can cause a hold.
        if verdict.action == HOLD:
            return Verdict(CLARIFY, reason="action not yet proposed as a verified typed agent call; clarify or retry",
                           contract=verdict.contract, missing=verdict.missing,
                           unavailable=verdict.unavailable, source="none")
        # The intervention limit cannot silently erase an unfulfilled action.
        if verdict.action == ALLOW and terminal in ("answer", "finish"):
            contract = self.contract(message, trusted, observations)
            requested = contract.hold
            if requested:
                cap, args = requested
                approved = any(
                    o.status == "approval_required" and o.target == cap and
                    (cap == "post_status_update" and o.arguments.get("message") == args.get("message")
                     or cap != "post_status_update" and o.arguments.get("service") == args.get("service"))
                    for o in observations
                )
                if not approved:
                    return Verdict(CLARIFY, reason="requested action has no valid host approval receipt",
                                   contract=contract.as_json(), source="none")
        return verdict

    def ground(self, text, *, message, conversation, observations, host_facts):
        return super().ground(text, message=message, conversation=self._trusted(conversation),
                              observations=observations, host_facts=host_facts)

    def veto(self, message, conversation, target):
        return super().veto(message, self._trusted(conversation), target)
