"""Conservative, host-owned evidence gate for deterministic FINISH.

This is a structural *minimum-evidence* check, not a causal judge or an
outcome scorer. It never reads the evaluation gold, labels, or test fixtures.
Ambiguous intents/referents deliberately cannot be finished deterministically.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import re
from typing import Sequence

from .contracts import Observation
from .world import SERVICES

# Each evidence kind has one registered, receipt-bearing producer. Document
# retrieval is not included: a search hit alone cannot prove its relevance.
_FACT_PRODUCERS = {
    "get_service_health": "health",
    "get_error_metrics": "errors",
    "get_deployment_history": "deploys",
    "get_config_diff": "config",
    "get_service_owner": "owner",
    "run_smoke_checks": "smoke",
}
_INTENT_PATTERNS = {
    "health": r"\b(?:status|health|healthy|degrad\w*|latenc\w*|sluggish|slow|p95)\b",
    "errors": r"\b(?:errors?|failures?|spik\w*|increas\w*|metrics?|error[\s-]*rates?)\b",
    "deploys": r"\b(?:deploy\w*|releas\w*|rollouts?|builds?|approv\w*)\b",
    "config": r"\b(?:config\w*|baseline|drift\w*)\b",
    "owner": r"\b(?:owners?|on[\s-]?call|responsib\w*)\b",
    "smoke": r"\b(?:smoke[\s-]*checks?|health[\s-]*checks?)\b",
}
_CAUSAL = re.compile(r"\b(?:why|caus\w*|explain\w*|trigger\w*|blame|contribut\w*)\b", re.I)
_ACTION = re.compile(r"\b(?:rollback|roll[\s-]*back|revert|page|post|publish|revoke|restart)\b", re.I)


@dataclass(frozen=True)
class Sufficiency:
    sufficient: bool
    intent: str
    referents: tuple[str, ...]
    required: tuple[str, ...]
    present: tuple[str, ...]
    missing: tuple[str, ...]
    conflicts: tuple[str, ...]
    reason: str

    def as_json(self) -> dict:
        return asdict(self)


def assess(request: str, observations: Sequence[Observation]) -> Sufficiency:
    """Check minimum directly observed facts for a bounded explicit request.

    No last-service guessing, no gold-label access, no inferred document
    authority. Matching source + referent + payload is required. A completed
    tool is never by itself evidence of a complete investigation.
    """
    if _ACTION.search(request):
        return Sufficiency(False, "action", (), (), (), ("action_intent:pending",), (),
                           "action-like request cannot be resolved by deterministic FINISH; use host approval/clarification")

    referents = tuple(s for s in SERVICES if re.search(r"(?<!\w)" + re.escape(s) + r"(?!\w)", request, re.I))
    kinds = {kind for kind, pattern in _INTENT_PATTERNS.items() if re.search(pattern, request, re.I)}
    causal = bool(_CAUSAL.search(request))
    if causal:
        # A causal incident explanation requires triangulation even if the
        # user mentioned only one signal. This is not proof of causality.
        kinds.update(("errors", "deploys", "health"))
    intent = "investigation" if causal else ("lookup" if kinds else "unclassified")

    if not referents:
        return Sufficiency(False, intent, (), (), (), ("referent:explicit_service_required",), (),
                           "no explicit, unambiguous service referent for deterministic FINISH")
    if not kinds:
        return Sufficiency(False, intent, referents, (), (), ("intent:unclassified",), (),
                           "no supported read intent; deterministic FINISH would risk a partial answer")

    required = tuple(sorted(f"{kind}:{service}" for service in referents for kind in kinds))
    observed: dict[str, str] = {}
    conflicts: set[str] = set()

    for observation in observations:
        if observation.status != "ok":
            continue
        kind = _FACT_PRODUCERS.get(observation.target or "")
        service = observation.arguments.get("service")
        if kind is None or service not in referents:
            continue
        fact_id = f"{kind}:{service}"
        payload = observation.facts.get(fact_id)
        if not isinstance(payload, dict) or payload.get("service") != service:
            continue
        fingerprint = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        if fact_id in observed and observed[fact_id] != fingerprint:
            conflicts.add(fact_id)
        observed[fact_id] = fingerprint

    present = tuple(sorted(set(required).intersection(observed)))
    missing = tuple(sorted(set(required).difference(observed)))
    contradictions = tuple(sorted(conflicts))
    sufficient = not missing and not contradictions
    if contradictions:
        reason = "conflicting observations for " + ", ".join(contradictions)
    elif missing:
        reason = "insufficient evidence for deterministic FINISH; missing " + ", ".join(missing)
    else:
        reason = "minimum source- and referent-checked evidence present; final answer still requires outcome validation"
    return Sufficiency(sufficient, intent, referents, required, present, missing, contradictions, reason)
