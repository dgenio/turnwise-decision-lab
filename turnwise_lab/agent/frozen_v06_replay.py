"""FROZEN v0.6 replay compatibility, not a selectable production host policy.

Recorded v0.6 traces were produced before the evidence-sufficiency gate.
A historical replay must preserve that known-unsafe FINISH behavior exactly;
otherwise the published findings, including silent misses, become impossible
to reproduce. Do not use this class for new evaluations or applications.
"""
from __future__ import annotations

import json

from .contracts import Decision, Observation
from .host import Host, Validation


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

    def render_verified(self, observations: list[Observation], *, evidence: dict) -> str:
        lines = []
        for o in observations:
            if o.status != "ok":
                continue
            for key, value in o.facts.items():
                lines.append(f"{key}: {json.dumps(value, separators=(', ', ': '), sort_keys=True)}")
        return "Verified data (no model used):\n" + "\n".join(lines)
