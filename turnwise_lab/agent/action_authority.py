"""Prospective (post-freeze) request-bound host authority for write proposals.

The v0.7 experiment is immutable. This module is an opt-in *new* control,
not a patch to its locked results or a general semantic-intent detector.

All write proposals, whether from a learned controller, host plan or native
agent, must match the current user's request and target exactly before they
can even produce a human-approval receipt. The ordinary Host still performs
schema, permission and execution checks. Nothing here executes a write.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from .contracts import Decision, Observation
from .host import CATALOG_BY_ID, Host, Validation
from .world import IncidentWorld
from ..v07.evidence import (
    compile_contract,
    detect_action,
    services_in,
    strip_quoted,
    type_claim,
    unknown_services,
)


@dataclass(frozen=True)
class AuthorizedWrite:
    """A single current-turn intent, or an explicit denial with a reason."""

    capability: str | None
    arguments: dict[str, str] | None
    reason: str

    def matches(self, decision: Decision) -> bool:
        return (
            self.capability is not None
            and decision.target == self.capability
            and dict(decision.arguments) == self.arguments
        )


def _last_user_referent(conversation: list[dict]) -> tuple[list[str], str]:
    """Only user-authored, non-quoted text may supply a follow-up referent."""
    for msg in reversed(conversation):
        if msg.get("role") != "user":
            continue
        entities = services_in(strip_quoted(msg.get("content", "")))
        if entities:
            return entities, "prior user utterance"
    return [], "none"


def authorize_write(message: str, conversation: list[dict] | None = None) -> AuthorizedWrite:
    """Conservatively bind *one* write request to its exact target.

    The action's own clause must identify its service; service names in
    unrelated clauses do not count. A pronoun-only clause may use an
    unambiguous earlier *user* referent, never an assistant/tool utterance.

    This deliberately favors a visible rejected proposal over a false
    approval. Lexical intent remains insufficient for a production policy.
    """
    conversation = list(conversation or [])
    requested, declined = detect_action(message)
    if not requested:
        return AuthorizedWrite(None, None, "no positive write request in this user turn"
                               + (f"; explicitly declined {declined}" if declined else ""))

    clean = strip_quoted(message)
    clauses = [p.strip() for p in re.split(r"\s*(?:[,;]|\b(?:and|then)\b)\s*", clean, flags=re.I) if p.strip()]
    active = [(clause, cap) for clause in clauses if (cap := detect_action(clause)[0])]
    if len(active) != 1 or active[0][1] != requested:
        return AuthorizedWrite(None, None, "the request contains multiple or unscoped write intents")
    clause = active[0][0]
    if unknown_services(clause):
        return AuthorizedWrite(None, None, "action clause names an unregistered service; never substitute another service")

    if requested == "post_status_update":
        claim = type_claim(message, conversation)
        if claim.type != "action" or claim.action != requested or not claim.status_text:
            return AuthorizedWrite(None, None, "status update text is missing or ambiguous")
        contract = compile_contract(claim, message)
        if contract.hold is None or contract.hold[0] != requested:
            return AuthorizedWrite(None, None, "no unambiguous status update request")
        return AuthorizedWrite(requested, dict(contract.hold[1]), "current user requested this exact status text")

    here = services_in(clause)
    if len(here) > 1:
        return AuthorizedWrite(None, None, "action clause names multiple services")
    if here:
        service, provenance = here[0], "current user action clause"
    else:
        # A named service somewhere else *in this turn* cannot be stolen
        # as the target of an implicit/unknown action in another clause.
        if services_in(clean) or unknown_services(clean):
            return AuthorizedWrite(None, None, "action target is not named in its clause; other clauses are not authority")
        prior, provenance = _last_user_referent(conversation)
        if len(prior) != 1:
            return AuthorizedWrite(None, None, "no unique referent in prior user utterances")
        service = prior[0]
    return AuthorizedWrite(requested, {"service": service}, f"exact action target from {provenance}")


class RequestBoundHost(Host):
    """Opt-in host for one user turn; do not reuse this object across turns.

    Pass the same `message` and `conversation` into the turn runner. The
    write authority is resolved from that immutable input on construction.
    """

    def __init__(self, world: IncidentWorld, *, message: str,
                 conversation: list[dict] | None = None, **host_kwargs):
        super().__init__(world, **host_kwargs)
        self.request_message = message
        self.write_authority = authorize_write(message, conversation)

    def validate(self, decision: Decision, executed: list[Observation]) -> Validation:
        cap = CATALOG_BY_ID.get(decision.target or "")
        if (
            decision.operation in ("call_tool", "call_workflow")
            and cap is not None
            and cap.side_effect
            and not self.write_authority.matches(decision)
        ):
            return Validation(
                False, decision, "rejected",
                "current-user action authority mismatch: " + self.write_authority.reason,
            )
        return super().validate(decision, executed)

    def execute(self, decision: Decision, *, step_index: int, call_id: str,
                user_text: str) -> Observation:
        """Defend the execution/harness boundary even if a caller skips validate()."""
        cap = CATALOG_BY_ID.get(decision.target or "")
        if user_text != self.request_message or (
            cap is not None and cap.side_effect and not self.write_authority.matches(decision)
        ):
            reason = ("request-bound host reused for a different turn"
                      if user_text != self.request_message
                      else "current-user action authority mismatch at execution boundary")
            return Observation(step_index, call_id, decision.operation, decision.target,
                               dict(decision.arguments), "rejected", reason=reason)
        return super().execute(decision, step_index=step_index, call_id=call_id,
                               user_text=user_text)
