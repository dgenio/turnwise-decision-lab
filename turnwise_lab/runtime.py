"""Local, closed-world, host-side execution contract (NOT an agent framework).

A planner can propose what to do. This harness independently verifies that a
registered capability is allowed before executing deterministic Python code.
No filesystem/network/write tools are registered; default policy denies writes.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Mapping
import hashlib
import json

from .core import Plan, Request, pack_sources


@dataclass(frozen=True)
class RegisteredAction:
    id: str
    description: str
    handler: Callable[[Mapping[str, Any]], Any]
    side_effect: bool = False
    required_permission: str = "read"


@dataclass(frozen=True)
class HostIdentity:
    principal: str
    permissions: frozenset[str] = frozenset({"read"})
    granted_write_actions: frozenset[str] = frozenset()


@dataclass
class Receipt:
    status: str
    path: str
    selected_action: str | None = None
    model_tier: str | None = None
    answer: Any = None
    context_ids: list[str] = field(default_factory=list)
    classifier_called: bool = False
    reason_codes: list[str] = field(default_factory=list)
    executed_actions: list[str] = field(default_factory=list)
    audit_digest: str = ""

    def as_json(self) -> dict[str, Any]:
        return asdict(self)


def _hash_receipt(r: Receipt, principal: str) -> str:
    # This is an integrity fingerprint for reproduction, NOT a signed audit log.
    material = json.dumps({"principal": principal, "status": r.status, "path": r.path,
                           "action": r.selected_action, "context_ids": r.context_ids,
                           "reason_codes": r.reason_codes, "executed": r.executed_actions,
                           "answer": r.answer, "model_tier": r.model_tier},
                          sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class LocalHarness:
    """Executes only independently approved registered local actions.

    A Plan is fully untrusted; its path, capability ID, approval flag and
    probability are never treated as authority. The host resolves identity
    and action grants independently. Default is read-only even with a grant.
    """
    def __init__(self, actions: Mapping[str, RegisteredAction], *, allow_writes: bool = False):
        self.actions = dict(actions)
        self.allow_writes = allow_writes

    def run(self, request: Request, plan: Plan, *, identity: HostIdentity,
            arguments: Mapping[str, Any] | None = None) -> Receipt:
        receipt = Receipt(status="blocked", path=plan.path,
                          model_tier=plan.model_tier, selected_action=plan.capability_id,
                          classifier_called=plan.decision_model_called,
                          reason_codes=list(plan.reasons))
        try:
            if plan.path == "hold" or plan.approval_required:
                receipt.status = "approval_required" if plan.approval_required else "blocked"
                receipt.reason_codes.append("host_honors_hold")
            elif plan.path == "direct":
                if request.direct_answer is None:
                    receipt.reason_codes.append("host_verified_answer_required")
                else:
                    # The answer comes ONLY from the trusted host, not the planner.
                    receipt.answer = request.direct_answer
                    receipt.status = "completed"
                    receipt.reason_codes.append("host_verified_answer_used")
            elif plan.path in {"flow", "tool"}:
                action = self.actions.get(plan.capability_id or "")
                presented = request.flows if plan.path == "flow" else request.tools
                match = next((c for c in presented if c.id == plan.capability_id), None)
                if action is None or match is None:
                    receipt.reason_codes.append("unregistered_or_unpresented_capability")
                elif match.side_effect != action.side_effect:
                    receipt.reason_codes.append("capability_side_effect_metadata_mismatch")
                elif action.required_permission not in identity.permissions:
                    receipt.reason_codes.append("principal_lacks_permission")
                elif action.side_effect and (not self.allow_writes or
                                             action.id not in identity.granted_write_actions or
                                             action.id not in request.approved_actions):
                    receipt.status = "approval_required"
                    receipt.reason_codes.append("write_requires_independent_host_approval")
                else:
                    # Only bounded and registered Python handlers. No arbitrary eval.
                    receipt.answer = action.handler(dict(arguments or {}))
                    receipt.status = "completed"
                    receipt.executed_actions.append(action.id)
                    receipt.reason_codes.append("registered_action_executed")
            elif plan.path == "llm":
                # Do not pretend a model produced an answer. Return a strict handoff.
                packed = pack_sources(request, "related", external=False)
                receipt.context_ids = [p["id"] for p in packed]
                receipt.status = "generation_required"
                receipt.reason_codes.append("no_generation_backend_configured")
            else:
                receipt.reason_codes.append("invalid_path")
        except Exception as exc:
            # Preserve fail-closed behavior and avoid outputting exception secrets.
            receipt.status = "error"
            receipt.answer = None
            receipt.reason_codes.append("handler_raised_" + type(exc).__name__)
        receipt.audit_digest = _hash_receipt(receipt, identity.principal)
        return receipt
