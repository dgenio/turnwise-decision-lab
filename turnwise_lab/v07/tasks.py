"""Task files for the v0.7 study: schema, loading, validation and hashing.

    python -m turnwise_lab.v07.tasks --validate fixtures/v07_dev.json

Gold fields (everything under ``expect``, plus ``category`` and ``claim_type``)
are read by the scorer and the report only. ``runtime_view`` is the only thing
a controller, the gate or the host ever receives.
"""
from __future__ import annotations

from pathlib import Path
import argparse
import hashlib
import json

from ..agent.host import CATALOG_BY_ID
from ..agent.world import DOCS, SERVICES
from .world import VARIANTS

ROOT = Path(__file__).resolve().parents[2]
SETS = {"dev": ROOT / "fixtures" / "v07_dev.json", "locked": ROOT / "fixtures" / "v07_locked.json"}
SCHEMA = "v07-tasks-1"
CATEGORIES = ("lookup", "investigation", "action_request", "ambiguous", "multi_turn", "adverse", "smalltalk_general")
CLAIM_TYPES = ("lookup", "causal", "verification", "action", "general", "ambiguous")
FACT_KINDS = ("health", "errors", "deploys", "config", "owner", "smoke")
WRITES = tuple(c.id for c in CATALOG_BY_ID.values() if c.side_effect)
RUNTIME_FIELDS = ("id", "world_variant", "conversation", "message")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def runtime_view(task: dict) -> dict:
    """What execution may see. No gold label is in here; a test pins this."""
    return {k: task[k] for k in RUNTIME_FIELDS}


def validate(data: dict) -> list[str]:
    errors = []
    if data.get("schema_version") != SCHEMA:
        errors.append(f"schema_version must be {SCHEMA}")
    seen = set()
    for i, s in enumerate(data.get("scenarios", [])):
        sid = s.get("id", f"#{i}")

        def bad(msg):
            errors.append(f"{sid}: {msg}")
        if sid in seen:
            bad("duplicate id")
        seen.add(sid)
        if s.get("category") not in CATEGORIES:
            bad(f"category must be one of {CATEGORIES}")
        if s.get("claim_type") not in CLAIM_TYPES:
            bad(f"claim_type must be one of {CLAIM_TYPES}")
        if s.get("world_variant") not in VARIANTS:
            bad(f"world_variant must be one of {VARIANTS}")
        if not isinstance(s.get("message"), str) or not s["message"].strip():
            bad("message must be a non-empty string")
        convo = s.get("conversation")
        if not isinstance(convo, list) or any(set(m) != {"role", "content"} or m["role"] not in ("user", "assistant") for m in convo):
            bad("conversation must be a list of {role: user|assistant, content}")
        e = s.get("expect") or {}
        if e.get("outcome") not in ("answer", "clarify", "approval"):
            bad("expect.outcome must be answer | clarify | approval")
        if e.get("min_tier") not in ("none", "light", "heavy"):
            bad("expect.min_tier must be none | light | heavy")
        for f in e.get("required_facts", []):
            kind, _, ent = f.partition(":")
            if kind == "doc":
                if ent not in {d.id for d in DOCS}:
                    bad(f"unknown document {f}")
            elif kind not in FACT_KINDS or ent not in SERVICES:
                bad(f"unknown fact {f}")
        if not isinstance(e.get("required_facts", []), list):
            bad("expect.required_facts must be a list")
        inc = e.get("answer_must_include", [])
        if not isinstance(inc, list) or any(not isinstance(g, list) or not g or any(not isinstance(t, str) or not t for t in g) for g in inc):
            bad("expect.answer_must_include must be a list of non-empty lists of strings (AND of ORs)")
        exc = e.get("answer_must_not_include", [])
        if not isinstance(exc, list) or any(not isinstance(t, str) or not t for t in exc):
            bad("expect.answer_must_not_include must be a list of strings")
        if e.get("outcome") == "approval":
            if e.get("approval_target") not in WRITES:
                bad(f"expect.approval_target must be one of {WRITES}")
            if e.get("approval_target") != "post_status_update" and e.get("approval_service") not in SERVICES:
                bad("expect.approval_service must name the service")
        elif e.get("approval_target") is not None:
            bad("approval_target is only for outcome=approval")
        for c in e.get("forbidden_calls", []):
            if c not in CATALOG_BY_ID:
                bad(f"unknown forbidden call {c}")
        if not isinstance(e.get("reference_answer"), str) or len(e["reference_answer"]) < 20:
            bad("expect.reference_answer must describe a fully correct reply (>= 20 characters)")
    return errors


def load_tasks(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    errors = validate(data)
    if errors:
        raise ValueError("invalid task file:\n" + "\n".join(errors))
    out = []
    for s in data["scenarios"]:
        e = s["expect"]
        e.setdefault("required_facts", [])
        e.setdefault("answer_must_include", [])
        e.setdefault("answer_must_not_include", [])
        e.setdefault("approval_target", None)
        e.setdefault("approval_service", None)
        e.setdefault("forbidden_calls", [])
        out.append(s)
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--validate", type=Path, required=True)
    p.add_argument("--quiet", action="store_true", help="print counts only (use for a locked file you must not read)")
    args = p.parse_args()
    data = json.loads(args.validate.read_text(encoding="utf-8"))
    errors = validate(data)
    if errors:
        if args.quiet:
            raise SystemExit(f"INVALID: {len(errors)} schema error(s)")
        raise SystemExit("INVALID\n" + "\n".join(errors))
    counts = {}
    for s in data["scenarios"]:
        counts[s["category"]] = counts.get(s["category"], 0) + 1
    print(f"valid: {len(data['scenarios'])} scenarios {dict(sorted(counts.items()))} sha256 {sha256(args.validate)[:16]}")


if __name__ == "__main__":
    main()
