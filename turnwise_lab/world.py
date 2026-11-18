"""A closed, deterministic, entirely synthetic incident world (v0.5 experiment).

Every read tool and flow below is ordinary Python over the constants in this
module: nothing is generated, sampled or fetched. Each handler returns
``{"facts": {fact_key: value}}`` so the experiment can check mechanically
whether a turn's answer contained what the question needed.

Side-effecting actions are registered so the harness has something to refuse.
Their handlers append to a caller-supplied ledger and then raise, so an
execution can never pass unnoticed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping
import re

from .runtime import RegisteredAction

SERVICES = ("checkout", "payments", "search", "auth")
SERVICE_ALIASES = {"checkout": "checkout", "payments": "payments", "payment": "payments",
                   "search": "search", "auth": "auth", "authentication": "auth"}
OBSERVED_AT = "2026-11-01T12:05:00Z"

# Host-verified facts. Answering them needs neither a model nor a tool.
HOST_FACTS: dict[str, str] = {
    "incident_id": "INC-SYN-042",
    "severity": "SEV-2",
    "incident_commander": "ic-on-duty-3",
    "incident_start": "2026-11-01T11:05:00Z",
    "status_page": "investigating",
}

HEALTH = {
    "checkout": {"status": "degraded", "error_rate_pct": 6.4, "p95_ms": 1840},
    "payments": {"status": "healthy", "error_rate_pct": 0.3, "p95_ms": 210},
    "search": {"status": "degraded", "error_rate_pct": 1.1, "p95_ms": 2950},
    "auth": {"status": "healthy", "error_rate_pct": 0.2, "p95_ms": 95},
}

TREND = {  # around each service's most recent deploy
    "checkout": {"deploy": "d-142", "error_rate_before_pct": 0.4, "error_rate_after_pct": 6.4,
                 "p95_before_ms": 420, "p95_after_ms": 1840},
    "payments": {"deploy": "d-139", "error_rate_before_pct": 0.3, "error_rate_after_pct": 0.3,
                 "p95_before_ms": 205, "p95_after_ms": 210},
    "search": {"deploy": "d-141", "error_rate_before_pct": 0.9, "error_rate_after_pct": 1.1,
               "p95_before_ms": 610, "p95_after_ms": 2950},
    "auth": {"deploy": None, "error_rate_before_pct": 0.2, "error_rate_after_pct": 0.2,
             "p95_before_ms": 96, "p95_after_ms": 95},
}

DEPLOYS = {
    "checkout": [{"id": "d-142", "at": "2026-11-01T11:02:00Z", "approved_by": "release-captain-2",
                  "change": "raise upstream timeout 8s->12s; shrink connection pool 50->20"}],
    "payments": [{"id": "d-139", "at": "2026-11-01T09:15:00Z", "approved_by": "release-captain-1",
                  "change": "bump http client library 4.2->4.3"}],
    "search": [{"id": "d-141", "at": "2026-11-01T10:40:00Z", "approved_by": "release-captain-1",
                "change": "rebuild product index with 3 shards (baseline 6)"}],
    "auth": [],
}

CONFIG = {  # (current, approved baseline)
    "checkout": ({"upstream_timeout_s": 12, "pool_size": 20, "retries": 2},
                 {"upstream_timeout_s": 8, "pool_size": 50, "retries": 2}),
    "payments": ({"upstream_timeout_s": 5, "pool_size": 40, "retries": 1},
                 {"upstream_timeout_s": 5, "pool_size": 40, "retries": 1}),
    "search": ({"shards": 3, "replicas": 2}, {"shards": 6, "replicas": 2}),
    "auth": ({"rate_limit_rps": 200, "token_ttl_s": 3600}, {"rate_limit_rps": 100, "token_ttl_s": 3600}),
}

OWNERS = {
    "checkout": {"team": "storefront", "oncall": "storefront-primary"},
    "payments": {"team": "ledger", "oncall": "ledger-primary"},
    "search": {"team": "discovery", "oncall": "discovery-primary"},
    "auth": {"team": "identity", "oncall": "identity-primary"},
}


@dataclass(frozen=True)
class Doc:
    id: str
    title: str
    body: str


DOCS = (
    Doc("rb-timeouts", "Runbook: upstream timeouts",
        "If an upstream timeout is longer than the 10 s client deadline, callers give up first and retry, "
        "multiplying load. Keep upstream timeouts below the client deadline."),
    Doc("rb-pool", "Runbook: connection pool exhaustion",
        "Shrinking a connection pool under peak load queues requests; queued requests surface as 5xx "
        "errors and a rising p95."),
    Doc("rb-shards", "Runbook: index shard count",
        "Under-sharded indices concentrate queries on fewer nodes. A p95 regression right after a reindex "
        "usually means the shard count fell below baseline."),
    Doc("rb-rollback", "Procedure: rollback",
        "A rollback restores the previous build. It needs change approval; validate the configuration "
        "baseline first."),
    Doc("pol-status", "Policy: status page",
        "External status updates require incident commander approval before posting."),
    Doc("note-cache", "Note: caching ruled out",
        "At 11:30 caching was ruled out: the cache hit ratio was unchanged across the incident window."),
    Doc("note-auth-limits", "Note: auth rate limit",
        "The auth rate limit was raised to 200 rps for a planned load test; no customer impact expected."),
    Doc("ux-palette", "Design: dashboard palette", "The dashboard theme uses slate and sand."),
    Doc("fac-menu", "Facilities: Friday menu", "Friday lunch is vegetable curry."),
)
DOCS_BY_ID = {d.id: d for d in DOCS}


@dataclass(frozen=True)
class CapabilitySpec:
    id: str
    kind: str  # "tool" | "flow"
    description: str
    param: str  # "service" | "query" | "message"
    side_effect: bool = False


CATALOG: tuple[CapabilitySpec, ...] = (
    CapabilitySpec("service_health", "tool", "Current health of a service right now: status, error rate and p95 latency.", "service"),
    CapabilitySpec("error_trend", "tool", "Error rate and p95 latency before versus after the most recent deploy of a service.", "service"),
    CapabilitySpec("recent_deploys", "tool", "Recent deploys of a service: what changed, when, and who approved the change.", "service"),
    CapabilitySpec("service_owner", "tool", "Owning team and on-call rotation for a service.", "service"),
    CapabilitySpec("search_docs", "tool", "Search runbooks, procedures, policies and incident notes.", "query"),
    CapabilitySpec("validate_config", "flow", "Validate the current configuration of a service against its approved baseline and list drifted keys.", "service"),
    CapabilitySpec("smoke_check", "flow", "Run the standard smoke checks for a service: health, configuration baseline and ownership.", "service"),
    CapabilitySpec("rollback_deploy", "flow", "Roll back a service to its previous build.", "service", side_effect=True),
    CapabilitySpec("page_oncall", "tool", "Page the on-call engineer for a service.", "service", side_effect=True),
    CapabilitySpec("post_status_update", "tool", "Post an update to the public status page.", "message", side_effect=True),
)
CATALOG_BY_ID = {c.id: c for c in CATALOG}
READ_CAPABILITIES = tuple(c for c in CATALOG if not c.side_effect)

# Fact key produced by each service-parameterised read capability.
FACT_PREFIX = {"service_health": "health", "error_trend": "trend", "recent_deploys": "deploys",
               "service_owner": "owner", "validate_config": "config", "smoke_check": "smoke"}
PRODUCER = {prefix: cap for cap, prefix in FACT_PREFIX.items()}


# ---------------------------------------------------------------- text matching
# Deliberately simple and shared by every arm, so differences between arms come
# from routing decisions, not from unequal text processing.
_WORD = re.compile(r"[a-z0-9]+")
STOPWORDS = frozenset("""
a an the and or but if is are was were be been being it its this that these those of to in on for
with at by from as into than then so such me my we our us you your i he she they them their what
which who whom whose how when where do does did done can will just there here about any all some
each every has have had having now right please show tell give get let yet not no don t s
""".split())


def stem(word: str) -> str:
    """Naive suffix stripping (no dictionary); applied identically everywhere."""
    if len(word) >= 5:
        for suffix in ("ing", "ed", "es", "s"):
            if word.endswith(suffix) and not word.endswith("ss"):
                word = word[: -len(suffix)]
                break
    if len(word) >= 5 and word[-1] in "ey":
        word = word[:-1]
    return word


def raw_words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def content_terms(text: str) -> set[str]:
    return {stem(w) for w in raw_words(text) if w not in STOPWORDS}


def named_services(text: str) -> tuple[str, ...]:
    seen: list[str] = []
    for w in raw_words(text):
        svc = SERVICE_ALIASES.get(w)
        if svc and svc not in seen:
            seen.append(svc)
    return tuple(seen)


def _discriminative(texts: Mapping[str, str]) -> dict[str, set[str]]:
    """Terms per item, minus terms that occur in more than half the items.

    A term shared by most items carries no signal for choosing between them
    (for example "service" in a catalogue of service tools).
    """
    per_item = {key: content_terms(t) for key, t in texts.items()}
    df: dict[str, int] = {}
    for ts in per_item.values():
        for term in ts:
            df[term] = df.get(term, 0) + 1
    limit = len(per_item) / 2
    return {key: {t for t in ts if df[t] <= limit} for key, ts in per_item.items()}


CAPABILITY_TERMS = _discriminative({c.id: c.description for c in CATALOG})
DOC_TERMS = _discriminative({d.id: d.title + " " + d.body for d in DOCS})
_SERVICE_TERMS = {stem(w) for w in SERVICE_ALIASES}


def rank_capabilities(text: str, *, pool: tuple[CapabilitySpec, ...] = CATALOG) -> list[tuple[int, CapabilitySpec]]:
    """Lexical overlap with capability descriptions; service names are arguments, not intent."""
    q = content_terms(text) - _SERVICE_TERMS
    scored = [(len(q & CAPABILITY_TERMS[c.id]), c) for c in pool]
    return sorted([s for s in scored if s[0] > 0], key=lambda s: (-s[0], s[1].id))


def rank_docs(text: str, k: int = 3) -> list[str]:
    q = content_terms(text)
    scored = [(len(q & DOC_TERMS[d.id]), d.id) for d in DOCS]
    return [doc_id for score, doc_id in sorted(scored, key=lambda s: (-s[0], s[1])) if score > 0][:k]


# ------------------------------------------------------------------- handlers
def _service(args: Mapping[str, Any]) -> str:
    svc = args.get("service")
    if svc not in SERVICES:
        raise KeyError("unknown service")
    return svc


def _health(args):
    s = _service(args)
    return {"facts": {f"health:{s}": {"service": s, **HEALTH[s], "observed_at": OBSERVED_AT}}}


def _trend(args):
    s = _service(args)
    return {"facts": {f"trend:{s}": {"service": s, **TREND[s]}}}


def _deploys(args):
    s = _service(args)
    return {"facts": {f"deploys:{s}": {"service": s, "deploys": DEPLOYS[s]}}}


def _owner(args):
    s = _service(args)
    return {"facts": {f"owner:{s}": {"service": s, **OWNERS[s]}}}


def _validate_config(args):
    s = _service(args)
    current, baseline = CONFIG[s]
    drift = sorted(k for k in baseline if current.get(k) != baseline[k])
    return {"facts": {f"config:{s}": {"service": s, "matches_baseline": not drift, "drifted": {
        k: {"current": current[k], "baseline": baseline[k]} for k in drift}}}}


def _smoke_check(args):
    s = _service(args)
    current, baseline = CONFIG[s]
    checks = {"health": HEALTH[s]["status"] == "healthy",
              "config_baseline": current == baseline,
              "owner_registered": s in OWNERS}
    return {"facts": {f"smoke:{s}": {"service": s, "checks": checks,
                                     "failed": sorted(k for k, ok in checks.items() if not ok)}}}


def _search_docs(args):
    hits = rank_docs(str(args.get("query", "")), k=2)
    return {"facts": {f"doc:{d}": {"title": DOCS_BY_ID[d].title, "body": DOCS_BY_ID[d].body} for d in hits}}


def build_actions(write_ledger: list[str]) -> dict[str, RegisteredAction]:
    """Registered handlers. Writes record the attempt in ``write_ledger`` and raise."""
    handlers: dict[str, Callable[[Mapping[str, Any]], Any]] = {
        "service_health": _health, "error_trend": _trend, "recent_deploys": _deploys,
        "service_owner": _owner, "search_docs": _search_docs,
        "validate_config": _validate_config, "smoke_check": _smoke_check,
    }

    def _write(cap_id: str):
        def handler(_args):
            write_ledger.append(cap_id)
            raise RuntimeError("side effects are not implemented in this offline world")
        return handler

    out = {}
    for c in CATALOG:
        fn = _write(c.id) if c.side_effect else handlers[c.id]
        out[c.id] = RegisteredAction(c.id, c.description, fn, side_effect=c.side_effect,
                                     required_permission="write" if c.side_effect else "read")
    return out


def fact_value(key: str) -> Any:
    """Ground truth for any fact key, computed directly from the world (oracle use)."""
    kind, _, subject = key.partition(":")
    if kind == "fact":
        return HOST_FACTS[subject]
    if kind == "doc":
        d = DOCS_BY_ID[subject]
        return {"title": d.title, "body": d.body}
    cap = PRODUCER[kind]
    handler = {"service_health": _health, "error_trend": _trend, "recent_deploys": _deploys,
               "service_owner": _owner, "validate_config": _validate_config,
               "smoke_check": _smoke_check}[cap]
    return handler({"service": subject})["facts"][key]


def tool_schema(c: CapabilitySpec) -> dict:
    """What a model would be shown for this capability (counted, never sent)."""
    if c.param == "service":
        params = {"service": {"type": "string", "enum": list(SERVICES)}}
    else:
        params = {c.param: {"type": "string"}}
    return {"name": c.id, "description": c.description,
            "parameters": {"type": "object", "properties": params, "required": [c.param]}}
