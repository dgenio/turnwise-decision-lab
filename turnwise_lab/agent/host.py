"""The host: the only component allowed to execute anything.

A decision model *proposes*. The host checks the operation type, the target
capability, the argument schema, the caller's permissions, side-effect
metadata, repeats and budgets, and only then executes through the same
``LocalHarness`` boundary used since v0.4. Writes are never executed here:
they end in an approval request. Nothing a provider returns can change that.

A write proposal becomes an approval request only when the *user* positively
requested that action, on that target, in this turn (``intent.py``). Mentioning a
service is not a request, and neither is model output, tool output, a controller
hint or an assistant turn. The same check applies to every proposer that reaches
the host: a controller step, the tool-capable heavy handoff and the heavy-only
baseline. Final action statuses come from the host's own receipts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
import json

from ..core import Capability as HarnessCapability, Plan, Request
from ..runtime import HostIdentity, LocalHarness, RegisteredAction
from .contracts import MODEL_OUTCOMES, OPERATIONS, PROPOSABLE, TIERS, Decision, ModelOutcome, Observation
from .evidence import assess_evidence
from .intent import analyse as analyse_intent, completion_claims, resolve_write
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
    evidence_reference_time: datetime | None = None  # historical replays have no implicit wall clock
    max_evidence_age_seconds: int = 3600


@dataclass
class Validation:
    ok: bool
    decision: Decision
    status: str  # accepted | rejected | approval_required
    reason: str
    dropped: list[str] = field(default_factory=list)
    evidence: dict | None = None
    intent: dict | None = None  # write proposals only: the host's verdict on whether the user requested it


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
        self._intent_cache: dict = {}

    # -------------------------------------------------------------- policy
    def allowed_capabilities(self) -> tuple[Capability, ...]:
        """What the decision model may *propose*. Writes are listed: proposing one yields an approval request."""
        return CATALOG

    def validate(self, d: Decision, executed: list[Observation], *, user_message: str = "",
                 conversation: tuple[dict, ...] | list[dict] = ()) -> Validation:
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
                return self.validate_write(d, cap, args, executed, user_message, conversation)
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
        if d.operation == "handoff_heavy":
            if d.target is not None or d.arguments or d.model_tier != "heavy":
                return Validation(False, d, "rejected", "heavy handoff takes no target or arguments and requires heavy tier")
            return Validation(True, d, "accepted", "tool-capable heavy handoff proposed; host limits still apply")
        if d.operation == "finish":
            review = assess_evidence(
                user_message, executed, conversation=conversation,
                as_of=self.limits.evidence_reference_time,
                max_age_seconds=self.limits.max_evidence_age_seconds,
            ).as_json()
            if not review["sufficient"]:
                failures = review["missing"] + review["problems"]
                return Validation(False, d, "rejected",
                                  "insufficient evidence for deterministic finish: " + ", ".join(failures),
                                  evidence=review)
            return Validation(True, d, "accepted", "task-specific verified evidence sufficient for data-only reply",
                              evidence=review)
        return Validation(True, d, "accepted", f"{d.operation} permitted")

    def validate_write(self, d: Decision, cap: Capability, args: dict, executed: list[Observation],
                       user_message: str, conversation) -> Validation:
        """A write is never executed; it is held for approval only if the user requested exactly this action."""
        verdict = self.check_write_intent(cap.id, args, user_message, conversation)
        if not verdict["ok"]:
            return Validation(False, d, "rejected", f"{verdict['code']}: {verdict['reason']}", intent=verdict)
        if any(o.status == "approval_required" and o.target == cap.id and o.arguments == args for o in executed):
            return Validation(False, d, "rejected", "duplicate_hold: approval for this action was already requested in this turn",
                              intent={**verdict, "ok": False, "code": "duplicate_hold"})
        return Validation(True, d, "approval_required", "side-effecting capability: requires independent human approval",
                          intent=verdict)

    def review_model_outcome(self, generation: dict) -> ModelOutcome | None:
        """Validate an optional typed model outcome, without granting any authority.

        None preserves the frozen untyped v0.6 behaviour. A malformed typed
        outcome is an error observation, never an answer or executable tool call.
        This contract is structural; generated answer correctness is still
        subject to separate evidence/outcome evaluation.
        """
        raw = generation.get("outcome")
        if raw is None:
            return None
        if generation.get("status") != "ok":
            return ModelOutcome("error", "typed generator did not report successful generation")
        if not isinstance(raw, dict) or raw.get("kind") not in MODEL_OUTCOMES:
            return ModelOutcome("error", "unknown model outcome")
        kind, call = raw["kind"], raw.get("proposed_call")
        if kind == "tool_proposal":
            if not (isinstance(call, dict) and call.get("operation") in PROPOSABLE
                    and isinstance(call.get("target"), str) and bool(call["target"])
                    and isinstance(call.get("arguments"), dict)
                    and all(isinstance(k, str) for k in call["arguments"])):
                return ModelOutcome("error", "malformed tool proposal")
            return ModelOutcome(kind, "model proposed a call; policy must decide and host must validate",
                                {"operation": call["operation"], "target": call["target"],
                                 "arguments": dict(call["arguments"])})
        if call is not None:
            return ModelOutcome("error", f"{kind} cannot carry a proposed call")
        if kind == "answer_candidate":
            if not isinstance(generation.get("text"), str) or not generation["text"].strip():
                return ModelOutcome("error", "empty or malformed answer candidate")
        return ModelOutcome(kind, {"answer_candidate": "typed answer candidate (not verified)",
                                   "needs_evidence": "model reports missing evidence",
                                   "error": "model reported an error"}[kind])

    # ------------------------------------------------------------ user intent
    def action_intents(self, user_message: str, conversation=()) -> dict:
        """The host's reading of which writes the user requested, declined or left unclear (no model involved)."""
        key = (user_message, tuple((m.get("role"), str(m.get("content", ""))) for m in conversation or ()))
        if key not in self._intent_cache:
            self._intent_cache[key] = analyse_intent(user_message, conversation)
        return self._intent_cache[key]

    def check_write_intent(self, capability: str, arguments: dict, user_message: str, conversation=()) -> dict:
        return resolve_write(capability, arguments, self.action_intents(user_message, conversation))

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
    def render_verified(self, observations: list[Observation], *, evidence: dict) -> str:
        """Only render relevant, receipt-backed facts after the host's FINISH gate."""
        if not evidence.get("sufficient"):
            raise ValueError("verified rendering requires a sufficient host evidence review")
        approved = set(evidence["verified"])
        lines, seen = [], set()
        for o in observations:
            if o.status != "ok":
                continue
            for key, value in o.facts.items():
                if key not in approved or key in seen:
                    continue
                lines.append(f"{key}: {json.dumps(value, separators=(', ', ': '), sort_keys=True)}")
                seen.add(key)
        if set(seen) != approved:
            raise ValueError("verified rendering lost its supporting evidence")
        intro = ("Verified source facts (no causal inference established):\n"
                 if evidence["intent"] == "causal_investigation"
                 else "Verified data (no model used):\n")
        return intro + "\n".join(lines)

    def approval_message(self, obs: Observation) -> str:
        args = ", ".join(f"{k}={v}" for k, v in obs.arguments.items())
        return (f"{obs.target}({args}) needs approval from an authorised person. Nothing was executed; "
                "the request has been recorded for approval.")

    @staticmethod
    def confirm_actions_message(actions: list[str]) -> str:
        return ("Before anything is requested: did you want " + "; ".join(actions) + "? Nothing has been requested or "
                "executed. Confirm the action and its target and it will go to an authorised person for approval.")

    def review_generated_answer(self, text: str) -> dict:
        """Claims in a generated reply that a write happened. This host cannot execute writes, so any is unsupported."""
        return {"unsupported_action_claims": completion_claims(text)}

    @staticmethod
    def withheld_message(claims: list[dict]) -> str:
        caps = ", ".join(sorted({c["capability"] for c in claims}))
        return ("I withheld a generated reply because it described an action as done or under way "
                f"({caps}) and the host has no record of executing it. No action has been executed in this turn.")

    def compose_final(self, final: dict, ledger: list[dict], denied: list[dict]) -> dict:
        """Host-owned final envelope: action statuses come from host receipts, never from model prose.

        Every action the user requested ends visibly: held for approval, named in a host
        confirmation question, listed as not attempted, or recorded as declined. Denied
        write proposals (from any model or controller) are kept for audit and are never
        turned into user intents or approval requests.
        """
        final = dict(final)
        kind = final.get("kind")
        status = [dict(e) for e in ledger]
        open_ = [e for e in status if e["status"] in ("requested", "needs_clarification")]
        described = [describe_action(e) for e in open_]
        if open_ and kind in ("approval_required", "verified", "answer", "clarify"):
            for e in open_:
                e["status"] = "needs_confirmation"
            if kind == "answer":  # model prose cannot speak for a pending action
                final["model_text"] = final.get("text")
                final["text"], final["by"] = "", "host"
            if kind != "approval_required":
                final["kind"] = "clarify"
                final["reason"] = f"requested action not submitted for approval ({final.get('reason', '')})"
            final["text"] = "\n".join(t for t in (final.get("text") or "", self.confirm_actions_message(described)) if t)
        elif open_:
            for e in open_:
                e["status"] = "not_attempted"
            final["text"] = (final.get("text") or "") + " Not attempted: " + "; ".join(described) + "."
        final["action_status"] = status
        final["denied_write_proposals"] = [dict(d) for d in denied]
        final["writes_executed"] = len(self.world.write_ledger)
        return final

    @staticmethod
    def clarify_message() -> str:
        return "I need a bit more detail to do this safely: which service or change do you mean?"

    @staticmethod
    def abstain_message(reason: str) -> str:
        return f"I stopped without an answer to avoid guessing ({reason}). Please escalate to the incident commander."

    @staticmethod
    def host_facts() -> dict:
        return dict(HOST_FACTS)


def describe_action(entry: dict) -> str:
    args = entry.get("arguments")
    if args is None:
        return f"{entry['capability']}() with its target not specified"
    if args.get("message", "") is None:
        return f"{entry['capability']}() with the text still to be written"
    return f"{entry['capability']}({', '.join(f'{k}={v}' for k, v in args.items())})"
