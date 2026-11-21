"""B': the Turnwise Core loop with a native-intercept model port. An ABLATION of the model interface (#87).

Turnwise Core (arm B) asks the model for one typed ``StepOutcome`` with **no tools attached**. That keeps the
property the hypothesis needs, *nothing a model emits is executed without a policy decision and host
validation*, but it also changes four other things at once: one proposal per call, a fresh packet instead of a
conversation, tool descriptions as text inside the input, and tool calls emulated as JSON in a string. A
difference between arm A and arm B therefore mixes "who controls" with "how the model is asked".

This module changes **only how the model is asked**. The policy, the host and the loop are the same:

    1. the model is called with the provider's real ``tools`` field and an append-only conversation;
    2. EVERY tool call in its response becomes a ``tool_proposal`` observation, and the policy is asked about
       each one in order. Nothing in the response is executed by the model call;
    3. the policy's adoption (``CALL_TOOL ... adopted_from=...``) is validated and executed by the host, as in
       arm B. A call the policy does not adopt is answered "declined by policy: <reason>", because the API
       requires every call to be answered;
    4. results the host obtained itself are appended to the conversation, labelled as host results.

Invariant 1 holds unchanged: the policy regains control after every observation, including each proposal.
Invariant 2 as worded in ``AGENTS.md`` says a model step "runs with no tools", and this port sends a ``tools``
field. So this is **labelled as an ablation, not as Turnwise Core**, until the owner decides whether to reword
that invariant. What it preserves is the narrower property above, and tests pin it.

How several proposals in one response are handled (the "consideration phase"): for each proposal in order the
runtime calls ``policy.decide`` with that proposal as the latest observation. Only an adoption acts. Any other
decision is read as "this proposal is declined, for this reason" and is NOT carried out; once every proposal
has been considered, the ordinary loop asks the policy for its next move. A terminal decision (``HOLD``,
``CLARIFY``, ...) ends the phase at once, with the remaining proposals unconsidered and unexecuted. A policy
written for arm B therefore works here unchanged. Every such call is counted as a policy decision.

Framework-neutral and stdlib-only. A framework supplies the port (``openai_agents/native_intercept.py``).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Any, Mapping, Protocol

from .incident_env import IncidentHost, ToolSpec
from .trace import RunResult, TraceRow
from .turnwise_core import (CONTROLLER, TERMINAL, Budget, Decision, ModelCallFailed, ModelOutcome, Op, Policy,
                            ToolProposal, TurnwiseRuntime, _Halted, _PROVIDER_FAILURES, _raise_if_halt,
                            describe_failure, handoff_message, parse_outcome)

ARCHITECTURE = "Turnwise Core loop, native-intercept model port (B' ablation; the model call carries a tools field)"

INTERCEPT_CONTRACT = (
    "You are being called for ONE step of a run that a Turnwise decision policy controls. "
    "A tool call you make is a request, not an action: the policy decides and the host validates, and you then "
    "receive either the host's result or the reason the call was declined. Results the host obtained itself "
    "arrive in messages that start with 'HOST RESULTS'. "
    "When you can answer, reply with a StepAnswer: kind='answer_candidate' with the answer in text and the "
    "receipt ids you relied on in cited_receipts; or kind='needs_evidence' explaining in text what is missing."
)
HOST_RESULTS = "HOST RESULTS (obtained by the host; you did not request them):"
NOT_CONSIDERED = "declined by policy: not considered"


@dataclass(frozen=True)
class NativeCall:
    """One tool call in a model response, exactly as the provider returned it. Data, never an action."""

    call_id: str
    tool: str
    arguments_json: str


@dataclass(frozen=True)
class NativeTurn:
    """What one model call returned: tool calls (proposals), or a typed final reply. Never both acted on."""

    calls: tuple[NativeCall, ...] = ()
    final: Mapping[str, Any] | None = None  # a StepAnswer as a mapping, when the response carried no tool call


@dataclass(frozen=True)
class CallAnswer:
    """How one earlier tool call is answered in the conversation."""

    adopted: bool
    text: str  # adopted: the host receipt the model sees; otherwise why the call was declined


class NativeInterceptPort(Protocol):
    """How a framework makes ONE model call with a real tools field and executes nothing."""

    label: str
    describe: str

    def native_step(self, tier: str, *, first_message: str, offered: tuple[ToolSpec, ...],
                    answers: Mapping[str, CallAnswer], host_results: tuple[str, ...]) -> NativeTurn: ...

    def handoff(self, task_text: str, max_turns: int) -> str: ...


@dataclass
class _OpenCall:
    """A tool call of the latest response of one tier: it must be answered before that tier is called again."""

    call_id: str
    outcome_id: str
    receipt_id: str | None = None  # set when the policy adopted it and the host produced a receipt
    reason: str = ""  # set when it was declined


class NativeInterceptRuntime(TurnwiseRuntime):
    """``TurnwiseRuntime`` with only ``_call_model`` replaced. The loop, validation and execution are inherited."""

    ARCHITECTURE = ARCHITECTURE

    def __init__(self, host: IncidentHost, policy: Policy, model: NativeInterceptPort, *, budget: Budget = Budget(),
                 framework: str = "no framework", max_proposals: int = 8):
        super().__init__(host, policy, model, budget=budget, framework=framework)  # type: ignore[arg-type]
        self.max_proposals = max_proposals  # tool calls the policy is asked about in one run; the rest are declined
        self.proposals_seen = 0  # every tool call any model response carried
        self.proposals_considered = 0
        self.proposals_declined = 0
        self._open: dict[str, list[_OpenCall]] = {}  # tier -> calls of its latest response
        self._shown: dict[str, list[str]] = {}  # tier -> receipt ids already in that tier's conversation
        self._offered: dict[str, tuple[str, ...]] = {}  # tier -> its tools field, fixed at the tier's first call

    # -- one model call: a real tools field, an append-only conversation, nothing executed
    def _call_model(self, step: int, d: Decision, tier: str) -> None:
        first = tier not in self._offered
        offered = self._offered.get(tier) or tuple(t.id for t in self.host.tools if t.id in d.may_propose)
        shown = self._shown.setdefault(tier, [])
        if not first and not set(d.may_propose) <= set(offered):
            # The tools field of a conversation is fixed (it is the start of the cacheable prefix). Refuse visibly.
            self._record_failure(step, d, tier, ModelCallFailed(
                "unsupported decision", "may_propose names a tool this conversation was not started with; the "
                                        "native-intercept port keeps one tools field per conversation"), called=False)
            return
        open_calls = self._open.get(tier, [])
        answers = {c.call_id: self._answer(c) for c in open_calls}
        delivered = [c.receipt_id for c in open_calls if c.receipt_id]
        new_context = [rid for rid in d.context if rid not in shown and rid not in delivered]
        self._model_calls += 1
        try:
            turn = self.model.native_step(
                tier, first_message=handoff_message(self.host, d.context) if first else "",
                offered=tuple(t for t in self.host.tools if t.id in offered), answers=answers,
                host_results=() if first else tuple(self.host.receipt(rid).for_model() for rid in new_context))
        except Exception as exc:  # a failed call is an observation; the conversation is unchanged, so nothing is lost
            _raise_if_halt(exc)
            self._record_failure(step, d, tier, exc, called=True)
            return
        # The call went through: its conversation now holds what was sent.
        self._offered[tier] = offered
        shown.extend(rid for rid in [*delivered, *new_context] if rid not in shown)
        self._open[tier] = []
        if not turn.calls:
            outcome = parse_outcome(turn.final, oid=f"m{len(self.outcomes) + 1}", source=f"{tier}_model",
                                    shown=tuple(shown))
            self.outcomes.append(outcome)
            self._latest = outcome
            self.rows.append(TraceRow(
                str(step), CONTROLLER, d.describe(),
                f"validated; called the {tier} model once via {self.model.describe}",
                f"{outcome.summary()} -> back to the policy", why=d.reason,
                short=f"policy -> {d.op.value} => " + outcome.kind.replace("_", " ")))
            return
        pending = []
        for call in turn.calls:
            self.proposals_seen += 1
            oid = f"m{len(self.outcomes) + 1}"
            args = _json_object(call.arguments_json)
            if args is None or not call.tool:
                outcome = ModelOutcome(oid, f"{tier}_model", "invalid", "", shown=tuple(shown),
                                       note=f"native tool call {call.tool or '?'}: arguments are not a JSON object")
            else:
                outcome = ModelOutcome(oid, f"{tier}_model", "tool_proposal", "", ToolProposal(call.tool, args),
                                       shown=tuple(shown), note="native tool call; not executed by the model call")
            self.outcomes.append(outcome)
            self._open[tier].append(_OpenCall(call.call_id, oid))
            pending.append((self._open[tier][-1], outcome))
        self._latest = pending[0][1]
        names = ", ".join(c.tool or "?" for c in turn.calls)
        self.rows.append(TraceRow(
            str(step), CONTROLLER, d.describe(),
            f"validated; called the {tier} model once via {self.model.describe}",
            f"{len(pending)} tool call(s) returned as proposals ({names}); NONE executed -> each goes to the policy",
            why=d.reason, short=f"policy -> {d.op.value} => proposes {names}"))
        self._consider(step, pending)

    # -- the consideration phase: the policy is asked about every proposal; only an adoption acts
    def _consider(self, step: int, pending: list[tuple[_OpenCall, ModelOutcome]]) -> None:
        for i, (call, outcome) in enumerate(pending, start=1):
            label = f"{step}.{i}"
            if outcome.kind != "tool_proposal":
                self._decline(label, call, outcome, "the arguments are not a JSON object", asked=False)
                continue
            if self.proposals_considered >= self.max_proposals:
                self._decline(label, call, outcome, f"proposal budget exhausted ({self.max_proposals} per run)",
                              asked=False)
                continue
            self.proposals_considered += 1
            self._latest = outcome
            snap = self.snapshot(step)
            self.snapshots.append(snap)  # counted: every proposal costs one policy decision
            decision = self.policy.decide(snap)
            adopts = (isinstance(decision, Decision) and decision.op in (Op.CALL_TOOL, Op.CALL_WORKFLOW)
                      and decision.adopted_from == outcome.id)
            if adopts:
                ok, why = self.host_validates(decision, step)
                if ok:
                    self._last_rejection = None
                    self._execute_tool(label, decision)  # the host validates the request itself and executes it
                    call.receipt_id = self._latest.id
                else:
                    self._reject(label, decision, why)
                    self._mark_declined(call, f"the host rejected the policy's decision: {why}")
                if self._rejections >= self.budget.max_rejections:
                    raise _Halted("too many requests were rejected by the host")
                continue
            reason = decision.reason if isinstance(decision, Decision) else "the policy returned no typed decision"
            self._decline(label, call, outcome, reason, asked=True)
            self._latest = outcome  # the policy's next decision starts from the proposal it declined
            if isinstance(decision, Decision) and decision.op in TERMINAL:
                for later, _ in pending[i:]:  # the policy is stopping the run: nothing further is considered
                    self._mark_declined(later, "not considered: the policy ended the run")
                return

    def _decline(self, label: str, call: _OpenCall, outcome: ModelOutcome, reason: str, *, asked: bool) -> None:
        self._mark_declined(call, reason)
        what = outcome.proposal.call() if outcome.proposal else outcome.note
        self.rows.append(TraceRow(
            label, CONTROLLER, f"does not adopt {outcome.id} {what}",
            "nothing executed" if asked else "nothing executed; the policy was not asked",
            "the call will be answered 'declined by policy' when the model is next called", why=reason,
            short=f"policy declines {outcome.id}"))

    def _mark_declined(self, call: _OpenCall, reason: str) -> None:
        call.reason = " ".join(reason.split())[:240]
        self.proposals_declined += 1

    def _answer(self, call: _OpenCall) -> CallAnswer:
        if call.receipt_id:
            return CallAnswer(True, self.host.receipt(call.receipt_id).for_model())
        return CallAnswer(False, f"declined by policy: {call.reason}" if call.reason else NOT_CONSIDERED)

    def _record_failure(self, step: int, d: Decision, tier: str, exc: BaseException, *, called: bool) -> None:
        failure = describe_failure(exc)
        rate_limited = isinstance(exc, ModelCallFailed) and exc.category == "provider error HTTP 429"
        provider_failed = rate_limited or failure.startswith(_PROVIDER_FAILURES)
        outcome = parse_outcome({"kind": "invalid", "text": f"model call failed: {failure}"},
                                oid=f"m{len(self.outcomes) + 1}", source=f"{tier}_model",
                                shown=tuple(self._shown.get(tier, ())))
        if provider_failed:
            outcome = replace(outcome, provider_rate_limited=rate_limited, provider_failed=True)
        self.outcomes.append(outcome)
        self._latest = outcome
        self.rows.append(TraceRow(
            str(step), CONTROLLER, d.describe(),
            (f"validated; called the {tier} model once via {self.model.describe}" if called
             else "validated; NOT sent to the model"),
            f"{outcome.summary()} -> back to the policy", why=d.reason,
            short=f"policy -> {d.op.value} => invalid"))

    def _result(self, status: str, answer: str) -> RunResult:
        result = super()._result(status, answer)
        result.counts.update({"model_tool_calls_returned_as_proposals": self.proposals_seen,
                              "proposals_declined": self.proposals_declined})
        result.notes.insert(0, "ABLATION (B'): the model was called with a tools field; every tool call came back "
                               "to the policy as a proposal and none was executed by a model call")
        return result


def _json_object(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text) if text else {}
    except ValueError:
        return None
    return value if isinstance(value, dict) and all(isinstance(k, str) for k in value) else None
