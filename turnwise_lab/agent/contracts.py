"""Typed contracts shared by the decision layer, the host and the trace."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

OPERATIONS = ("call_tool", "call_workflow", "call_model", "finish", "clarify", "abstain")
TIERS = ("light", "heavy")

# What a provider's number means. Never present one kind as another.
SCORE_RULE = "none: deterministic rule"
SCORE_LM = "normalised next-token score over the option letters (uncalibrated model score, not a probability of being right)"
SCORE_PROVIDER = "provider-reported probability (calibration unverified on this domain)"
SCORE_SCRIPTED = "none: scripted test decision"
SCORE_REPLAY = "replayed from a recorded trace (original score kept in 'recorded')"


@dataclass
class Question:
    """One typed question answered by a decision model (op, argument, tier, context block...)."""
    name: str
    options: list[str]
    answer: str | None
    scores: dict[str, float] | None = None
    score_kind: str = SCORE_RULE
    latency_ms: float | None = None
    input_tokens: int | None = None
    note: str = ""


@dataclass
class Decision:
    operation: str
    target: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    model_tier: str | None = None
    requires_continuation: bool = False
    provider: str = ""
    model: str = ""
    questions: list[Question] = field(default_factory=list)
    rationale: str = ""

    @property
    def latency_ms(self) -> float | None:
        vals = [q.latency_ms for q in self.questions if q.latency_ms is not None]
        return round(sum(vals), 1) if vals else None

    @property
    def input_tokens(self) -> int | None:
        vals = [q.input_tokens for q in self.questions if q.input_tokens is not None]
        return sum(vals) if vals else None

    def as_json(self) -> dict:
        d = asdict(self)
        d["latency_ms"] = self.latency_ms
        d["input_tokens"] = self.input_tokens
        return d


@dataclass
class ContextDecision:
    """Optional blocks proposed for one generation call. The host may drop any of them."""
    proposed: list[str]
    policy: str
    questions: list[Question] = field(default_factory=list)
    provider: str = ""
    model: str = ""

    def as_json(self) -> dict:
        return asdict(self)


@dataclass
class Observation:
    step_index: int
    call_id: str
    operation: str
    target: str | None
    arguments: dict[str, Any]
    status: str  # ok | error | approval_required | blocked | rejected | generated | pending
    facts: dict[str, Any] = field(default_factory=dict)
    text: str = ""
    reason: str = ""

    def summary(self, limit: int = 420) -> str:
        """Compact, bounded rendering for the decision model's state."""
        import json
        call = f"{self.target}({', '.join(f'{k}={v}' for k, v in self.arguments.items())})" if self.target else self.operation
        if self.status == "ok":
            compact = {k: ({kk: vv for kk, vv in v.items() if kk != "series"} if isinstance(v, dict) else v)
                       for k, v in self.facts.items()}
            body = json.dumps(compact, separators=(",", ":"), sort_keys=True)
        elif self.text:
            body = self.text
        else:
            body = self.reason
        body = body if len(body) <= limit else body[: limit - 3] + "..."
        return f"{call} -> {self.status}: {body}"
