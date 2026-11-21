"""Small, deliberately non-production per-turn decision/context planning experiment."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Protocol
import re

ROUTES = frozenset({"direct", "flow", "tool", "llm"})
TIERS = frozenset({"small", "standard", "deep"})
_TOKEN = re.compile(r"[a-zA-Z0-9À-ÿ_-]+")
_OBVIOUS_PRIVATE = re.compile(r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}|(?:api[_-]?key|password|secret|bearer[_-]?token)\s*[:=]\s*\S+", re.IGNORECASE)



def terms(text: str) -> set[str]:
    return {w.casefold() for w in _TOKEN.findall(text) if len(w) > 2}


@dataclass(frozen=True)
class Source:
    id: str
    summary: str
    body: str
    sensitivity: str = "public"  # public | internal | restricted


@dataclass(frozen=True)
class Capability:
    id: str
    description: str
    side_effect: bool = False


@dataclass(frozen=True)
class Request:
    text: str
    task_summary: str = ""  # a bounded, host-supplied summary, not raw conversation
    sources: tuple[Source, ...] = ()
    tools: tuple[Capability, ...] = ()
    flows: tuple[Capability, ...] = ()
    sensitivity: str = "public"
    approved_actions: frozenset[str] = frozenset()
    context_budget_chars: int = 480
    conversation_turns: int = 1
    allow_external_decider: bool = False  # explicit caller opt-in even when labeled public
    direct_answer: str | None = None  # verified, host-owned deterministic response



@dataclass(frozen=True)
class Judgment:
    route: str
    route_probability: float
    tier: str
    tier_probability: float
    context_mode: str = "related"  # none | related | extended


class Decider(Protocol):
    external: bool
    def decide(self, state: dict) -> Judgment: ...


@dataclass
class Plan:
    path: str
    model_tier: str | None
    context_ids: list[str] = field(default_factory=list)
    context_pack: list[dict[str, str]] = field(default_factory=list)
    capability_id: str | None = None
    deterministic_answer: str | None = None
    approval_required: bool = False
    reasons: list[str] = field(default_factory=list)
    decision_probability: float | None = None
    decision_model_called: bool = False

    def as_json(self) -> dict:
        return asdict(self)


def shortlist(query: str, items: tuple, n: int = 4) -> list:
    q = terms(query)
    ranked = sorted(items, key=lambda x: (-len(q & terms(x.id + ' ' + getattr(x, 'summary', getattr(x, 'description', '')))), x.id))
    return [x for x in ranked if q & terms(x.id + ' ' + getattr(x, 'summary', getattr(x, 'description', '')))][:n]


def _visible_sources(request: Request, external: bool) -> tuple[Source, ...]:
    # The decision model only gets bounded metadata, never source bodies.
    # An external provider must not learn even source descriptions of protected data.
    if external:
        return tuple(s for s in request.sources if s.sensitivity == "public" and
                     not _OBVIOUS_PRIVATE.search(s.summary + ' ' + s.body))
    return request.sources


def state_preview(request: Request, external: bool) -> dict:
    # Task data sent to external inference is never marked confidential; external use
    # must be explicitly permitted by the caller at the request boundary.
    summary = request.task_summary[:400]
    return {
        "new_turn": request.text[:900],
        "task_summary": summary,
        "conversation_turns": min(request.conversation_turns, 999),
        "available_read_tools": [x.id for x in request.tools if not x.side_effect][:8],
        "available_flows": [x.id for x in request.flows if not x.side_effect][:8],
        "context_candidates": [s.id for s in shortlist(request.text + ' ' + summary, _visible_sources(request, external))],
        "instructions": "Choose route, tier and context mode, not execution authorization. Abstain by low confidence.",
    }


def pack_sources(request: Request, mode: str, *, external: bool) -> list[dict[str, str]]:
    if mode == "none":
        return []
    candidates = shortlist(request.text + ' ' + request.task_summary, _visible_sources(request, external), 8 if mode == "extended" else 4)
    remaining = max(0, min(request.context_budget_chars, 3000))
    packed: list[dict[str, str]] = []
    for doc in candidates:
        # No partial source fragment: truncated snippets can lose crucial qualifications.
        if len(doc.body) <= remaining:
            packed.append({"id": doc.id, "text": doc.body})
            remaining -= len(doc.body)
    return packed


class Planner:
    def __init__(self, decider: Decider, *, min_route_probability: float = 0.72, min_tier_probability: float = 0.55, verified_direct_bypass: bool = True):
        self.decider = decider
        self.min_route_probability = min_route_probability
        self.min_tier_probability = min_tier_probability
        self.verified_direct_bypass = verified_direct_bypass

    def plan(self, request: Request) -> Plan:
        if request.sensitivity not in {"public", "internal", "restricted"}:
            return Plan(path="hold", model_tier=None, reasons=["invalid_sensitivity_label"])
        if not (80 <= request.context_budget_chars <= 3000):
            return Plan(path="hold", model_tier=None, reasons=["invalid_context_budget"])
        # A verified answer is local: bypass classification, including external
        # classifier opt-ins, without revealing any request to the provider.
        if self.verified_direct_bypass and request.direct_answer is not None:
            return Plan(path="direct", model_tier=None, deterministic_answer=request.direct_answer,
                        decision_model_called=False, reasons=["verified_direct_host_bypass"])
        external = self.decider.external
        if external and request.sensitivity != "public":
            # No external decision call for protected enterprise state.
            return Plan(path="hold", model_tier=None, reasons=["external_decider_forbidden_for_nonpublic_request"])
        if external and not request.allow_external_decider:
            return Plan(path="hold", model_tier=None, reasons=["external_decider_requires_explicit_opt_in"])
        if external and _OBVIOUS_PRIVATE.search(request.text + ' ' + request.task_summary):
            return Plan(path="hold", model_tier=None, reasons=["obvious_private_data_in_external_request"])
        try:
            decision = self.decider.decide(state_preview(request, external))
            if (decision.route not in ROUTES or decision.tier not in TIERS
                or decision.context_mode not in {"none", "related", "extended"}
                or not (0 <= decision.route_probability <= 1)
                or not (0 <= decision.tier_probability <= 1)):
                raise ValueError("invalid classifier response")
        except Exception as exc:
            # Use only bounded, already-authorized context and a stronger model; never
            # hallucinate a tool or auto-execute a write when the classifier fails.
            return Plan(path="llm", model_tier="deep", context_ids=[], context_pack=[],
                        reasons=["classifier_unavailable_or_invalid", type(exc).__name__], decision_model_called=True)
        plan = Plan(path=decision.route, model_tier=decision.tier if decision.route in {"tool", "llm"} else None,
                    decision_probability=decision.route_probability, decision_model_called=True)
        if decision.route_probability < self.min_route_probability:
            plan.path, plan.model_tier = "llm", "deep"
            plan.reasons.append("low_route_probability_escalation")
        elif decision.route == "direct":
            if request.direct_answer is None:
                plan.path, plan.model_tier = "llm", "deep"
                plan.reasons.append("no_verified_deterministic_answer")
            else:
                plan.deterministic_answer = request.direct_answer
        elif decision.route == "tool":
            ranked = shortlist(request.text + ' ' + request.task_summary, request.tools, 1)
            if not ranked:
                plan.path, plan.model_tier = "llm", "deep"
                plan.reasons.append("no_grounded_tool_candidate")
            else:
                tool = ranked[0]
                plan.capability_id = tool.id
                if tool.side_effect and tool.id not in request.approved_actions:
                    plan.path, plan.model_tier, plan.approval_required = "hold", None, True
                    plan.reasons.append("side_effect_requires_explicit_approval")
        elif decision.route == "flow":
            ranked = shortlist(request.text + ' ' + request.task_summary, request.flows, 1)
            if not ranked:
                plan.path, plan.model_tier = "llm", "deep"
                plan.reasons.append("no_grounded_flow_candidate")
            else:
                flow = ranked[0]
                plan.capability_id = flow.id
                if flow.side_effect and flow.id not in request.approved_actions:
                    plan.path, plan.model_tier, plan.approval_required = "hold", None, True
                    plan.reasons.append("side_effect_requires_explicit_approval")
        if plan.model_tier is not None and decision.tier_probability < self.min_tier_probability:
            plan.model_tier = "deep"
            plan.reasons.append("low_tier_probability_escalation")
        if plan.path != "hold":
            packed = pack_sources(request, decision.context_mode, external=external)
            plan.context_pack = packed
            plan.context_ids = [s["id"] for s in packed]
        return plan
