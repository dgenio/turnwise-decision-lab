"""Conservative, host-owned evidence gate for deterministic FINISH.

This is a bounded incident-world policy, not general natural-language understanding.
It never reads benchmark gold, expected routes, labels or recorded traces. Unknown
intents and unresolved referents fail closed. Only receipt-backed facts can count.

A host may supply a synthetic/recorded reference clock for freshness checks; in
offline replay no wall clock is assumed (v0.6's incident is historical).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import re
from typing import Sequence

from .contracts import Observation
from .world import SERVICES

# A fact family must come from its registered read operation, not from a model,
# a copied prompt, or a differently named tool.
SOURCES = {
    "health": "get_service_health",
    "errors": "get_error_metrics",
    "deploys": "get_deployment_history",
    "config": "get_config_diff",
    "owner": "get_service_owner",
    "smoke": "run_smoke_checks",
}
LOOKUPS = {
    "health": r"\b(?:health|healthy|unhealthy|status|degraded|latency|p95)\b",
    "errors": r"\b(?:errors?|error.rate|failures?|spikes?|trend)\b",
    "deploys": r"\b(?:deploy\w*|releas\w*|rollout|shipped|change history)\b",
    "config": r"\b(?:config\w*|drift|settings?|baseline)\b",
    "owner": r"\b(?:owners?|ownership|on.call|responsible|who approved|who manages)\b",
    "smoke": r"\b(?:smoke.checks?|smoke.tests?|run checks)\b",
}
CAUSAL = re.compile(
    r"\b(?:why|caus\w*|explain\w*|investigat\w*|diagnos\w*|blame|"
    r"correlat\w*|contribut\w*|root.cause|due.to|led.to)\b", re.I
)
ACTION = re.compile(
    r"\b(?:rollback|roll.back|revert|page|notify|post|publish|revoke|"
    r"disable|restart|trigger)\b", re.I
)
FRESHNESS = re.compile(r"\b(?:now|current\w*|today|latest|recent\w*|right.now)\b", re.I)
# The minimum payload shape, not the gold answer. A nonempty arbitrary dict
# is never sufficient to establish a fact.
FIELDS = {
    "health": ("status",),
    "errors": ("before_pct", "after_pct", "change_point", "window"),
    "deploys": ("deploys", "window"),
    "config": ("matches_baseline",),
    "owner": (),
    "smoke": ("checks",),
}


@dataclass(frozen=True)
class EvidenceReview:
    intent: str
    subjects: tuple[str, ...]
    required: tuple[str, ...]
    verified: tuple[str, ...]
    missing: tuple[str, ...]
    problems: tuple[str, ...]
    clock_checked: bool

    @property
    def sufficient(self) -> bool:
        return bool(self.required) and not self.missing and not self.problems

    def as_json(self) -> dict:
        return {
            "intent": self.intent, "subjects": list(self.subjects),
            "required": list(self.required), "verified": list(self.verified),
            "missing": list(self.missing), "problems": list(self.problems),
            "clock_checked": self.clock_checked, "sufficient": self.sufficient,
        }


def _named_services(text: str) -> tuple[str, ...]:
    return tuple(s for s in SERVICES if re.search(r"\b" + re.escape(s) + r"\b", text, re.I))


def _subjects(message: str, conversation: Sequence[dict]) -> tuple[str, ...]:
    explicit = _named_services(message)
    if explicit:
        return explicit
    # Only earlier *user statements* can disambiguate a pronoun. Never use
    # the last tool call as referent authority or guess among several.
    for turn in reversed(conversation):
        if turn.get("role") != "user":
            continue
        found = _named_services(str(turn.get("content", "")))
        if found:
            return found
    return ()


def _intent(message: str) -> tuple[str, tuple[str, ...]]:
    if ACTION.search(message):
        return "action_or_ambiguous_action", ()
    if CAUSAL.search(message):
        # Temporal co-occurrence is not causality. To expose deterministic
        # *facts* for a causal question require four complementary sources.
        return "causal_investigation", ("health", "errors", "deploys", "config")
    families = tuple(k for k, pattern in LOOKUPS.items() if re.search(pattern, message, re.I))
    if not families:
        return "unclassified", ()
    return ("compound_lookup" if len(families) > 1 else "factual_lookup"), families


def _payload_ok(family: str, payload: object, subject: str) -> bool:
    if not isinstance(payload, dict) or not payload:
        return False
    if "service" in payload and payload["service"] != subject:
        return False
    if any(k not in payload for k in FIELDS[family]):
        return False
    if family == "errors":
        return isinstance(payload["before_pct"], (float, int)) and isinstance(payload["after_pct"], (float, int))
    if family == "deploys":
        return isinstance(payload["deploys"], list)
    if family == "config":
        return isinstance(payload["matches_baseline"], bool)
    if family == "smoke":
        return isinstance(payload["checks"], dict)
    if family == "owner":
        return bool(payload.get("team") or payload.get("oncall") or payload.get("on_call"))
    return isinstance(payload["status"], str) if family == "health" else True


def _age_problem(payload: dict, key: str, as_of: datetime, max_age_seconds: int) -> str | None:
    value = payload.get("observed_at")
    if not isinstance(value, str):
        return f"freshness_unverifiable:{key}"
    try:
        recorded = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if recorded.tzinfo is None or as_of.tzinfo is None:
            return f"freshness_unverifiable:{key}"
        delta = as_of - recorded
        if delta > timedelta(seconds=max_age_seconds):
            return f"stale:{key}"
        if delta < -timedelta(minutes=5):
            return f"future_dated:{key}"
    except (TypeError, ValueError, OverflowError):
        return f"invalid_timestamp:{key}"
    return None


def assess_evidence(message: str, observations: Sequence[Observation], *,
                    conversation: Sequence[dict] = (), as_of: datetime | None = None,
                    max_age_seconds: int = 3600) -> EvidenceReview:
    """Determine whether verified facts suffice for a data-only response.

    Does not assess the correctness of generated prose. This gate is deliberately
    stricter than a successful tool receipt and independent of any test gold.
    """
    intent, families = _intent(message)
    subjects = _subjects(message, conversation)
    required = tuple(f"{family}:{subject}" for subject in subjects for family in families)
    problems: list[str] = []
    if not families:
        problems.append(f"unsafe_or_unsupported_intent:{intent}")
    if not subjects:
        problems.append("referent_unresolved")
    # Multiple explicitly named services require independent evidence for
    # each; a single-service pronoun whose history had several names is unsafe.
    if not _named_services(message) and len(subjects) > 1:
        problems.append("referent_ambiguous")
    checked = as_of is not None and bool(FRESHNESS.search(message))
    verified: list[str] = []
    missing: list[str] = []
    for key in required:
        family, subject = key.split(":", 1)
        candidates = []
        for obs in observations:
            if obs.status != "ok" or key not in obs.facts:
                continue
            if obs.target != SOURCES[family] or obs.arguments.get("service") != subject:
                problems.append(f"provenance_mismatch:{key}")
                continue
            payload = obs.facts[key]
            if not _payload_ok(family, payload, subject):
                problems.append(f"invalid_payload:{key}")
                continue
            candidates.append(payload)
        if not candidates:
            missing.append(key)
            continue
        if len({json.dumps(p, sort_keys=True, default=str) for p in candidates}) > 1:
            problems.append(f"conflicting_observations:{key}")
            continue
        if checked:
            for p in candidates:
                trouble = _age_problem(p, key, as_of, max_age_seconds)
                if trouble:
                    problems.append(trouble)
                    break
        verified.append(key)
    return EvidenceReview(intent, subjects, required, tuple(verified),
                          tuple(missing), tuple(dict.fromkeys(problems)), checked)
