"""Turnwise Core: a typed decision policy chooses every operation.

The whole architectural idea fits in one loop::

    while within budget:
        snapshot    = runtime.snapshot()            # task + bounded, typed observations
        decision    = policy.decide(snapshot)       # an untrusted, typed proposal
        verdict     = host_validates(decision)      # the host, not the policy, says yes or no
        observation = execute(decision)             # host tool/workflow, or ONE bounded model call
        # ... and the observation goes back to the policy, including model results

A capable model is an *operation* the policy may choose (``CALL_HEAVY``), not
the controller of the loop. When the model wants a tool, that request comes
back as a typed ``ModelOutcome(kind="tool_proposal")``; the policy may adopt
it, ignore it or escalate, and the host still validates whatever is chosen.
A model's answer is only an *answer candidate*; ``FINISH`` is a host-checked
decision, and the check is about receipts and citations, not causal truth.

``HANDOFF_AGENT`` (transfer control to a native agent for several steps) is
supported to make the contrast explicit. It is a different architecture: while
it runs, the native agent -- not the policy -- chooses the operations.

This module is framework-neutral and stdlib-only. Frameworks plug in through
``ModelPort`` (how to invoke a model once). They do not get a control loop.
"""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, replace
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Protocol, Union

from .incident_env import INCIDENT_RECORD, IncidentHost, Receipt, ToolSpec
from .trace import RunResult, TraceRow, status_tag, host_text

CONTROLLER = "Turnwise policy"
NATIVE = "native agent (handoff)"

# The version of the typed contract below: the Op vocabulary, the StepOutcome kinds and their meaning.
# Bump it (and tests/test_architecture_action_integrity.py) whenever either changes (#20).
CONTRACT_VERSION = "turnwise-core/1"


class Op(str, Enum):
    DIRECT = "DIRECT"  # return a host-verified record; no model
    CALL_TOOL = "CALL_TOOL"  # one registered tool, executed by the host
    CALL_WORKFLOW = "CALL_WORKFLOW"  # one registered deterministic workflow, executed by the host
    CALL_LIGHT = "CALL_LIGHT"  # one bounded call to the cheaper model
    CALL_HEAVY = "CALL_HEAVY"  # one bounded call to the capable model
    CLARIFY = "CLARIFY"  # stop visibly: information is missing
    HOLD = "HOLD"  # stop visibly: authorisation or evidence is missing
    FINISH = "FINISH"  # ask the host to accept a model's answer candidate
    HANDOFF_AGENT = "HANDOFF_AGENT"  # contrast only: give a native agent control for a bounded segment


TERMINAL = frozenset({Op.DIRECT, Op.FINISH, Op.HOLD, Op.CLARIFY})
MODEL_OPS = {Op.CALL_LIGHT: "light", Op.CALL_HEAVY: "heavy"}
OUTCOME_KINDS = ("answer_candidate", "tool_proposal", "needs_evidence")

STEP_CONTRACT = (
    "You are being called for ONE step of a run that a Turnwise decision policy controls. "
    "In this step no tool is callable; this overrides any instruction above to use tools. "
    "Read the JSON packet and reply with exactly one StepOutcome: "
    "kind='answer_candidate' with the answer in text and the receipt ids you relied on in cited_receipts; "
    "or kind='tool_proposal' with one tool from tools_you_may_propose and its arguments as a JSON object "
    "string in arguments_json; or kind='needs_evidence' explaining in text what is missing. "
    "A proposal is a request, not an action: the policy decides and the host validates."
)


# ---------------------------------------------------------------- typed contracts
@dataclass(frozen=True)
class Decision:
    """What the policy wants to happen next. A proposal, never an authorisation."""

    op: Op
    reason: str
    target: str | None = None  # tool/workflow id, or the fact key for DIRECT
    arguments: Mapping[str, Any] | None = None
    context: tuple[str, ...] = ()  # receipt ids the model is shown
    may_propose: tuple[str, ...] = ()  # tools the model may ask for
    candidate: str | None = None  # model outcome id, for FINISH
    adopted_from: str | None = None  # model outcome whose tool proposal this adopts
    message: str | None = None  # for CLARIFY / HOLD

    def describe(self) -> str:
        if self.op in (Op.CALL_TOOL, Op.CALL_WORKFLOW):
            args = ", ".join(f"{k}={v}" for k, v in (self.arguments or {}).items())
            return f"{self.op.value} {self.target}({args})" + (
                f" [adopts {self.adopted_from}'s proposal]" if self.adopted_from else "")
        if self.op in MODEL_OPS or self.op is Op.HANDOFF_AGENT:
            return (f"{self.op.value} context=[{', '.join(self.context)}]"
                    + (f" may_propose=[{', '.join(self.may_propose)}]" if self.op in MODEL_OPS else ""))
        if self.op is Op.FINISH:
            return f"FINISH with answer candidate {self.candidate}"
        if self.op is Op.DIRECT:
            return f"DIRECT host-verified record '{self.target}'"
        return f"{self.op.value}: {self.message}"


@dataclass(frozen=True)
class ToolProposal:
    tool: str
    arguments: dict[str, Any]

    def call(self) -> str:
        return f"{self.tool}({', '.join(f'{k}={v}' for k, v in self.arguments.items())})"


@dataclass(frozen=True)
class ModelOutcome:
    """A typed observation produced by one model call. Data, never authority."""

    id: str
    source: str  # heavy_model | light_model | native_agent
    kind: str  # answer_candidate | tool_proposal | needs_evidence | invalid
    text: str
    proposal: ToolProposal | None = None
    cited: tuple[str, ...] = ()
    shown: tuple[str, ...] = ()  # receipt ids that were in front of the model
    note: str = ""
    provider_rate_limited: bool = False  # Set by the host adapter, never parsed from model text.
    # Also set by the runtime from the classified failure, never from model text: the provider or transport
    # failed (timeout, connection error, HTTP error). Calling again would repeat the failed request.
    provider_failed: bool = False

    def summary(self) -> str:
        if self.kind == "tool_proposal" and self.proposal:
            return f"{self.id} tool_proposal {self.proposal.call()}: {_clip(self.text)}"
        if self.kind == "answer_candidate":
            return f"{self.id} answer_candidate citing [{', '.join(self.cited)}]: {_clip(self.text)}"
        return f"{self.id} {self.kind}: {_clip(self.text or self.note)}"


Observation = Union[Receipt, ModelOutcome]


@dataclass(frozen=True)
class Budget:
    max_steps: int = 12
    max_model_calls: int = 4
    max_tool_calls: int = 6
    max_rejections: int = 3
    handoff_max_turns: int = 6


@dataclass(frozen=True)
class Snapshot:
    """Everything the policy may look at. Built by the runtime from host state.

    It holds the task, host-parsed referents and permissions, typed
    observations, the host's last rejection and the remaining budget. It never
    holds evaluation labels, expected routes or fixture ids. It is a copy: a
    policy that changes it changes nothing the host relies on.
    """

    task: str
    step: int
    services: tuple[str, ...]  # services the *user* named (host-parsed)
    requested_writes: tuple[tuple[str, str], ...]  # writes the *user* asked for (host-parsed)
    verified_fact_keys: tuple[str, ...]
    tools: tuple[ToolSpec, ...]
    receipts: tuple[Receipt, ...]
    outcomes: tuple[ModelOutcome, ...]
    latest: Observation | None
    budget_left: Mapping[str, int]
    last_rejection: str | None = None  # why the host refused the previous decision, if it did

    def tool(self, tool_id: str) -> ToolSpec | None:
        return next((t for t in self.tools if t.id == tool_id), None)

    def tool_for_role(self, role: str) -> ToolSpec | None:
        return next((t for t in self.tools if t.role == role), None)

    def attempted(self, tool_id: str, arguments: Mapping[str, Any]) -> bool:
        return any(r.tool == tool_id and r.arguments == dict(arguments) for r in self.receipts)


class Policy(Protocol):
    name: str

    def decide(self, snapshot: Snapshot) -> Decision: ...


class RunHalt(Exception):
    """Stop the run at once, e.g. a provider spending cap. Not an observation for the policy.

    A framework or port may re-raise it wrapped in another exception, so the
    runtime looks for it along the whole exception chain.
    """


class ModelCallFailed(Exception):
    """A port's classified model-call failure: ``category`` is e.g. refusal, timeout, invalid structured output."""

    def __init__(self, category: str, detail: str):
        super().__init__(f"{category}: {detail}")
        self.category, self.detail = category, detail


class ModelPort(Protocol):
    """How a framework invokes a model for exactly one Turnwise operation."""

    label: str  # SIMULATED ... or LIVE ...; printed in every trace
    describe: str  # the framework API used for one model call

    def call(self, tier: str, packet: dict[str, Any]) -> Mapping[str, Any]: ...

    def handoff(self, task_text: str, max_turns: int) -> str | HandoffReport: ...


@dataclass(frozen=True)
class HandoffReport:
    """What a ``HANDOFF_AGENT`` segment returns when the framework can say how many model calls it made.

    ``model_calls`` comes from the framework's own record of the native agent's run (for example one
    entry per model response). A port that returns a plain string, or a count that is not a non-negative
    integer, is recorded as ``unknown``: the agent's calls are never reported as 0.
    """

    text: str
    model_calls: int | None = None


# ---------------------------------------------------------------- the runtime
class TurnwiseRuntime:
    def __init__(self, host: IncidentHost, policy: Policy, model: ModelPort, *, budget: Budget = Budget(),
                 framework: str = "no framework"):
        self.host, self.policy, self.model, self.budget, self.framework = host, policy, model, budget, framework
        self.outcomes: list[ModelOutcome] = []
        self.snapshots: list[Snapshot] = []  # every snapshot the policy was given (for tests/inspection)
        self.rows: list[TraceRow] = []
        self._latest: Observation | None = None
        self._rejections = 0
        self._model_calls = 0  # CALL_LIGHT / CALL_HEAVY: exactly one model call each
        self._handoffs = 0  # HANDOFF_AGENT: the agent makes its own model calls inside
        self._handoff_model_calls: list[int | None] = []  # per handoff: reported model calls, or None (unknown)
        self._last_rejection: str | None = None
        self._adopted: dict[str, str] = {}  # model outcome id -> receipt id of the policy decision that adopted it

    # -- what the policy sees
    def remaining(self, step: int) -> dict[str, int]:
        """Remaining budget, computed from the runtime's own counters (never from anything the policy holds)."""
        tool_calls = sum(1 for r in self.host.receipts if r.proposed_by != "native_agent")
        return {"steps": self.budget.max_steps - step + 1,
                "model_calls": self.budget.max_model_calls - self._model_calls - self._handoffs,
                "tool_calls": self.budget.max_tool_calls - tool_calls}

    def snapshot(self, step: int) -> Snapshot:
        # Deep copies: the policy may read everything and change nothing the host relies on.
        receipts = copy.deepcopy(tuple(self.host.receipts))
        outcomes = copy.deepcopy(tuple(self.outcomes))
        latest = None if self._latest is None else next(
            o for o in (*receipts, *outcomes) if o.id == self._latest.id)
        return Snapshot(
            task=self.host.user_request, step=step,
            services=self.host.services_named_by_user(),
            requested_writes=tuple(sorted(self.host.requested_writes)),
            verified_fact_keys=tuple(sorted(INCIDENT_RECORD)),
            tools=self.host.tools, receipts=receipts, outcomes=outcomes, latest=latest,
            budget_left=MappingProxyType(self.remaining(step)),
            last_rejection=self._last_rejection,
        )

    def run(self) -> RunResult:
        for step in range(1, self.budget.max_steps + 1):
            snap = self.snapshot(step)
            self.snapshots.append(snap)
            decision = self.policy.decide(snap)
            ok, why = self.host_validates(decision, step)
            if not ok:
                self._reject(step, decision, why)
                if self._rejections >= self.budget.max_rejections:
                    return self._result("stopped", "Stopped: too many decisions were rejected by the host.")
                continue
            self._last_rejection = None
            if decision.op in TERMINAL:
                return self._terminal(step, decision)
            try:
                if decision.op in (Op.CALL_TOOL, Op.CALL_WORKFLOW):
                    self._execute_tool(step, decision)
                    if self._rejections >= self.budget.max_rejections:
                        return self._result("stopped", "Stopped: too many requests were rejected by the host.")
                elif decision.op in MODEL_OPS:
                    self._call_model(step, decision, MODEL_OPS[decision.op])
                else:
                    self._handoff(step, decision)
            except _Halted as halt:
                self.rows.append(TraceRow(str(step), CONTROLLER, decision.describe(), f"HALTED: {halt}",
                                          "run stops; nothing goes back to the policy", why=decision.reason,
                                          short=f"policy -> {decision.op.value} [halted]"))
                return self._result("stopped", f"Stopped: {halt}.")
        return self._result("stopped", "Stopped: step budget exhausted before a host-accepted result.")

    # -- host validation of a policy decision (independent of the policy and of its snapshot)
    def host_validates(self, d: Any, step: int) -> tuple[bool, str]:
        left = self.remaining(step)
        if not isinstance(d, Decision) or not isinstance(d.op, Op):
            return False, "the policy did not return a typed Decision"
        if not d.reason.strip():
            return False, "a decision must state its reason"
        if d.op in (Op.CALL_TOOL, Op.CALL_WORKFLOW):
            spec = next((t for t in self.host.tools if t.id == d.target), None)
            if spec is None:
                return False, f"unregistered capability {d.target!r}"
            if (spec.kind == "workflow") != (d.op is Op.CALL_WORKFLOW):
                return False, f"{d.target} is a {spec.kind}, not a {d.op.value} target"
            if not isinstance(d.arguments, Mapping):
                return False, "tool arguments are missing"
            if left["tool_calls"] <= 0:
                return False, "tool budget exhausted"
            if d.adopted_from is not None:
                src = next((o for o in self.outcomes if o.id == d.adopted_from), None)
                if src is None or src.proposal is None or (src.proposal.tool, src.proposal.arguments) != (
                        d.target, dict(d.arguments)):
                    return False, f"claims to adopt {d.adopted_from}'s proposal but does not match it"
            return True, ""
        if d.op in MODEL_OPS or d.op is Op.HANDOFF_AGENT:
            if left["model_calls"] <= 0:
                return False, "model budget exhausted"
            unknown = [c for c in d.context if not (self.host.receipt(c) and self.host.receipt(c).executed)]
            if unknown:
                return False, f"context may only contain executed host receipts; not {unknown}"
            if any(t not in {spec.id for spec in self.host.tools} for t in d.may_propose):
                return False, "may_propose lists an unregistered tool"
            return True, ""
        if d.op is Op.DIRECT:
            if self.host.requested_writes:
                return False, "DIRECT would silently drop a user-requested action; require host disposition"
            return (True, "") if self.host.verified_fact(d.target or "") is not None else (
                False, f"no host-verified record named {d.target!r}")
        if d.op is Op.FINISH:
            return self._check_finish(d)
        if not (d.message or "").strip():
            return False, f"{d.op.value} must say what is missing"
        if self._claims_unexecuted_action(d.message):
            return False, f"{d.op.value} message mentions a completed side effect that no host receipt shows"
        if (claim_problem := self.host.approval_claim_problem(d.message)) is not None:
            return False, f"{d.op.value} message: {claim_problem}"
        return True, ""

    def _claims_unexecuted_action(self, text: str) -> bool:
        """A conservative keyword screen, not a semantic check: any mention of a completed side effect is
        refused unless a host receipt shows an executed write (negated mentions are refused too)."""
        writes = {t.id for t in self.host.tools if t.side_effect}
        return bool(_ACTION_CLAIM.search(text)) and not any(r.executed and r.tool in writes for r in self.host.receipts)

    def _check_finish(self, d: Decision) -> tuple[bool, str]:
        cand = next((o for o in self.outcomes if o.id == d.candidate), None)
        if cand is None or cand.kind != "answer_candidate":
            return False, "FINISH must name an answer candidate produced by a model in this run"
        if not cand.cited:
            return False, f"{cand.id} cites no host evidence"
        bad = [c for c in cand.cited
               if c not in cand.shown or not (self.host.receipt(c) and self.host.receipt(c).executed)]
        if bad:
            return False, f"{cand.id} cites {bad}, which are not executed receipts it was shown"
        if self.host.requested_writes:
            return False, "FINISH cannot replace an outstanding requested action with generated prose; require host disposition"
        if self._claims_unexecuted_action(cand.text):
            return False, f"{cand.id} mentions a completed side effect that no host receipt shows as executed"
        missing = self.host.missing_evidence(cand.cited)
        if missing:
            return False, f"{cand.id} lacks task-scoped executed/cited evidence: {', '.join(missing)}"
        return True, ""

    # -- execution
    def _execute_tool(self, step: int, d: Decision) -> None:
        r = self.host.execute(d.target, d.arguments, proposed_by="turnwise_policy")
        self._latest = r
        if d.adopted_from:
            self._adopted[d.adopted_from] = r.id
        self.rows.append(TraceRow(str(step), CONTROLLER, d.describe(), host_text(r),
                                  f"{r.summary()} -> back to the policy", why=d.reason,
                                  short=f"policy -> {d.op.value} {d.target}" + status_tag(r)
                                  + (f" (adopts {d.adopted_from})" if d.adopted_from else "")))
        if r.status == "rejected":
            self._rejections += 1

    def _call_model(self, step: int, d: Decision, tier: str) -> None:
        packet = self._packet(d, tier)
        self._model_calls += 1
        rate_limited = provider_failed = False
        try:
            raw = self.model.call(tier, packet)
        except Exception as exc:  # a failed model call is an observation, not a crash or an answer...
            _raise_if_halt(exc)  # ...unless it is a halt (e.g. the provider spending cap): then the run stops
            failure = describe_failure(exc)
            rate_limited = isinstance(exc, ModelCallFailed) and exc.category == "provider error HTTP 429"
            provider_failed = rate_limited or failure.startswith(_PROVIDER_FAILURES)
            raw = {"kind": "invalid", "text": f"model call failed: {failure}"}
        outcome = parse_outcome(raw, oid=f"m{len(self.outcomes) + 1}", source=f"{tier}_model", shown=d.context)
        if provider_failed:
            outcome = replace(outcome, provider_rate_limited=rate_limited, provider_failed=True)
        self.outcomes.append(outcome)
        self._latest = outcome
        self.rows.append(TraceRow(
            str(step), CONTROLLER, d.describe(),
            f"validated; called the {tier} model once via {self.model.describe}",
            f"{outcome.summary()} -> back to the policy", why=d.reason,
            short=f"policy -> {d.op.value} => " + (
                f"proposes {outcome.proposal.tool}" if outcome.proposal else outcome.kind.replace("_", " "))))

    def _handoff(self, step: int, d: Decision) -> None:
        self._handoffs += 1
        before = len(self.host.receipts)
        halt: BaseException | None = None
        model_calls: int | None = None
        try:
            returned = self.model.handoff(handoff_message(self.host, d.context), self.budget.handoff_max_turns)
        except Exception as exc:  # e.g. not supported, or the agent hit its turn limit: an observation, not a crash
            halt = exc if _find_halt(exc) is not None else None
            text, failure = "", f"handoff ended without an answer: {describe_failure(exc)}"
        else:
            failure = ""
            text = returned.text if isinstance(returned, HandoffReport) else returned
            reported = returned.model_calls if isinstance(returned, HandoffReport) else None
            if type(reported) is int and reported >= 0:  # bool, float, str and negatives stay unknown
                model_calls = reported
        self._handoff_model_calls.append(model_calls)
        new = self.host.receipts[before:]
        self.rows.append(TraceRow(str(step), CONTROLLER, d.describe(),
                                  f"validated; control TRANSFERRED to the native agent (max {self.budget.handoff_max_turns} turns)",
                                  "the native agent now chooses operations itself", why=d.reason,
                                  short="policy -> HANDOFF_AGENT"))
        for i, r in enumerate(new, start=1):
            self.rows.append(TraceRow(f"{step}.{i}", NATIVE, f"tool call {r.call()}", host_text(r), r.summary(),
                                      short=f"native agent -> tool {r.tool}" + status_tag(r)))
        if halt is not None:  # the native agent's own tool calls are in the trace above; then the run stops
            _raise_if_halt(halt)
        # A native agent declares no citations. The runtime attaches every executed receipt the agent was given
        # or produced, and says so: for a handoff, FINISH's citation check is therefore weak.
        cited = tuple(d.context) + tuple(r.id for r in new if r.executed)
        outcome = ModelOutcome(f"m{len(self.outcomes) + 1}", "native_agent",
                               "answer_candidate" if text.strip() else "invalid", text, cited=cited, shown=cited,
                               note=failure or "runtime-attached citations")
        self.outcomes.append(outcome)
        self._latest = outcome
        self.rows.append(TraceRow(f"{step}.{len(new) + 1}", NATIVE, "final answer -> control returns to the policy",
                                  "not consulted until the policy decides again", outcome.summary(),
                                  short="native agent -> answer, back to policy"))

    def _terminal(self, step: int, d: Decision) -> RunResult:
        if d.op is Op.DIRECT:
            value = self.host.verified_fact(d.target)
            answer = f"{d.target.replace('_', ' ')}: {value} (host-verified incident record {INCIDENT_RECORD['incident_id']})"
            host, status = "validated; value read from the host's verified record (no model call)", "answered_directly"
        elif d.op is Op.FINISH:
            cand = next(o for o in self.outcomes if o.id == d.candidate)
            answer = cand.text
            if cand.source == "native_agent":
                cites = (f"citations [{', '.join(cand.cited)}] were attached by the runtime (the native agent "
                         "declares none), so this provenance check is weak")
            else:
                cites = f"its citations [{', '.join(cand.cited)}] are executed host receipts it was shown"
            host = (f"accepted {cand.id}: {cites}; the keyword screen found no claimed side effect. "
                    "Causal correctness is NOT verified.")
            status = "finished"
        elif d.op is Op.HOLD:
            answer, host, status = d.message or "", "validated; run stops visibly, nothing pending is executed", "held"
        else:
            answer, host, status = d.message or "", "validated; run stops and asks the user", "needs_clarification"
        self.rows.append(TraceRow(str(step), CONTROLLER, d.describe(), host, "run ends", why=d.reason,
                                  short=f"policy -> {d.op.value} [{status}]"))
        return self._result(status, answer)

    def _reject(self, step: int, d: Any, why: str) -> None:
        self._rejections += 1
        self._last_rejection = why
        desc = d.describe() if isinstance(d, Decision) else repr(d)
        reason = d.reason if isinstance(d, Decision) else ""
        self.rows.append(TraceRow(str(step), CONTROLLER, desc, f"REJECTED: {why}",
                                  "nothing executed -> back to the policy", why=reason,
                                  short=f"policy -> {getattr(getattr(d, 'op', None), 'value', '?')} [rejected]"))

    # -- the context packet: assembled by the host from receipts, as the policy selected
    def _packet(self, d: Decision, tier: str) -> dict[str, Any]:
        return {
            "turnwise_step": {"tier": tier, "step_contract": STEP_CONTRACT},
            "task": self.host.user_request,
            "evidence": [json.loads(self.host.receipt(rid).for_model()) for rid in d.context],
            "tools_you_may_propose": [
                {"name": t.id, "kind": t.kind, "description": t.description, "parameters": t.json_schema()}
                for t in self.host.tools if t.id in d.may_propose],
        }

    def _result(self, status: str, answer: str) -> RunResult:
        # #13: DIRECT and FINISH already refuse to end a run over an outstanding requested write. Every other
        # ending (HOLD, CLARIFY, a host stop) keeps its message and gets a host-written disposition appended,
        # so a request the user made is never dropped silently. The text comes from the host's own parse.
        unsubmitted = self.host.unsubmitted_requested_writes()
        if unsubmitted:
            answer = (f"{answer}\n\nHost: you requested {'; '.join(unsubmitted)}. It was not submitted, so no "
                      "approval request exists and nothing was executed.")
        notes = []
        for o in (o for o in self.outcomes if o.proposal):
            rid = self._adopted.get(o.id)
            notes.append(f"model proposal {o.id} {o.proposal.call()}: " + (
                f"adopted by the policy, host {self.host.receipt(rid).status} ({rid})" if rid
                else "NOT adopted by the policy"))
        notes.append(self.host.action_record())
        # The label comes from what happened, not from what the policy calls itself.
        architecture = "Agent handoff (contrast; NOT Turnwise Core)" if self._handoffs else "Turnwise Core"
        title = f"{architecture} -- same agent, policy: {self.policy.name} ({self.framework})"
        counts: dict[str, int | str] = {"policy_decisions": len(self.snapshots),
                                         "model_calls_chosen_by_policy": self._model_calls}
        if self._handoffs:
            counts["handoffs"] = self._handoffs
            # The native agent's own model calls, from the framework's record; unknown if any handoff did not say.
            counts["model_calls_inside_handoffs"] = (
                "unknown" if None in self._handoff_model_calls else sum(self._handoff_model_calls))
        counts.update({"host_tool_requests": len(self.host.receipts), "rejected": self._rejections})
        return RunResult(title, self.model.label, self.host.user_request, status, answer, list(self.rows),
                         notes, counts, writes_executed=len(self.host.write_ledger))


# ---------------------------------------------------------------- helpers
class _Halted(Exception):
    """Internal: a RunHalt was found while executing a decision."""


def _exception_chain(exc: BaseException) -> list[BaseException]:
    chain, seen = [], set()
    while exc is not None and id(exc) not in seen:
        chain.append(exc)
        seen.add(id(exc))
        exc = exc.__cause__ or exc.__context__
    return chain


def _find_halt(exc: BaseException) -> RunHalt | None:
    return next((e for e in _exception_chain(exc) if isinstance(e, RunHalt)), None)


def _raise_if_halt(exc: BaseException) -> None:
    halt = _find_halt(exc)
    if halt is not None:
        raise _Halted(str(halt)) from exc


# Failure categories (from describe_failure) where the provider or transport failed, as opposed to a model that
# answered badly (invalid structured output, refusal, incomplete response, a function call in a tool-less step).
_PROVIDER_FAILURES = ("timeout", "connection error", "provider error HTTP")


def describe_failure(exc: BaseException) -> str:
    """Classify a failed model call for the trace. Framework-neutral: a port may raise ``ModelCallFailed`` with
    its own category; otherwise the exception chain's class names and HTTP status decide. Never an answer."""
    chain = _exception_chain(exc)
    classified = next((e for e in chain if isinstance(e, ModelCallFailed)), None)
    if classified is not None:
        return str(classified)[:240]
    names = {cls.__name__ for e in chain for cls in type(e).__mro__}
    status = next((s for s in (getattr(e, "status_code", None) for e in chain) if isinstance(s, int)), None)
    message = " ".join(str(exc).split())
    if _find_halt(exc) is not None:
        category = "run halted"
    elif "ModelRefusalError" in names:
        category = "refusal"
    elif names & {"APITimeoutError", "ModelTimeoutError", "TimeoutException", "TimeoutError"}:
        category = "timeout"
    elif status is not None:
        category = f"provider error HTTP {status}"
    elif "incomplete" in message.lower():
        category = "incomplete response"
    elif names & {"ValidationError", "JSONDecodeError"} or (
            "ModelBehaviorError" in names and ("JSON" in message or "validat" in message.lower())):
        category = "invalid structured output"
    elif "ModelBehaviorError" in names:
        category = "model behavior error"
    elif names & {"MaxTurnsExceeded", "WorkflowRuntimeError"} and "max" in message.lower():
        category = "framework step limit reached"
    elif "APIConnectionError" in names:
        category = "connection error"
    else:
        category = "unclassified failure"
    return f"{category} ({type(exc).__name__}: {message[:160]})"


def handoff_message(host: IncidentHost, context: tuple[str, ...]) -> str:
    """What a native agent receives on HANDOFF_AGENT: the task, then one host receipt per line."""
    return "\n".join([host.user_request] + [host.receipt(rid).for_model() for rid in context])


# Any wording that reports a side effect as done, started or under way. Deliberately broad (negations match
# too): a screen that fails closed, while the authoritative status is ``action_record`` (host receipts).
# It covers the v0.6 H10 mechanism ("a rollback, which was initiated by the on-call engineer") and the
# adversarial ADV-003 phrasings ("I rolled checkout back", "was restored", "I undid", "switched ... back").
# It is a keyword screen, not a semantic check: an unlisted paraphrase can still pass (#13).
_DONE = (r"complete|completed|done|executed|performed|finished|applied|succeeded|initiated|triggered|started|"
         r"issued|launched|underway|under\s+way|in\s+progress|carried\s+out|kicked\s+off|went\s+through")
_ACTION_CLAIM = re.compile(
    r"\b(?:rolled[\s-]?back|reverted|paged|undone|undid|restored|reinstated)\b"
    # split verb phrases: "I rolled checkout back", "switched checkout back to build d-141" (ADV-003)
    r"|\b(?:rolled|switched|moved|put|set|flipped)\s+(?:[\w-]+\s+){0,3}?back\b"
    rf"|\b(?:rollback|revert|roll[\s-]?back)\b[^.!?]{{0,40}}?\b(?:{_DONE})\b"
    r"|\b(?:initiated|triggered|started|issued|launched|performed|executed|ran|kicked\s+off|carried\s+out)\b"
    r"[^.!?]{0,20}?\b(?:rollback|revert)\b"
    r"|\b(?:previous|prior|last\s+known\s+good)\s+(?:version|release|deploy(?:ment)?)\b[^.!?]{0,30}?"
    r"\b(?:restored|reinstated|redeployed)\b", re.IGNORECASE)


def parse_outcome(raw: Any, *, oid: str, source: str, shown: tuple[str, ...]) -> ModelOutcome:
    """Validate one raw model result into a typed observation. Malformed -> kind 'invalid'."""
    def invalid(why: str) -> ModelOutcome:
        return ModelOutcome(oid, source, "invalid", "", shown=shown, note=why)

    if not isinstance(raw, Mapping):
        return invalid("model result is not an object")
    kind, text = raw.get("kind"), raw.get("text")
    if kind not in OUTCOME_KINDS:
        return invalid(str(text or f"unknown outcome kind {kind!r}"))
    if not isinstance(text, str):
        return invalid("text must be a string")
    cited = raw.get("cited_receipts") or []
    if not isinstance(cited, list) or not all(isinstance(c, str) for c in cited):
        return invalid("cited_receipts must be a list of receipt ids")
    proposal = None
    if kind == "tool_proposal":
        tool, args_json = raw.get("tool"), raw.get("arguments_json")
        try:
            args = json.loads(args_json) if isinstance(args_json, str) else None
        except ValueError:
            args = None
        if not isinstance(tool, str) or not tool or not isinstance(args, dict) or not all(
                isinstance(k, str) for k in args):
            return invalid("tool_proposal needs a tool name and a JSON object of arguments")
        proposal = ToolProposal(tool, args)
    elif raw.get("tool"):
        return invalid(f"only a tool_proposal may name a tool (got {kind})")
    if kind == "answer_candidate" and not text.strip():
        return invalid("empty answer candidate")
    return ModelOutcome(oid, source, kind, text, proposal, tuple(cited), shown)


def _clip(text: str, limit: int = 140) -> str:
    text = " ".join((text or "").split())
    return '"' + (text if len(text) <= limit else text[: limit - 3] + "...") + '"'
