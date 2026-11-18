"""FROZEN v0.6 replay compatibility, not a selectable production host policy.

Recorded v0.6 traces were produced before the evidence-sufficiency gate, the
user write-intent gate and the host-owned final envelope. A historical replay
must preserve that known-unsafe behaviour exactly (any FINISH after one
successful read, a hold for any write proposal including unrequested and
duplicate ones, generated prose passed through unchecked); otherwise the
published findings, including silent misses and unrequested holds, become
impossible to reproduce. Do not use this class for new evaluations or applications.
"""
from __future__ import annotations

import json

from .contracts import Decision, Observation
from .host import Capability, Host, Validation


class FrozenV06ReplayHost(Host):
    """For tests of immutable v0.6 traces ONLY; unsafe for new decisions."""

    def validate(self, d: Decision, executed: list[Observation], *,
                 user_message: str = "", conversation: tuple[dict, ...] | list[dict] = ()) -> Validation:
        if d.operation == "finish":
            if not any(o.status == "ok" for o in executed):
                return Validation(False, d, "rejected", "finish needs at least one verified observation")
            # The replay renderer ignores this marker. Its only purpose is to
            # satisfy the updated loop's typed validation interface.
            return Validation(True, d, "accepted", "finish permitted",
                              evidence={"sufficient": True, "intent": "frozen_v06_replay", "verified": []})
        return super().validate(d, executed, user_message=user_message, conversation=conversation)

    def validate_write(self, d: Decision, cap: Capability, args: dict, executed: list[Observation],
                       user_message: str, conversation) -> Validation:
        return Validation(True, d, "approval_required", "side-effecting capability: requires independent human approval")

    def action_intents(self, user_message: str, conversation=()) -> dict:
        return {"schema": "frozen_v06_replay", "intents": [], "mentions": []}

    def review_generated_answer(self, text: str) -> dict:
        return {"unsupported_action_claims": []}

    def compose_final(self, final: dict, ledger: list[dict], denied: list[dict]) -> dict:
        return dict(final)

    def render_verified(self, observations: list[Observation], *, evidence: dict) -> str:
        lines = []
        for o in observations:
            if o.status != "ok":
                continue
            for key, value in o.facts.items():
                lines.append(f"{key}: {json.dumps(value, separators=(', ', ': '), sort_keys=True)}")
        return "Verified data (no model used):\n" + "\n".join(lines)
