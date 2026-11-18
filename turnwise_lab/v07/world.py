"""World variants for the v0.7 study (all values invented).

The four v0.6 variants are unchanged. Five more make the *same request* need a
different conclusion, so that an answer written from one-sided or misread
evidence is observably wrong:

* ``deploy_after_rise``      checkout deploy d-142 lands at 11:20, fifteen minutes AFTER errors rose at 11:05.
* ``two_deploys``            checkout has d-140 at 08:30 (unrelated) and d-142 at 11:02.
* ``search_errors_rise``     search errors rise 0.9% -> 4.8% at 10:45, five minutes after reindex d-141.
* ``config_drift_no_deploy`` checkout errors rise at 11:05 with NO deploy in 24h; the pool was changed out of band (config drift only).
* ``deploys_flaky``          the first get_deployment_history call for checkout fails with a transient error.

    python -m turnwise_lab.v07.world --dump      # every read tool's output in every variant
"""
from __future__ import annotations

from copy import deepcopy
import argparse
import json

from ..agent import world as v06
from ..agent.world import IncidentWorld, SERVICES, TransientToolError

V06_VARIANTS = v06.VARIANTS
NEW_VARIANTS = ("deploy_after_rise", "two_deploys", "search_errors_rise", "config_drift_no_deploy", "deploys_flaky")
VARIANTS = V06_VARIANTS + NEW_VARIANTS


class StudyWorld(IncidentWorld):
    def __init__(self, variant: str = "baseline"):
        if variant not in VARIANTS:
            raise ValueError(f"unknown variant {variant!r}")
        super().__init__(variant if variant in V06_VARIANTS else "baseline")
        self.variant = variant
        self._deploys_flaky_remaining = 1 if variant == "deploys_flaky" else 0
        if variant == "deploy_after_rise":
            self.deploys["checkout"][0]["at"] = "2026-11-01T11:20:00Z"
        elif variant == "two_deploys":
            self.deploys["checkout"].insert(0, {"id": "d-140", "at": "2026-11-01T08:30:00Z", "approved_by": "release-captain-3",
                                                "change": "enable gzip for static assets"})
        elif variant == "search_errors_rise":
            self.trend["search"].update(error_rate_after_pct=4.8)
            self.health["search"]["error_rate_pct"] = 4.8
            self.change_at["search"] = "10:45"
        elif variant == "config_drift_no_deploy":
            self.deploys["checkout"] = []
            self.trend["checkout"]["deploy"] = None

    def get_deployment_history(self, args):
        s = self._svc(args)
        if s == "checkout" and self._deploys_flaky_remaining:
            self._deploys_flaky_remaining -= 1
            raise TransientToolError("deploy log backend timeout")
        return super().get_deployment_history(args)


def dump() -> dict:
    """Every read tool's output in every variant (after any transient failure), for task authors."""
    from ..agent.render import render_facts
    out = {}
    for variant in VARIANTS:
        rows = {}
        for tool in ("get_service_health", "get_error_metrics", "get_deployment_history", "get_config_diff",
                     "get_service_owner", "run_smoke_checks"):
            for s in SERVICES:
                w = StudyWorld(variant)
                try:
                    facts = getattr(w, tool)({"service": s})["facts"]
                except TransientToolError:
                    facts = getattr(w, tool)({"service": s})["facts"]
                    rows[f"{tool}({s}) [first call fails with a transient error; retry returns]"] = render_facts(facts)
                    continue
                rows[f"{tool}({s})"] = render_facts(facts)
        out[variant] = rows
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--dump", action="store_true")
    args = p.parse_args()
    if args.dump:
        data = dump()
        base = data["baseline"]
        print("## baseline")
        for k, v in base.items():
            print(f"{k}: {v}")
        for variant in VARIANTS[1:]:
            print(f"\n## {variant} (only what differs from baseline)")
            for k, v in data[variant].items():
                plain = k.split(" [")[0]
                if base.get(plain) != v or k != plain:
                    print(f"{k}: {v}")
        print("\n## documents reachable through search_runbooks(query) (lexical search, top 2)")
        for d in v06.DOCS:
            print(f"doc:{d.id}: {d.title}: {d.body}")
        print("\n## host-verified incident record (no tool needed)")
        print(json.dumps(v06.HOST_FACTS, sort_keys=True))


if __name__ == "__main__":
    main()
