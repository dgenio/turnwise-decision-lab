"""One incident snapshot, one tool catalog, one host: shared by every configuration.

Every configuration gets the same principal, tool names, descriptions, argument
schemas, temporal snapshot and evidence. The host validates every call, executes
registered reads, and never executes a write: a write proposal that reaches it
ends as an approval request. All values are invented.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import json
from typing import Any

SNAPSHOT_AS_OF = "2026-11-01T11:40:00Z"
SERVICES = ("checkout", "payments", "search", "auth")

_ERRORS = {"checkout": (0.4, 6.4, "11:05"), "payments": (0.3, 0.3, None), "search": (0.9, 1.1, None), "auth": (0.1, 0.1, None)}
_DEPLOYS = {"checkout": [{"id": "d-142", "at": "11:02", "change": "connection pool max 20 -> 5", "approved_by": "release-bot"}],
            "payments": [], "search": [{"id": "d-141", "at": "10:40", "change": "reindex product catalog", "approved_by": "search-team"}],
            "auth": []}
_CONFIG = {"checkout": {"pool_max": {"current": 5, "baseline": 20}}, "payments": {}, "search": {}, "auth": {}}
_HEALTH = {"checkout": ("degraded", 6.4, 1840), "payments": ("healthy", 0.3, 210), "search": ("degraded", 1.1, 2950),
           "auth": ("healthy", 0.1, 90)}


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    side_effect: bool = False

    @property
    def permission(self) -> str:
        return "write" if self.side_effect else "read"

    def json_schema(self) -> dict:
        """The exact argument schema every configuration exposes to the model."""
        return {"type": "object", "properties": {"service": {"type": "string", "enum": list(SERVICES)}},
                "required": ["service"], "additionalProperties": False}


CATALOG: tuple[ToolSpec, ...] = (
    ToolSpec("get_service_health", "Current status, error rate and p95 latency of one service."),
    ToolSpec("get_error_metrics", "Error-rate change for one service in the last hour, with the change point."),
    ToolSpec("get_deployment_history", "Recent deployments of one service: what changed, when, approved by whom."),
    ToolSpec("get_config_diff", "Current configuration of one service compared with its approved baseline."),
    ToolSpec("rollback_deployment", "Roll one service back to its previous build. Side effect: needs human approval.", True),
)
CATALOG_BY_NAME = {t.name: t for t in CATALOG}


def _read(name: str, service: str) -> dict:
    if name == "get_service_health":
        status, err, p95 = _HEALTH[service]
        return {f"health:{service}": {"status": status, "error_rate_pct": err, "p95_ms": p95, "as_of": SNAPSHOT_AS_OF}}
    if name == "get_error_metrics":
        before, after, change = _ERRORS[service]
        return {f"errors:{service}": {"before_pct": before, "after_pct": after, "change_point": change, "window": "10:30-11:30Z"}}
    if name == "get_deployment_history":
        return {f"deploys:{service}": {"window": "last 24h", "deploys": deepcopy(_DEPLOYS[service])}}
    if name == "get_config_diff":
        drift = deepcopy(_CONFIG[service])
        return {f"config:{service}": {"matches_baseline": not drift, "drifted": drift}}
    raise KeyError(name)


@dataclass
class Host:
    """The only component that executes anything. The same instance type serves every configuration."""
    principal: str = "demo-reader"
    permissions: frozenset = frozenset({"read"})
    receipts: list[dict] = field(default_factory=list)

    def validate(self, name: str, arguments: Any) -> dict:
        spec = CATALOG_BY_NAME.get(name)
        if spec is None:
            return {"status": "rejected", "reason": f"unregistered tool {name!r}"}
        if not isinstance(arguments, dict) or set(arguments) != {"service"} or arguments["service"] not in SERVICES:
            return {"status": "rejected", "reason": f"arguments {arguments!r} do not match the registered schema"}
        if spec.side_effect:
            return {"status": "approval_required", "reason": "side effect: never executed here; needs human approval"}
        if spec.permission not in self.permissions:
            return {"status": "rejected", "reason": f"principal lacks permission {spec.permission!r}"}
        return {"status": "accepted", "reason": "registered read, arguments valid"}

    def submit(self, name: str, arguments: Any, *, proposer: str, call_id: str) -> dict:
        """Validate, then execute a read or record an approval request. Returns the observation the caller sees."""
        verdict = self.validate(name, arguments)
        if verdict["status"] == "accepted":
            observation = {"tool": name, "status": "ok", "facts": _read(name, arguments["service"])}
        elif verdict["status"] == "approval_required":
            observation = {"tool": name, "status": "approval_required", "executed": False}
        else:
            observation = {"tool": name, "status": "rejected", "reason": verdict["reason"]}
        self.receipts.append({"call_id": call_id, "tool": name, "arguments": deepcopy(arguments), "proposer": proposer,
                              "validation": verdict["status"], "reason": verdict["reason"],
                              "observation_status": observation["status"], "fact_keys": list(observation.get("facts", {}))})
        return observation

    def observed_fact_keys(self) -> set[str]:
        """Evidence the host actually returned in this turn (used to check what an answer may cite)."""
        return {k for r in self.receipts if r["observation_status"] == "ok" for k in r["fact_keys"]}

    @property
    def writes_executed(self) -> int:
        return 0  # no code path in this host executes a write


def as_model_text(observation: dict) -> str:
    """How a tool result is shown to a model, identically in every configuration."""
    return json.dumps(observation, sort_keys=True, separators=(",", ":"))
