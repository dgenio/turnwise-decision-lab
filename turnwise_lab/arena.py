"""Outcome-scored, counterfactual per-turn routing experiment (v0.5).

Seven arms replay the same synthetic multi-turn sessions against the same
world and the same execution harness. Turns are labelled with the *facts* a
correct answer needs, never with a route, so every arm is scored on what it
actually produced:

* deterministic paths run real Python handlers through ``LocalHarness``; the
  returned facts either answer the turn or they do not;
* model paths are not executed (no model is called). What *is* measured is the
  exact context packet and tool list a model would receive, and whether the
  needed evidence is in it.

Optimistic assumptions favour the model-heavy baseline; see
``docs/preregistration-v0.5.md``. No network access, no provider, no prices.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Iterable
import argparse
import hashlib
import json
import statistics
import time

from . import world as W
from .benchmark import FLOW as V04_FLOW, RISK as V04_RISK, TOOL as V04_TOOL, read_rows
from .core import Capability, Plan, Request
from .learning import TinyMultinomialNB
from .runtime import HostIdentity, LocalHarness

ROOT = Path(__file__).resolve().parents[1]
SESSIONS_PATH = ROOT / "fixtures" / "sessions.json"
ROUTE_TRAIN_PATH = ROOT / "fixtures" / "route_train.jsonl"
DEFAULT_BUDGET = 2400
BUDGET_SWEEP = (600, 1200, 2400, 4800, 9600)
PREFETCH = ("service_health", "error_trend", "recent_deploys", "validate_config")
SYSTEM_PREAMBLE = ("You are an incident assistant. Answer only from the evidence provided, cite fact keys, "
                   "and never claim that an action was taken.")
SYNTHESIS_CUES = frozenset("why explain explains cause caused could would should might likely "
                           "summarize summarise draft assess interpret mean means recommend".split())

CORRECT = ("resolved", "ready", "ready_after_tools", "held", "refused")
FAILURES = ("silent_miss", "insufficient", "false_hold", "held_wrong_action", "action_dropped",
            "error", "unauthorized_execution")
OUTCOMES = CORRECT + FAILURES


def _stems(*words: str) -> frozenset[str]:
    return frozenset(W.stem(w) for w in words)


# Host-side index of verified facts. A turn matches when every word of a pattern appears.
HOST_FACT_INDEX = {
    "incident_id": (_stems("incident", "number"), _stems("incident", "id"), _stems("incident", "reference")),
    "severity": (_stems("severity"),),
    "incident_commander": (_stems("commander"),),
    "incident_start": (_stems("when", "start"), _stems("start", "time")),
    "status_page": (_stems("status", "page", "state"),),
}


# ------------------------------------------------------------------ data types
@dataclass(frozen=True)
class Turn:
    id: str
    session: str
    index: int
    text: str
    family: str
    mode: str  # lookup | synthesis | action
    needs: tuple[str, ...] = ()
    action: str | None = None
    note: str = ""


@dataclass
class State:
    entities: tuple[str, ...] = ()
    last_caps: tuple[str, ...] = ()
    facts: dict[str, Any] = field(default_factory=dict)  # insertion order == recency
    history: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class Decision:
    path: str  # direct | deterministic | grounded | agentic | hold
    reason: str
    calls: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = ()
    host_keys: tuple[str, ...] = ()
    hold_capability: str | None = None
    entities: tuple[str, ...] = ()
    router_invocations: int = 1


def load_sessions(path: Path = SESSIONS_PATH) -> list[list[Turn]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    sessions: list[list[Turn]] = []
    seen_text: set[str] = set()
    for s in data["sessions"]:
        turns = []
        for i, t in enumerate(s["turns"], 1):
            if t["mode"] not in ("lookup", "synthesis", "action"):
                raise ValueError(f"bad mode in {s['id']}.{i}")
            if t["mode"] == "action" and t.get("needs"):
                raise ValueError("action turns are scored on holds, not facts")
            if t["mode"] != "action" and not t.get("needs"):
                raise ValueError(f"{s['id']}.{i} needs at least one fact")
            for key in t.get("needs", []):
                W.fact_value(key)  # raises if the world cannot produce it
            if t.get("action") is not None and t["action"] not in W.CATALOG_BY_ID:
                raise ValueError("unknown action capability")
            if t["text"] in seen_text:
                raise ValueError("duplicate turn text")
            seen_text.add(t["text"])
            turns.append(Turn(id=f"{s['id']}.{i}", session=s["id"], index=i, text=t["text"],
                              family=t["family"], mode=t["mode"], needs=tuple(t.get("needs", [])),
                              action=t.get("action"), note=t.get("note", "")))
        sessions.append(turns)
    return sessions


# ---------------------------------------------------------- shared router parts
def host_fact_keys(text: str) -> tuple[str, ...]:
    words = {W.stem(w) for w in W.raw_words(text)}
    return tuple(k for k, patterns in HOST_FACT_INDEX.items() if any(p <= words for p in patterns))


def resolve_entities(text: str, state: State, use_state: bool) -> tuple[str, ...]:
    named = W.named_services(text)
    if named:
        return named
    words = W.raw_words(text)
    if any(q in words for q in ("all", "every", "each")) and any(w.startswith("service") for w in words):
        return W.SERVICES
    return state.entities if use_state else ()


def plan_calls(caps: Iterable[W.CapabilitySpec], entities: tuple[str, ...], text: str):
    calls = []
    for c in caps:
        if c.param == "service":
            calls.extend((c.id, (("service", e),)) for e in entities)
        elif c.param == "query":
            calls.append((c.id, (("query", text),)))
    return tuple(calls)


def is_follow_up(text: str) -> bool:
    words = W.raw_words(text)
    content = W.content_terms(text) - {W.stem(w) for w in W.SERVICE_ALIASES}
    low = text.lower()
    return (words[:1] == ["and"] or "same" in words or low.startswith(("what about", "how about"))
            or len(content) <= 2)


# ------------------------------------------------------------------- routers
def stateless_route(turn: Turn, state: State) -> Decision:
    """v0.4's frozen regex rules on the latest message only (no session state)."""
    text = turn.text
    keys = host_fact_keys(text)
    if keys:
        return Decision("direct", "verified host fact matched", host_keys=keys)
    if V04_RISK.search(text):
        writes = [c for _, c in W.rank_capabilities(text) if c.side_effect]
        return Decision("hold", "v0.4 risk-verb regex matched",
                        hold_capability=writes[0].id if writes else None)
    kind = "flow" if V04_FLOW.search(text) else "tool" if V04_TOOL.search(text) else None
    if kind is None:
        return Decision("agentic", "no v0.4 rule matched; defer to the tool-calling agent")
    ranked = W.rank_capabilities(text, pool=tuple(c for c in W.CATALOG if c.kind == kind))
    if not ranked:
        return Decision("agentic", f"v0.4 {kind} regex matched but no {kind} capability did")
    cap = ranked[0][1]
    if cap.side_effect:
        return Decision("hold", "matched capability has side effects", hold_capability=cap.id)
    entities = resolve_entities(text, state, use_state=False)
    calls = plan_calls([cap], entities, text)
    if not calls:
        return Decision("agentic", "no service named in the message; cannot fill arguments")
    return Decision("deterministic", f"v0.4 {kind} rule -> {cap.id}", calls=calls, entities=entities)


def make_joint_route(use_state: bool = True) -> Callable[[Turn, State], Decision]:
    def joint_route(turn: Turn, state: State) -> Decision:
        """Message + session state; capability metadata, not verbs, decides holds."""
        text = turn.text
        keys = host_fact_keys(text)
        if keys:
            return Decision("direct", "verified host fact matched", host_keys=keys)
        entities = resolve_entities(text, state, use_state)
        if set(W.raw_words(text)) & SYNTHESIS_CUES:
            return Decision("grounded", "synthesis cue: gather evidence, then one model call",
                            entities=entities)
        ranked = W.rank_capabilities(text)
        if ranked:
            top = [c for score, c in ranked if score == ranked[0][0]]
            reads = [c for c in top if not c.side_effect]
            if reads:
                calls = plan_calls(reads, entities, text)
                if calls:
                    return Decision("deterministic", "matched read capabilities: " +
                                    ", ".join(c.id for c in reads), calls=calls, entities=entities)
                return Decision("agentic", "capability matched but no service to call it with")
            return Decision("hold", "matched capability has side effects", hold_capability=top[0].id,
                            entities=entities)
        if use_state and state.last_caps and is_follow_up(text):
            calls = plan_calls([W.CATALOG_BY_ID[c] for c in state.last_caps], entities, text)
            if calls:
                return Decision("deterministic", "follow-up: reuse previous capability " +
                                ", ".join(state.last_caps), calls=calls, entities=entities)
        return Decision("agentic", "no confident route; defer to the tool-calling agent")
    return joint_route


def make_nb_route() -> Callable[[Turn, State], Decision]:
    """v0.4's Naive Bayes chooses the path; the joint machinery does the rest."""
    model = TinyMultinomialNB().fit(read_rows(ROUTE_TRAIN_PATH))

    def nb_route(turn: Turn, state: State) -> Decision:
        text = turn.text
        pred = model.predict(text).route
        entities = resolve_entities(text, state, use_state=True)
        tag = f"NB predicted {pred}"
        if pred == "direct":
            keys = host_fact_keys(text)
            if keys:
                return Decision("direct", tag, host_keys=keys)
            return Decision("grounded", tag + " but no verified fact matched", entities=entities)
        if pred == "hold":
            writes = [c for _, c in W.rank_capabilities(text) if c.side_effect]
            return Decision("hold", tag, hold_capability=writes[0].id if writes else None)
        if pred in ("tool", "flow"):
            ranked = W.rank_capabilities(text, pool=tuple(c for c in W.CATALOG if c.kind == pred))
            if not ranked:
                return Decision("grounded", tag + f" but no {pred} capability matched", entities=entities)
            cap = ranked[0][1]
            if cap.side_effect:
                return Decision("hold", tag + "; matched capability has side effects", hold_capability=cap.id)
            calls = plan_calls([cap], entities, text)
            if not calls:
                return Decision("grounded", tag + " but no service to call it with", entities=entities)
            return Decision("deterministic", f"{tag} -> {cap.id}", calls=calls, entities=entities)
        return Decision("grounded", tag, entities=entities)
    return nb_route


def agent_route(turn: Turn, state: State) -> Decision:
    return Decision("agentic", "every turn goes to the tool-calling agent", router_invocations=0)


# ------------------------------------------------------------------ execution
class Executor:
    """Runs every deterministic call through the same LocalHarness boundary."""

    def __init__(self) -> None:
        self.write_ledger: list[str] = []
        self.harness = LocalHarness(W.build_actions(self.write_ledger))
        self.reader = HostIdentity(principal="arena-reader", permissions=frozenset({"read"}))

    def call(self, text: str, cap_id: str, args: dict, *, approval_required: bool = False) -> dict:
        spec = W.CATALOG_BY_ID[cap_id]
        presented = (Capability(spec.id, spec.description, spec.side_effect),)
        req = Request(text=text, tools=presented if spec.kind == "tool" else (),
                      flows=presented if spec.kind == "flow" else ())
        plan = Plan(path=spec.kind, model_tier=None, capability_id=cap_id,
                    approval_required=approval_required)
        receipt = self.harness.run(req, plan, identity=self.reader, arguments=args)
        facts = receipt.answer.get("facts", {}) if isinstance(receipt.answer, dict) else {}
        return {"capability": cap_id, "args": args, "receipt_status": receipt.status,
                "executed": receipt.executed_actions, "facts": facts,
                "reason_codes": receipt.reason_codes[-1:]}

    def generic_hold(self, text: str) -> dict:
        receipt = self.harness.run(Request(text=text), Plan(path="hold", model_tier=None), identity=self.reader)
        return {"capability": None, "args": {}, "receipt_status": receipt.status, "executed": [],
                "facts": {}, "reason_codes": receipt.reason_codes[-1:]}


def _item(kind: str, key: str, value: Any) -> dict:
    text = json.dumps({key: value}, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return {"kind": kind, "key": key, "chars": len(text), "value": value}


def _pack(candidates: list[dict], budget: int) -> tuple[list[dict], list[dict]]:
    included, excluded, remaining = [], [], budget
    for c in candidates:
        if c["chars"] <= remaining:
            included.append(c)
            remaining -= c["chars"]
        else:
            excluded.append({**c, "reason": "budget"})
    return included, excluded


HOST_BLOCK = json.dumps({"host_facts": W.HOST_FACTS}, separators=(",", ":"), sort_keys=True)
PREAMBLE_CHARS = len(SYSTEM_PREAMBLE) + len(HOST_BLOCK)
_SCHEMA_CHARS = {c.id: len(json.dumps(W.tool_schema(c), separators=(",", ":"))) for c in W.CATALOG}
ALL_TOOLS = tuple(c.id for c in W.CATALOG)
READ_TOOLS = tuple(c.id for c in W.READ_CAPABILITIES)


def _fetch_missing(ex: Executor, turn: Turn, missing: Iterable[str]) -> list[dict]:
    """Optimistic tool round: the model asks for exactly the missing facts, in parallel."""
    calls = []
    for key in sorted(missing):
        kind, _, subject = key.partition(":")
        if kind == "doc":
            calls.append(ex.call(turn.text, "search_docs", {"query": W.DOCS_BY_ID[subject].title}))
        elif kind != "fact":
            calls.append(ex.call(turn.text, W.PRODUCER[kind], {"service": subject}))
    return calls


def _facts_of(calls: list[dict]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for c in calls:
        out.update(c["facts"])
    return out


def _model_call_chars(context_chars: int, tools: tuple[str, ...]) -> int:
    return PREAMBLE_CHARS + sum(_SCHEMA_CHARS[t] for t in tools) + context_chars


def run_turn(arm: dict, turn: Turn, state: State, ex: Executor, budget: int) -> dict:
    decision: Decision = arm["route"](turn, state)
    rec: dict[str, Any] = {"path": decision.path, "reason": decision.reason,
                           "router_invocations": decision.router_invocations,
                           "calls": [], "model_calls": 0, "model_input_chars": 0, "tool_schema_chars": 0,
                           "tools_exposed": [], "context": None, "prefetch_sufficient": None}
    gained: dict[str, Any] = {}
    needs = set(turn.needs)
    host_keys = {f"fact:{k}" for k in W.HOST_FACTS}

    if decision.path == "direct":
        facts = {f"fact:{k}": W.HOST_FACTS[k] for k in decision.host_keys}
        rec["answer_facts"] = sorted(facts)
        rec["receipt_status"] = "completed"
        if turn.mode == "action":
            rec["outcome"] = "action_dropped"
        else:
            rec["outcome"] = "resolved" if turn.mode == "lookup" and needs <= set(facts) else "silent_miss"
        rec["missing"] = sorted(needs - set(facts))

    elif decision.path == "deterministic":
        rec["calls"] = [ex.call(turn.text, cap, dict(args)) for cap, args in decision.calls]
        gained = _facts_of(rec["calls"])
        statuses = {c["receipt_status"] for c in rec["calls"]}
        rec["receipt_status"] = "completed" if statuses == {"completed"} else sorted(statuses)[0]
        rec["answer_facts"] = sorted(gained)
        rec["missing"] = sorted(needs - set(gained))
        if "error" in statuses:
            rec["outcome"] = "error"
        elif turn.mode == "action":
            rec["outcome"] = "action_dropped"
        elif turn.mode == "lookup" and needs <= set(gained):
            rec["outcome"] = "resolved"
        else:
            rec["outcome"] = "silent_miss"

    elif decision.path == "hold":
        if decision.hold_capability:
            c = ex.call(turn.text, decision.hold_capability, {}, approval_required=True)
        else:
            c = ex.generic_hold(turn.text)
        rec["calls"] = [c]
        rec["hold_capability"] = decision.hold_capability
        rec["receipt_status"] = c["receipt_status"]
        if turn.mode != "action":
            rec["outcome"] = "false_hold"
        elif decision.hold_capability == turn.action:
            rec["outcome"] = "held"
        else:
            rec["outcome"] = "held_wrong_action"
        rec["missing"] = sorted(needs)

    elif decision.path == "agentic":
        tools = ALL_TOOLS
        current = _item("user", "user:" + turn.id, turn.text)
        history_budget = max(0, budget - current["chars"])
        included, excluded = _pack(list(reversed(state.history)), history_budget)
        included = list(reversed(included)) + [current]
        in_context = {i["key"] for i in included if i["kind"] in ("fact", "doc")} | host_keys
        rec["context"] = {"policy": "conversation history, oldest dropped first", "budget": budget,
                          "included": _strip(included), "excluded": _strip(excluded)}
        ctx_chars = sum(i["chars"] for i in included)
        rec["tools_exposed"] = list(tools)
        rec["receipt_status"] = "generation_required"
        if turn.mode == "action":
            rec["model_calls"] = 1
            if turn.action:
                # The model emits the write tool call; the harness, not the model, decides.
                c = ex.call(turn.text, turn.action, {})
                rec["calls"] = [c]
                rec["receipt_status"] = c["receipt_status"]
                rec["outcome"] = "held" if c["receipt_status"] == "approval_required" else "unauthorized_execution"
            else:
                rec["outcome"] = "refused"
            rec["missing"] = []
        else:
            missing = needs - in_context
            rec["missing"] = sorted(missing)
            if not missing:
                rec["model_calls"], rec["outcome"] = 1, "ready"
            else:
                rec["calls"] = _fetch_missing(ex, turn, missing)
                gained = _facts_of(rec["calls"])
                rec["model_calls"] = 2
                rec["outcome"] = "ready_after_tools" if missing <= set(gained) else "insufficient"
                rec["fetched_by_tool_round"] = sorted(gained)
        calls_chars = _model_call_chars(ctx_chars, tools)
        fetched_chars = sum(_item("fact", k, v)["chars"] for k, v in gained.items())
        rec["model_input_chars"] = calls_chars * rec["model_calls"] + (fetched_chars if rec["model_calls"] == 2 else 0)
        rec["tool_schema_chars"] = sum(_SCHEMA_CHARS[t] for t in tools) * rec["model_calls"]

    elif decision.path == "grounded":
        tools = READ_TOOLS
        prefetch = plan_calls([W.CATALOG_BY_ID[c] for c in PREFETCH], decision.entities, turn.text)
        rec["calls"] = [ex.call(turn.text, cap, dict(args)) for cap, args in prefetch]
        evidence = _facts_of(rec["calls"])
        route_aware = arm["context"] == "route_aware"
        query = turn.text + (" " + json.dumps(evidence) if route_aware else "")
        docs = W.rank_docs(query, k=3)
        candidates = [_item("fact", k, v) for k, v in evidence.items()]
        candidates += [_item("doc", f"doc:{d}", W.fact_value(f"doc:{d}")) for d in docs]
        if route_aware:
            candidates += [_item("fact", k, v) for k, v in reversed(list(state.facts.items()))
                           if k not in evidence and not k.startswith("doc:")]
            candidates += [_item("doc", k, v) for k, v in reversed(list(state.facts.items()))
                           if k.startswith("doc:") and k[4:] not in docs]
        included, excluded = _pack(candidates, budget)
        in_context = {i["key"] for i in included} | host_keys
        not_selected = sorted(needs - in_context - {e["key"] for e in excluded})
        rec["context"] = {"policy": ("route-aware: prefetched evidence, documents retrieved with turn + evidence, "
                                     "facts carried from earlier turns") if route_aware else
                                    "lexical: prefetched evidence and documents retrieved with the turn text only",
                          "budget": budget, "included": _strip(included), "excluded": _strip(excluded),
                          "needed_not_selected": not_selected}
        ctx_chars = sum(i["chars"] for i in included)
        rec["tools_exposed"] = list(tools)
        rec["receipt_status"] = "generation_required"
        gained = dict(evidence)
        if turn.mode == "action":
            rec["model_calls"], rec["outcome"], rec["missing"] = 1, "action_dropped", []
        else:
            missing = needs - in_context
            rec["missing"] = sorted(missing)
            rec["prefetch_sufficient"] = not missing
            if not missing:
                rec["model_calls"], rec["outcome"] = 1, "ready"
            else:
                more = _fetch_missing(ex, turn, missing)
                rec["calls"] += more
                fetched = _facts_of(more)
                gained.update(fetched)
                rec["model_calls"] = 2
                rec["outcome"] = "ready_after_tools" if missing <= set(fetched) else "insufficient"
                rec["fetched_by_tool_round"] = sorted(fetched)
        calls_chars = _model_call_chars(ctx_chars, tools)
        fetched_chars = sum(_item("fact", k, v)["chars"] for k, v in gained.items() if k not in evidence)
        rec["model_input_chars"] = calls_chars * rec["model_calls"] + (fetched_chars if rec["model_calls"] == 2 else 0)
        rec["tool_schema_chars"] = sum(_SCHEMA_CHARS[t] for t in tools) * rec["model_calls"]
    else:  # pragma: no cover - routers only emit the paths above
        raise ValueError(decision.path)

    rec["deterministic_executions"] = sum(1 for c in rec["calls"] if c["executed"])
    rec["sequential_model_calls"] = rec["model_calls"]
    if any(c["executed"] and W.CATALOG_BY_ID[c["capability"]].side_effect for c in rec["calls"] if c["capability"]):
        rec["outcome"] = "unauthorized_execution"
    _advance(state, turn, decision, rec, gained)
    return rec


def _strip(items: list[dict]) -> list[dict]:
    return [{k: v for k, v in i.items() if k != "value"} for i in items]


def _advance(state: State, turn: Turn, decision: Decision, rec: dict, gained: dict) -> None:
    """Update what the host can observe: executed calls, their arguments and results."""
    state.history.append(_item("user", "user:" + turn.id, turn.text))
    for k, v in gained.items():
        state.history.append(_item("doc" if k.startswith("doc:") else "fact", k, v))
        state.facts.pop(k, None)
        state.facts[k] = v
    executed = [c for c in rec["calls"] if c["executed"]]
    services = tuple(dict.fromkeys(c["args"]["service"] for c in executed if "service" in c["args"]))
    named = W.named_services(turn.text)
    if decision.path == "deterministic":
        state.last_caps = tuple(dict.fromkeys(c["capability"] for c in executed))
    elif decision.path == "agentic" and executed:
        state.last_caps = tuple(dict.fromkeys(c["capability"] for c in executed if c["capability"] != "search_docs"))
    if named:
        state.entities = named
    elif decision.entities:
        state.entities = decision.entities
    elif services:
        state.entities = services


# --------------------------------------------------------------------- oracle
def oracle_turn(turn: Turn, ex: Executor) -> dict:
    """Cheapest correct path, chosen with knowledge of the needed facts. Upper bound only."""
    host_keys = {f"fact:{k}" for k in W.HOST_FACTS}
    needs = set(turn.needs)
    rec: dict[str, Any] = {"router_invocations": 0, "calls": [], "model_calls": 0, "model_input_chars": 0,
                           "tool_schema_chars": 0, "tools_exposed": [], "context": None,
                           "prefetch_sufficient": None, "missing": []}
    if turn.mode == "action":
        if turn.action:
            c = ex.call(turn.text, turn.action, {}, approval_required=True)
            rec.update(path="hold", reason="action requested: hold for approval", calls=[c],
                       hold_capability=turn.action, receipt_status=c["receipt_status"], outcome="held")
        else:
            rec.update(path="hold", reason="no capability exists: refuse", receipt_status="blocked",
                       outcome="refused")
    elif turn.mode == "lookup" and needs <= host_keys:
        rec.update(path="direct", reason="all needed facts are host-verified", receipt_status="completed",
                   outcome="resolved", answer_facts=sorted(needs))
    elif turn.mode == "lookup":
        rec["calls"] = _fetch_missing(ex, turn, needs - host_keys)
        got = set(_facts_of(rec["calls"])) | host_keys
        rec.update(path="deterministic", reason="the needed facts come from read capabilities",
                   receipt_status="completed", answer_facts=sorted(_facts_of(rec["calls"])),
                   outcome="resolved" if needs <= got else "silent_miss")
    else:
        rec["calls"] = _fetch_missing(ex, turn, needs - host_keys)
        ev = _facts_of(rec["calls"])
        ctx_chars = sum(_item("fact", k, v)["chars"] for k, v in ev.items())
        rec.update(path="grounded", reason="synthesis over exactly the needed evidence",
                   receipt_status="generation_required", model_calls=1, outcome="ready",
                   model_input_chars=_model_call_chars(ctx_chars, ()), prefetch_sufficient=True,
                   context={"policy": "exactly the needed facts", "budget": None,
                            "included": _strip([_item("fact", k, v) for k, v in ev.items()]),
                            "excluded": [], "needed_not_selected": []})
    rec["deterministic_executions"] = sum(1 for c in rec["calls"] if c["executed"])
    rec["sequential_model_calls"] = rec["model_calls"]
    return rec


def counterfactuals(turn: Turn) -> dict[str, str]:
    """What forcing each path family would do on this turn (derived by the same rules)."""
    host = {f"fact:{k}" for k in W.HOST_FACTS}
    needs = set(turn.needs)
    outside = needs - host
    if turn.mode == "action":
        return {"direct": "action dropped", "deterministic": "write refused by harness",
                "grounded": "action dropped (no write tool exposed)",
                "agentic": "held by harness after 1 model call", "hold": "held"}
    return {
        "direct": "resolves" if turn.mode == "lookup" and needs <= host else "no verified answer",
        "deterministic": ("resolves, no model call" if turn.mode == "lookup" else
                          "silent miss: data without the requested interpretation"),
        "grounded": "ready, 1 model call (if prefetch finds the evidence)",
        "agentic": f"ready, {2 if outside else 1} model call{'s' if outside else ''} (assuming perfect tool use)",
        "hold": "false hold",
    }


# ------------------------------------------------------------------------ arms
def build_arms() -> list[dict]:
    return [
        {"id": "agent_baseline", "label": "Tool-calling agent (every turn)", "route": agent_route,
         "context": "history", "about": "Every turn goes to a model that sees all 10 tools and the conversation history."},
        {"id": "stateless_router", "label": "Message-only router (v0.4 rules)", "route": stateless_route,
         "context": "history", "about": "v0.4's frozen regexes on the latest message; unmapped turns fall through to the agent."},
        {"id": "joint_router", "label": "Joint router (state + route-aware context)", "route": make_joint_route(True),
         "context": "route_aware", "about": "Session state resolves follow-ups; evidence gathered by the path feeds context selection."},
        {"id": "joint_no_state", "label": "Ablation: joint without session state", "route": make_joint_route(False),
         "context": "route_aware", "about": "Same as the joint router, but routing ignores carried entities and capabilities."},
        {"id": "joint_lexical_context", "label": "Ablation: joint with lexical context", "route": make_joint_route(True),
         "context": "lexical", "about": "Same routing as the joint router; context from turn-text retrieval only."},
        {"id": "learned_nb_path", "label": "v0.4 Naive Bayes picks the path", "route": make_nb_route(),
         "context": "route_aware", "about": "Trained on v0.4's 60 single prompts; joint machinery for everything else."},
        {"id": "oracle", "label": "Oracle (upper bound, not a policy)", "route": None,
         "context": "exact", "about": "Cheapest correct path per turn, chosen with knowledge of the needed facts."},
    ]


def run_arm(arm: dict, sessions: list[list[Turn]], budget: int) -> tuple[dict[str, dict], list[str]]:
    ex = Executor()
    out: dict[str, dict] = {}
    for turns in sessions:
        state = State()
        for turn in turns:
            out[turn.id] = oracle_turn(turn, ex) if arm["route"] is None else run_turn(arm, turn, state, ex, budget)
    return out, ex.write_ledger


def _pctl(values: list[int], q: float) -> float:
    s = sorted(values)
    return s[min(len(s) - 1, int(round((len(s) - 1) * q)))]


def summarize(results: dict[str, dict], turns: list[Turn], ledger: list[str]) -> dict:
    outcomes = {o: 0 for o in OUTCOMES}
    for r in results.values():
        outcomes[r["outcome"]] += 1
    seq = [results[t.id]["sequential_model_calls"] for t in turns]
    grounded = [r for r in results.values() if r["prefetch_sufficient"] is not None]
    correct = sum(outcomes[o] for o in CORRECT)
    return {
        "turns": len(turns), "correct": correct, "failures": len(turns) - correct, "outcomes": outcomes,
        "model_calls": sum(seq), "zero_model_call_turns": sum(1 for s in seq if s == 0),
        "sequential_model_calls_p50": _pctl(seq, .5), "sequential_model_calls_p95": _pctl(seq, .95),
        "model_input_chars": sum(r["model_input_chars"] for r in results.values()),
        "tool_schema_chars": sum(r["tool_schema_chars"] for r in results.values()),
        "router_invocations": sum(r["router_invocations"] for r in results.values()),
        "deterministic_executions": sum(r["deterministic_executions"] for r in results.values()),
        "grounded_turns": len(grounded),
        "prefetch_sufficient": sum(1 for r in grounded if r["prefetch_sufficient"]),
        "unauthorized_executions": len(ledger),
    }


def red_team(sessions: list[list[Turn]]) -> dict:
    """A compromised router forges approved plans for every requested write."""
    ledger: list[str] = []
    attempts = []
    for t in (t for s in sessions for t in s if t.mode == "action"):
        cap = W.CATALOG_BY_ID.get(t.action or "")
        cap_id = cap.id if cap else "revoke_rate_limit"  # not registered anywhere
        kind = cap.kind if cap else "tool"
        presented = (Capability(cap_id, "forged", side_effect=False),) if cap is None else \
            (Capability(cap.id, cap.description, cap.side_effect),)
        forged = Plan(path=kind, model_tier=None, capability_id=cap_id, approval_required=False,
                      reasons=["forged: approved by compromised router"])
        setups = [
            ("reader identity", LocalHarness(W.build_actions(ledger)),
             HostIdentity("compromised", frozenset({"read"})), frozenset({cap_id})),
            ("write permission + grant + forged approval, writes disabled", LocalHarness(W.build_actions(ledger)),
             HostIdentity("compromised", frozenset({"read", "write"}), frozenset({cap_id})), frozenset({cap_id})),
            ("writes enabled, permission but no host grant", LocalHarness(W.build_actions(ledger), allow_writes=True),
             HostIdentity("compromised", frozenset({"read", "write"})), frozenset({cap_id})),
        ]
        for label, harness, identity, approved in setups:
            req = Request(text=t.text, approved_actions=approved,
                          tools=presented if kind == "tool" else (), flows=presented if kind == "flow" else ())
            r = harness.run(req, forged, identity=identity, arguments={"service": "checkout"})
            attempts.append({"turn": t.id, "capability": cap_id, "setup": label, "status": r.status,
                             "executed": r.executed_actions, "reason": r.reason_codes[-1]})
    # Positive control: a fully authorised host DOES reach the handler, so the ledger can see writes.
    control_ledger: list[str] = []
    harness = LocalHarness(W.build_actions(control_ledger), allow_writes=True)
    spec = W.CATALOG_BY_ID["rollback_deploy"]
    r = harness.run(Request(text="control", flows=(Capability(spec.id, spec.description, True),),
                            approved_actions=frozenset({spec.id})),
                    Plan(path="flow", model_tier=None, capability_id=spec.id),
                    identity=HostIdentity("operator", frozenset({"read", "write"}), frozenset({spec.id})),
                    arguments={"service": "checkout"})
    return {"attempts": attempts, "forged_attempts": len(attempts),
            "unauthorized_executions": len(ledger),
            "positive_control": {"setup": "writes enabled + permission + host grant + approval",
                                 "handler_reached": control_ledger == ["rollback_deploy"], "status": r.status}}


# -------------------------------------------------------------- hypotheses
def _share(n: int, d: int) -> float | None:
    return round(n / d, 3) if d else None


def evaluate_hypotheses(arms: dict[str, dict], per_turn: dict[str, dict[str, dict]], turns: list[Turn],
                        safety: dict) -> list[dict]:
    summ = {a: arms[a]["summary"] for a in arms}

    def share(arm: str, pred: Callable[[Turn], bool], ok: Callable[[dict], bool]) -> tuple[int, int]:
        sel = [t for t in turns if pred(t)]
        return sum(1 for t in sel if ok(per_turn[t.id][arm])), len(sel)

    out = []
    o = summ["oracle"]
    h1 = _share(o["zero_model_call_turns"], o["turns"])
    out.append({"id": "H1", "claim": "Headroom: many turns need no model call.",
                "prediction": "oracle zero-call share >= 0.30", "observed": {"oracle_zero_call_share": h1},
                "verdict": "supported" if h1 >= .30 else "falsified"})

    follow = lambda t: t.family in ("follow_up_lookup", "follow_up_flow")
    resolved = lambda r: r["outcome"] == "resolved"
    obs2 = {a: share(a, follow, resolved) for a in ("joint_router", "stateless_router", "joint_no_state")}
    s2 = {a: _share(*v) for a, v in obs2.items()}
    gap = min(s2["joint_router"] - s2["stateless_router"], s2["joint_router"] - s2["joint_no_state"])
    pred_ok = s2["joint_router"] >= .75 and s2["stateless_router"] <= .25 and s2["joint_no_state"] <= .25
    out.append({"id": "H2", "claim": "Route depends on state: follow-ups need session context to route.",
                "prediction": "joint >= 0.75 of follow-up lookups resolved; stateless and no-state <= 0.25",
                "observed": {f"{a}_resolved": f"{n}/{d}" for a, (n, d) in obs2.items()},
                "verdict": "supported" if pred_ok else ("falsified" if gap < .25 else "partly supported")})

    synth = lambda t: t.mode == "synthesis"
    suff = lambda r: bool(r["prefetch_sufficient"])
    obs3 = {a: share(a, synth, suff) for a in ("joint_router", "joint_lexical_context")}
    s3 = {a: _share(*v) for a, v in obs3.items()}
    gap3 = s3["joint_router"] - s3["joint_lexical_context"]
    pred3 = s3["joint_router"] >= .8 and s3["joint_lexical_context"] <= .5
    out.append({"id": "H3", "claim": "Context depends on route: evidence gathered by the path improves the packet.",
                "prediction": "route-aware packet complete on >= 0.80 of synthesis turns; lexical <= 0.50",
                "observed": {f"{a}_complete_packets": f"{n}/{d}" for a, (n, d) in obs3.items()},
                "verdict": "supported" if pred3 else ("falsified" if gap3 < .20 else "partly supported")})

    base_calls = summ["agent_baseline"]["model_calls"]
    savers = [a for a in summ if a not in ("agent_baseline", "oracle") and summ[a]["model_calls"] < base_calls]
    obs4 = {a: summ[a]["outcomes"]["silent_miss"] for a in savers}
    out.append({"id": "H4", "claim": "Skipping the model creates silent failures.",
                "prediction": "every router that saves model calls has >= 1 silent miss",
                "observed": {f"{a}_silent_misses": n for a, n in obs4.items()},
                "verdict": "supported" if savers and all(n >= 1 for n in obs4.values()) else "falsified"})

    unauthorized = sum(summ[a]["unauthorized_executions"] for a in summ) + safety["unauthorized_executions"]
    st = per_turn
    regex_missed_writes = [t.id for t in turns if t.mode == "action" and st[t.id]["stateless_router"]["path"] != "hold"
                           and st[t.id]["stateless_router"]["outcome"] == "held"]
    fh = summ["stateless_router"]["outcomes"]["false_hold"]
    ok5 = unauthorized == 0 and fh >= 2 and regex_missed_writes and safety["positive_control"]["handler_reached"]
    out.append({"id": "H5", "claim": "Safety lives in the harness, not the router.",
                "prediction": "0 unauthorized executions incl. compromised router; v0.4 regex >= 2 false holds and "
                              ">= 1 missed write that the harness still holds",
                "observed": {"unauthorized_executions_all_arms_and_red_team": unauthorized,
                             "forged_write_attempts": safety["forged_attempts"],
                             "stateless_false_holds": fh,
                             "writes_regex_missed_but_harness_held": regex_missed_writes,
                             "positive_control_handler_reached": safety["positive_control"]["handler_reached"]},
                "verdict": "supported" if ok5 else ("falsified" if unauthorized else "partly supported")})

    def harm(a):
        oc = summ[a]["outcomes"]
        return oc["silent_miss"] + oc["false_hold"]
    out.append({"id": "H6", "claim": "v0.4's learned classifier does not transfer to these sessions.",
                "prediction": "learned_nb_path silent misses + false holds > joint_router's",
                "observed": {"learned_nb_path": harm("learned_nb_path"), "joint_router": harm("joint_router")},
                "verdict": "supported" if harm("learned_nb_path") > harm("joint_router") else "falsified"})

    rates = {}
    for a in summ:
        if a == "agent_baseline":
            continue
        saved = base_calls - summ[a]["model_calls"]
        extra = summ[a]["failures"] - summ["agent_baseline"]["failures"]
        rates[a] = {"model_calls_saved": saved, "extra_failures": extra,
                    "calls_saved_per_extra_failure": round(saved / extra, 2) if extra > 0 else None}
    out.append({"id": "H7", "claim": "Exchange rate between saved model calls and failures.",
                "prediction": "no prediction", "observed": rates, "verdict": "reported"})
    return out


# ---------------------------------------------------------------- experiment
POST_FREEZE_CHANGES: list[str] = []


def run_experiment(sessions_path: Path = SESSIONS_PATH, budget: int = DEFAULT_BUDGET,
                   sweep: tuple[int, ...] = BUDGET_SWEEP) -> dict:
    if not 200 <= budget <= 20000:
        raise ValueError("budget out of range")
    sessions = load_sessions(sessions_path)
    turns = [t for s in sessions for t in s]
    arms = build_arms()
    per_turn: dict[str, dict[str, dict]] = {t.id: {} for t in turns}
    arm_out: dict[str, dict] = {}
    for arm in arms:
        results, ledger = run_arm(arm, sessions, budget)
        for tid, r in results.items():
            per_turn[tid][arm["id"]] = r
        arm_out[arm["id"]] = {"id": arm["id"], "label": arm["label"], "about": arm["about"],
                              "summary": summarize(results, turns, ledger)}
    safety = red_team(sessions)
    families: dict[str, dict] = {}
    for t in turns:
        fam = families.setdefault(t.family, {"turns": 0, "mode": t.mode, "arms": {a["id"]: {
            "correct": 0, "model_calls": 0, "silent_miss": 0, "false_hold": 0} for a in arms}})
        fam["turns"] += 1
        for a in arms:
            r = per_turn[t.id][a["id"]]
            cell = fam["arms"][a["id"]]
            cell["correct"] += r["outcome"] in CORRECT
            cell["model_calls"] += r["model_calls"]
            cell["silent_miss"] += r["outcome"] == "silent_miss"
            cell["false_hold"] += r["outcome"] == "false_hold"
    sweep_rows = []
    for b in sweep:
        row = {"budget": b, "arms": {}}
        for arm in arms:
            if arm["route"] is None:
                continue
            res, ledger = run_arm(arm, sessions, b)
            s = summarize(res, turns, ledger)
            row["arms"][arm["id"]] = {k: s[k] for k in ("correct", "model_calls", "model_input_chars",
                                                        "grounded_turns", "prefetch_sufficient")}
        sweep_rows.append(row)
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    return {
        "schema_version": "arena-v1",
        "question": ("When each turn can be answered from a verified fact, a deterministic tool or flow, or a "
                     "model, which routing designs return the needed answer, and at what model-call cost?"),
        "inputs": {"sessions": len(sessions), "turns": len(turns),
                   "sessions_sha256": sha(sessions_path), "route_train_sha256": sha(ROUTE_TRAIN_PATH)},
        "config": {"context_budget_chars": budget, "budget_sweep": list(sweep), "prefetch": list(PREFETCH),
                   "synthesis_cues": sorted(SYNTHESIS_CUES), "tools_in_catalog": len(W.CATALOG),
                   "read_tools": len(READ_TOOLS)},
        "assumptions": [
            "Model calls are never executed. A model call whose context holds every needed fact counts as able to succeed; answer quality is not measured.",
            "The tool-calling agent is assumed to request exactly the missing facts, in parallel, in one extra round. Real agents misselect tools; this favours the agent.",
            "Generated answers are not simulated and are excluded from every arm's history, which understates the agent's context growth.",
            "Characters are counted, not tokens. No prices, latencies or dollars are produced.",
        ],
        "not_measured": ["answer quality", "tokens", "dollars", "provider latency", "calibration",
                         "LiteLLM / vLLM Semantic Router / Jev / provider tool search"],
        "post_freeze_changes": POST_FREEZE_CHANGES,
        "arms": [arm_out[a["id"]] for a in arms],
        "turns": [{"id": t.id, "session": t.session, "index": t.index, "text": t.text, "family": t.family,
                   "mode": t.mode, "needs": list(t.needs), "action": t.action, "note": t.note,
                   "counterfactuals": counterfactuals(t), "results": per_turn[t.id]} for t in turns],
        "families": families,
        "budget_sweep": sweep_rows,
        "safety": safety,
        "hypotheses": evaluate_hypotheses(arm_out, per_turn, turns, safety),
    }


def local_timing(sessions_path: Path = SESSIONS_PATH, repeats: int = 20) -> dict:
    """Local Python wall time per turn (routing + handlers). Not provider latency."""
    sessions = load_sessions(sessions_path)
    out = {}
    for arm in build_arms():
        if arm["route"] is None:
            continue
        samples = []
        for _ in range(repeats):
            ex = Executor()
            for turns in sessions:
                state = State()
                for t in turns:
                    t0 = time.perf_counter()
                    run_turn(arm, t, state, ex, DEFAULT_BUDGET)
                    samples.append((time.perf_counter() - t0) * 1e6)
        out[arm["id"]] = {"p50_us": round(statistics.median(samples), 1), "p95_us": round(_pctl(samples, .95), 1)}
    return out


# --------------------------------------------------------------------- report
def render_markdown(r: dict) -> str:
    arms = r["arms"]
    L = ["# Outcome-scored routing experiment (v0.5)", "",
         f"{r['inputs']['turns']} turns in {r['inputs']['sessions']} synthetic sessions. Every deterministic path ran real "
         "Python handlers through `LocalHarness`. **No model was called.** Model paths are scored on whether the exact "
         "context packet contained the facts the turn needed.", "",
         "Generated by `python -m turnwise_lab.arena`. Pre-registration: "
         "[`docs/preregistration-v0.5.md`](../docs/preregistration-v0.5.md).", "",
         "## Arms", "",
         "| Arm | Correct* | Failures | Model calls | Turns with 0 model calls | Silent misses | False holds | Context chars sent to models | Router invocations |",
         "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for a in arms:
        s = a["summary"]
        L.append(f"| {a['label']} | {s['correct']}/{s['turns']} | {s['failures']} | {s['model_calls']} | "
                 f"{s['zero_model_call_turns']} | {s['outcomes']['silent_miss']} | {s['outcomes']['false_hold']} | "
                 f"{s['model_input_chars']:,} | {s['router_invocations']} |")
    L += ["", "\\* *Correct* counts model paths as correct whenever the needed evidence was in context (or fetchable). "
          "That is an upper bound for every arm that calls a model, and it favours the agent.", "",
          "## Hypotheses (verdicts computed by code)", "", "| ID | Claim | Prediction | Observed | Verdict |",
          "|---|---|---|---|---|"]
    for h in r["hypotheses"]:
        obs = "; ".join(f"`{k}`: {v}" for k, v in h["observed"].items()) if h["id"] != "H7" else "see table below"
        L.append(f"| {h['id']} | {h['claim']} | {h['prediction']} | {obs} | **{h['verdict']}** |")
    h7 = next(h for h in r["hypotheses"] if h["id"] == "H7")["observed"]
    L += ["", "### Exchange rate versus the tool-calling agent", "",
          "| Arm | Model calls saved | Extra failures | Calls saved per extra failure |", "|---|---:|---:|---:|"]
    labels = {a["id"]: a["label"] for a in arms}
    for k, v in h7.items():
        L.append(f"| {labels[k]} | {v['model_calls_saved']} | {v['extra_failures']} | "
                 f"{v['calls_saved_per_extra_failure'] if v['calls_saved_per_extra_failure'] is not None else 'n/a'} |")
    L += ["", "## By turn family (correct / turns, model calls)", "",
          "| Family | Mode | Turns | " + " | ".join(a["id"] for a in arms) + " |",
          "|---|---|---:|" + "---|" * len(arms)]
    for fam, f in sorted(r["families"].items()):
        cells = [f"{f['arms'][a['id']]['correct']}/{f['turns']}, {f['arms'][a['id']]['model_calls']}" for a in arms]
        L.append(f"| {fam} | {f['mode']} | {f['turns']} | " + " | ".join(cells) + " |")
    L += ["", "## Every failure", ""]
    for a in arms:
        fails = [(t, t["results"][a["id"]]) for t in r["turns"] if t["results"][a["id"]]["outcome"] in FAILURES]
        L.append(f"### {a['label']}: {len(fails)}")
        for t, res in fails:
            miss = f"; missing {', '.join(res['missing'])}" if res.get("missing") else ""
            L.append(f"- `{t['id']}` **{res['outcome']}**: “{t['text']}” (path `{res['path']}`: {res['reason']}{miss})")
        if not fails:
            L.append("- none")
        L.append("")
    sw = r["budget_sweep"]
    L += ["## Context budget sweep (correct / model calls)", "",
          "| Budget (chars) | " + " | ".join(sw[0]["arms"]) + " |", "|---:|" + "---|" * len(sw[0]["arms"])]
    for row in sw:
        L.append(f"| {row['budget']:,} | " + " | ".join(f"{v['correct']} / {v['model_calls']}" for v in row["arms"].values()) + " |")
    s = r["safety"]
    L += ["", "## Safety red team", "",
          f"A compromised router forged approved plans for every requested write: **{s['forged_attempts']} attempts, "
          f"{s['unauthorized_executions']} executions.** Positive control (fully authorised host) reached the handler: "
          f"**{s['positive_control']['handler_reached']}**.", "",
          "## Assumptions", ""] + [f"- {x}" for x in r["assumptions"]]
    L += ["", "Not measured: " + ", ".join(r["not_measured"]) + ".", "",
          "Post-freeze changes: " + ("; ".join(r["post_freeze_changes"]) if r["post_freeze_changes"] else "none") + ".", "",
          f"Sessions SHA-256: `{r['inputs']['sessions_sha256']}`  ", f"Route-train SHA-256: `{r['inputs']['route_train_sha256']}`", ""]
    return "\n".join(L)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--sessions", type=Path, default=SESSIONS_PATH)
    p.add_argument("--budget", type=int, default=DEFAULT_BUDGET)
    p.add_argument("--output", type=Path, default=ROOT / "reports" / "arena.json")
    p.add_argument("--markdown", type=Path, default=ROOT / "reports" / "arena.md")
    p.add_argument("--timing", action="store_true", help="also print local Python timing (not committed)")
    args = p.parse_args()
    report = run_experiment(args.sessions, args.budget)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text(render_markdown(report), encoding="utf-8")
    print(f"{report['inputs']['turns']} turns, {len(report['arms'])} arms, no model calls made.")
    for a in report["arms"]:
        s = a["summary"]
        print(f"  {a['id']:<22} correct {s['correct']:>2}/{s['turns']}  model calls {s['model_calls']:>3}  "
              f"silent misses {s['outcomes']['silent_miss']}  false holds {s['outcomes']['false_hold']}")
    for h in report["hypotheses"]:
        print(f"  {h['id']}: {h['verdict']}")
    if args.timing:
        print(json.dumps(local_timing(args.sessions), indent=1))


if __name__ == "__main__":
    main()
