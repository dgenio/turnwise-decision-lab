"""Deterministic synthetic incident world for v0.6.

Reuses the v0.5 data (read-only copies; the frozen v0.5 module is never
modified) and exposes the v0.6 tool names. ``variant`` changes what the tools
return, so the same user request can legitimately need a different next step:

* ``baseline``          checkout errors rise from 0.4% to 6.4% at 11:05, three minutes after deploy d-142.
* ``errors_flat``       checkout errors do not rise; there is nothing to explain.
* ``no_recent_deploy``  errors rise, but checkout has no deployment in the window.
* ``metrics_flaky``     the first get_error_metrics call fails with a transient error.

All values are invented. Every handler returns ``{"facts": {key: value}}``.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from .. import world as v05

SERVICES = v05.SERVICES
VARIANTS = ("baseline", "errors_flat", "no_recent_deploy", "metrics_flaky")
HOST_FACTS = dict(v05.HOST_FACTS)
DOCS = v05.DOCS


class TransientToolError(RuntimeError):
    pass


def _series(before: float, after: float, change_at: str | None) -> list[dict]:
    times = ["10:30", "10:45", "11:00", "11:05", "11:15", "11:30"]
    if change_at is None:
        return [{"t": t, "error_rate_pct": before} for t in times]
    idx = times.index(change_at)
    return [{"t": t, "error_rate_pct": before if i < idx else after} for i, t in enumerate(times)]


class IncidentWorld:
    def __init__(self, variant: str = "baseline"):
        if variant not in VARIANTS:
            raise ValueError(f"unknown variant {variant!r}")
        self.variant = variant
        self.health = deepcopy(v05.HEALTH)
        self.trend = deepcopy(v05.TREND)
        self.deploys = deepcopy(v05.DEPLOYS)
        self.config = deepcopy(v05.CONFIG)
        self.owners = deepcopy(v05.OWNERS)
        self.change_at = {"checkout": "11:05", "search": "11:05", "payments": None, "auth": None}
        if variant == "errors_flat":
            self.health["checkout"] = {"status": "healthy", "error_rate_pct": 0.5, "p95_ms": 430}
            self.trend["checkout"].update(error_rate_after_pct=0.5, p95_after_ms=430)
            self.change_at["checkout"] = None
        if variant == "no_recent_deploy":
            self.deploys["checkout"] = []
            self.trend["checkout"]["deploy"] = None
            self.config["checkout"] = (dict(self.config["checkout"][1]), self.config["checkout"][1])
        self._flaky_remaining = 1 if variant == "metrics_flaky" else 0
        self.write_ledger: list[str] = []

    # ----------------------------------------------------------- read tools
    def _svc(self, args: Mapping[str, Any]) -> str:
        svc = args.get("service")
        if svc not in SERVICES:
            raise KeyError("unknown service")
        return svc

    def get_service_health(self, args):
        s = self._svc(args)
        return {"facts": {f"health:{s}": {"service": s, **self.health[s], "observed_at": "2026-11-01T11:40:00Z"}}}

    def get_error_metrics(self, args):
        s = self._svc(args)
        if s == "checkout" and self._flaky_remaining:
            self._flaky_remaining -= 1
            raise TransientToolError("metrics backend timeout")
        t = self.trend[s]
        before, after = t["error_rate_before_pct"], t["error_rate_after_pct"]
        change = self.change_at[s] if after > before + 0.2 else None
        return {"facts": {f"errors:{s}": {"service": s, "window": "10:30-11:30Z", "before_pct": before,
                                          "after_pct": after, "change_point": change,
                                          "series": _series(before, after, change)}}}

    def get_deployment_history(self, args):
        s = self._svc(args)
        return {"facts": {f"deploys:{s}": {"service": s, "window": "last 24h", "deploys": deepcopy(self.deploys[s])}}}

    def get_config_diff(self, args):
        s = self._svc(args)
        current, baseline = self.config[s]
        drift = {k: {"current": current[k], "baseline": baseline[k]} for k in sorted(baseline) if current.get(k) != baseline[k]}
        return {"facts": {f"config:{s}": {"service": s, "matches_baseline": not drift, "drifted": drift}}}

    def get_service_owner(self, args):
        s = self._svc(args)
        return {"facts": {f"owner:{s}": {"service": s, **self.owners[s]}}}

    def search_runbooks(self, args):
        query = str(args.get("query", ""))[:200]
        hits = v05.rank_docs(query, k=2)
        return {"facts": {f"doc:{d}": {"title": v05.DOCS_BY_ID[d].title, "body": v05.DOCS_BY_ID[d].body} for d in hits}}

    # -------------------------------------------------------------- workflow
    def run_smoke_checks(self, args):
        """Deterministic multi-step workflow: health, config baseline, ownership."""
        s = self._svc(args)
        health = self.get_service_health(args)["facts"][f"health:{s}"]
        config = self.get_config_diff(args)["facts"][f"config:{s}"]
        checks = {"health": health["status"] == "healthy", "config_baseline": config["matches_baseline"],
                  "owner_registered": s in self.owners}
        return {"facts": {f"smoke:{s}": {"service": s, "checks": checks,
                                         "failed": sorted(k for k, ok in checks.items() if not ok)}}}

    # ---------------------------------------------------------------- writes
    def _write(self, name):
        def handler(_args):
            self.write_ledger.append(name)
            raise RuntimeError("side effects are not implemented in this offline world")
        return handler

    def handlers(self) -> dict:
        reads = {n: getattr(self, n) for n in ("get_service_health", "get_error_metrics", "get_deployment_history",
                                              "get_config_diff", "get_service_owner", "search_runbooks", "run_smoke_checks")}
        writes = {n: self._write(n) for n in ("rollback_deployment", "page_oncall", "post_status_update")}
        return {**reads, **writes}
