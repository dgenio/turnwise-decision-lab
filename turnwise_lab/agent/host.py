"""The host: the only component allowed to execute anything.

A decision model *proposes*. The host checks the operation type, the target
capability, the argument schema, the caller's permissions, side-effect
metadata, repeats and budgets, and only then executes through the same
``LocalHarness`` boundary used since v0.4. Writes are never executed here:
they end in an approval request. Nothing a provider returns can change that.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import json

from ..core import Capability as HarnessCapability, Plan, Request
from ..runtime import HostIdentity, LocalHarness, RegisteredAction
from .contracts import OPERATIONS, TIERS, Decision, Observation
from .world import HOST_FACTS, SERVICES, IncidentWorld


@dataclass(frozen=True)
class Capability:
    id: str
    kind: str  # tool | workflow
    description: str
    params: tuple[str, ...]
    side_effect: bool = False
    permission: str = "read"


CATALOG: tuple[Capability, ...] = (
    Capability("get_service_health", "tool", "Current status, error rate and p95 latency of one service right now.", ("service",)),
    Capability("get_error_metrics", "tool", "Error-rate series for one service around its latest deployment; shows whether and when errors increased.", ("service",)),
    Capability("get_deployment_history", "tool", "Recent deployments of one service: what changed, when, and who approved it.", ("service",)),
    Capability("get_config_diff", "tool", "Current configuration of one service compared with its approved baseline.", ("service",)),
    Capability("get_service_owner", "tool", "Owning team and on-call rotation of one service.", ("service",)),
    Capability("search_runbooks", "tool", "Search runbooks, procedures and incident notes for a query.", ("query",)),
    Capability("run_smoke_checks", "workflow", "Existing deterministic workflow: health, configuration baseline and ownership checks for one service.", ("service",)),
    Capability("rollback_deployment", "tool", "Roll one service back to its previous build. Side effect: needs human approval.", ("service",), True, "write"),
    Capability("page_oncall", "tool", "Page the on-call engineer of one service. Side effect: needs human approval.", ("service",), True, "write"),
    Capability("post_status_update", "tool", "Post a message to the public status page. Side effect: needs human approval.", ("message",), True, "write"),
)
CATALOG_BY_ID = {c.id: c for c in CATALOG}


@dataclass
class Limits:
    max_steps: int = 8
    max_retries_per_call: int = 1
    max_rejections: int = 2
    max_generation_tokens: dict = field(default_factory=lambda: {"light": 96, "heavy": 220})


@dataclass
class Validation:
    ok: bool
    decision: Decision
    status: str  # accepted | rejected | approval_required
    reason: str
    dropped: list[str] = field(default_factory=list)


class Host:
    def __init__(self, world: IncidentWorld, *, identity: HostIdentity | None = None,
                 permitted_blocks: frozenset[str] | None = None, limits: Limits | None = None):
        self.world = world
        self.identity = identity or HostIdentity("demo-reader", frozenset({"read", "read_incident"}))
        self.limits = limits or Limits()
        handlers = world.handlers()
        self.harness = LocalHarness({c.id: RegisteredAction(c.id, c.description, handlers[c.id], side_effect=c.side_effect,
                                                            required_permission=c.permission) for c in CATALOG})
        from .context import BLOCKS
        self.permitted_blocks = permitted_blocks if permitted_blocks is not None else frozenset(
            b.id for b in BLOCKS if b.permission is None or b.permission in self.identity.permissions)

    # -------------------------------------------------------------- policy
    def allowed_capabilities(self) -> tuple[Capability, ...]:
        """What the decision model may *propose*. Writes are listed: proposing one yields an approval request."""
        return CATALOG

    def validate(self, d: Decision, executed: list[Observation]) -> Validation:
        if d.operation not in OPERATIONS:
            return Validation(False, d, "rejected", f"unknown operation {d.operation!r}")
        if d.operation in ("call_tool", "call_workflow"):
            cap = CATALOG_BY_ID.get(d.target or "")
            if cap is None:
                return Validation(False, d, "rejected", f"unknown capability {d.target!r}")
            if (cap.kind == "workflow") != (d.operation == "call_workflow"):
                return Validation(False, d, "rejected", f"{cap.id} is a {cap.kind}, not {d.operation}")
            args = dict(d.arguments)
            if set(args) != set(cap.params):
                return Validation(False, d, "rejected", f"arguments {sorted(args)} do not match schema {list(cap.params)}")
            if "service" in args and args["service"] not in SERVICES:
                return Validation(False, d, "rejected", f"service {args['service']!r} is not one of {list(SERVICES)}")
            for key in ("query", "message"):
                if key in args and not (isinstance(args[key], str) and 0 < len(args[key]) <= 300):
                    return Validation(False, d, "rejected", f"{key} must be 1-300 characters")
            if cap.permission not in self.identity.permissions and not cap.side_effect:
                return Validation(False, d, "rejected", f"principal lacks permission {cap.permission!r}")
            if cap.side_effect:
                return Validation(True, d, "approval_required", "side-effecting capability: requires independent human approval")
            prior = [o for o in executed if o.target == cap.id and o.arguments == args]
            if any(o.status == "ok" for o in prior):
                return Validation(False, d, "rejected", "repeated action: identical call already succeeded in this turn")
            if sum(o.status == "error" for o in prior) > self.limits.max_retries_per_call:
                return Validation(False, d, "rejected", "retry budget for this call exhausted")
            return Validation(True, d, "accepted", "registered read capability, arguments valid")
        if d.operation == "call_model":
            if d.model_tier not in TIERS:
                return Validation(False, d, "rejected", f"model tier {d.model_tier!r} is not one of {list(TIERS)}")
            return Validation(True, d, "accepted", f"{d.model_tier} generation permitted")
        if d.operation == "finish" and not any(o.status == "ok" for o in executed):
            return Validation(False, d, "rejected", "finish needs at least one verified observation")
        return Validation(True, d, "accepted", f"{d.operation} permitted")

    # ------------------------------------------------------------ execution
    def execute(self, d: Decision, *, step_index: int, call_id: str, user_text: str) -> Observation:
        cap = CATALOG_BY_ID[d.target]
        presented = (HarnessCapability(cap.id, cap.description, cap.side_effect),)
        req = Request(text=user_text, tools=presented if cap.kind == "tool" else (),
                      flows=presented if cap.kind == "workflow" else ())
        plan = Plan(path="tool" if cap.kind == "tool" else "flow", model_tier=None, capability_id=cap.id)
        receipt = self.harness.run(req, plan, identity=self.identity, arguments=dict(d.arguments))
        status = {"completed": "ok", "approval_required": "approval_required", "error": "error"}.get(receipt.status, "blocked")
        facts = receipt.answer.get("facts", {}) if status == "ok" and isinstance(receipt.answer, dict) else {}
        reason = receipt.reason_codes[-1] if receipt.reason_codes else ""
        return Observation(step_index, call_id, d.operation, cap.id, dict(d.arguments), status, facts=facts, reason=reason)

    # ------------------------------------------------------------- finalise
    def render_verified(self, observations: list[Observation]) -> str:
        """Deterministic answer from verified tool output only (no model)."""
        lines = []
        for o in observations:
            if o.status != "ok":
                continue
            for key, value in o.facts.items():
                lines.append(f"{key}: {json.dumps(value, separators=(', ', ': '), sort_keys=True)}")
        return "Verified data (no model used):\n" + "\n".join(lines)

    def approval_message(self, obs: Observation) -> str:
        args = ", ".join(f"{k}={v}" for k, v in obs.arguments.items())
        return (f"{obs.target}({args}) needs approval from an authorised person. Nothing was executed; "
                "the request has been recorded for approval.")

    @staticmethod
    def clarify_message() -> str:
        return "I need a bit more detail to do this safely: which service or change do you mean?"

    @staticmethod
    def abstain_message(reason: str) -> str:
        return f"I stopped without an answer to avoid guessing ({reason}). Please escalate to the incident commander."

    @staticmethod
    def host_facts() -> dict:
        return dict(HOST_FACTS)
