"""S -- the shielded native agent on the OpenAI Agents SDK (issue #88). Opt-in; not Turnwise Core.

The agent is the very same ``Agent`` as the conventional example (A): one system prompt, every
function tool, the SDK's own ``Runner`` loop. The model chooses every operation inside that loop.
The host acts only before the loop, on each tool call, and at the exit (see ``shield.py``).

``typed_citations=True`` changes one thing: the agent's final output type becomes ``CitedAnswer``
(text plus the receipt ids it relies on). The loop, tools and instructions are untouched, and the
exit check then verifies the citations against host receipts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List

from agents import ModelSettings, RunConfig, RunHooks, Runner, ToolCallOutputItem
from pydantic import BaseModel, Field

from ..incident_env import HostSession, IncidentHost
from ..shield import PROPOSER, HostFirst, exit_check, feedback_message, host_first
from ..trace import RunResult, TraceRow, _quote, conventional_rows, host_text, receipt_id_from_output
from .conventional import _decision, build_agent

TITLE = "Shielded native agent (S) -- OpenAI Agents SDK (host rules, then Agent + Runner.run_sync, then a host exit check)"


class CitedAnswer(BaseModel):
    """Final output type of the typed variant. The field descriptions are the only prompt text it adds."""

    text: str = Field(description="The answer for the user.")
    cited_receipts: List[str] = Field(
        description="Ids of the host tool receipts the answer relies on (the 'receipt' field of tool results).")


class _ModelCallCounter(RunHooks):
    """Counts every model request the SDK starts, so a run that raises still reports the calls it made."""

    def __init__(self) -> None:
        self.started = 0

    async def on_llm_start(self, context: Any, agent: Any, system_prompt: Any, input_items: Any) -> None:
        self.started += 1


@dataclass
class ShieldRecord:
    """Everything a caller needs to count or audit an S run. Kept beside the printable ``RunResult``."""

    path: str  # host_write_rule | host_record | host_clarification | native_agent
    native_called: bool = False
    native_answers: list[str] = field(default_factory=list)  # every answer the agent gave, accepted or not
    model_calls: int = 0  # model requests the SDK started, summed over feedback rounds; a failed request counts
    model_responses: int = 0  # model responses the SDK returned; lower than model_calls only when a run raised
    prefetched: tuple[str, ...] = ()
    exit_checks: list[dict[str, Any]] = field(default_factory=list)  # one per answer the agent gave
    feedback_rounds: int = 0  # how many rejected answers went back to the agent
    cited: tuple[str, ...] | None = None  # typed variant only: what the last answer cited
    failure: str | None = None


def run_shielded(task: str, model: Any, *, model_label: str, typed_citations: bool = False, max_feedback: int = 1,
                 max_turns: int = 10, model_settings: ModelSettings | None = None, host: IncidentHost | None = None,
                 checklist: bool = False) -> tuple[RunResult, ShieldRecord]:
    """Run one task under arm S. ``host`` may be passed in so a caller can read receipts if the agent raises.

    ``max_feedback`` bounds how many rejected answers are returned to the agent with the host's reason.
    ``max_turns`` bounds each agent run; the host's own tool budget bounds tool calls across all of them.
    """
    if max_feedback < 0:
        raise ValueError("max_feedback must be >= 0")
    host = host or IncidentHost(task)
    first = host_first(host)
    rows = _host_rows(host, first)
    if first.status is not None:  # the host finished the turn itself: no model was called
        return (_result(host, task, model_label, first.status, first.answer, rows, 0, typed_citations,
                        ["no model call: the host's own rule answered or held this request"]),
                ShieldRecord(first.path))

    record = ShieldRecord(first.path, native_called=True, prefetched=first.prefetched)
    agent = build_agent(model, model_settings, checklist=checklist)
    if typed_citations:
        agent = agent.clone(output_type=CitedAnswer)
    session, config, counter = HostSession(host, actor="llm"), RunConfig(tracing_disabled=True), _ModelCallCounter()
    turns: list[Any] = []
    receipt_for_call: dict[str, str] = {}
    agent_input: Any = first.message
    answer, check = "", {"accepted": False, "status": "native_agent_failed", "why": "the agent did not finish"}
    try:
        for round_no in range(max_feedback + 1):
            result = Runner.run_sync(agent, agent_input, context=session, max_turns=max_turns, run_config=config,
                                     hooks=counter)
            record.model_calls, record.model_responses = counter.started, record.model_responses + len(result.raw_responses)
            turns += [_decision(response.output) for response in result.raw_responses]
            for item in result.new_items:
                if isinstance(item, ToolCallOutputItem):
                    raw = item.raw_item
                    call_id = raw.get("call_id") if isinstance(raw, dict) else getattr(raw, "call_id", None)
                    rid = receipt_id_from_output(item.output)
                    if call_id and rid:
                        receipt_for_call[call_id] = rid
            if typed_citations:
                answer, record.cited = result.final_output.text, tuple(result.final_output.cited_receipts)
            else:
                answer = str(result.final_output)
            record.native_answers.append(answer)
            check = exit_check(host, answer, record.cited)
            record.exit_checks.append(check)
            rows += conventional_rows(turns[len(turns) - len(result.raw_responses):], host.receipts,
                                      receipt_for_call=receipt_for_call, controller="LLM (inside the SDK Runner loop)",
                                      loop_name="the SDK Runner")
            last = round_no == max_feedback
            rows.append(_exit_row(check, returned=not check["accepted"] and not last))
            if check["accepted"] or last:
                break
            record.feedback_rounds += 1
            agent_input = result.to_input_list() + [{"role": "user", "content": feedback_message(check, typed=typed_citations)}]
    except Exception as exc:  # a failed run is a named status, never a success
        record.failure = f"{type(exc).__name__}: {' '.join(str(exc).split())[:200]}"
        record.model_calls = counter.started  # the requests made before the failure are not zero
        rows.append(TraceRow("exit", "host (exit check)", "none: the agent did not finish", "no answer is claimed",
                             record.failure, short="host -> native agent failed"))
        return (_result(host, task, model_label, "native_agent_failed",
                        "Unresolved: the native agent did not finish; no answer is claimed.", rows, record.model_calls,
                        typed_citations, ["a failed run is a failure: receipts are kept, nothing is retried"]), record)

    if check["accepted"]:
        status, final = "finished", answer
    else:
        status, final = check["status"], f"Unresolved: the host did not accept the agent's answer ({check['why']})."
    notes = ["the model controls its own loop; the host acts before it, on every tool call and at the exit",
             "the exit check is provenance and claim screening, not a truth check"]
    if record.feedback_rounds:
        notes.append(f"{record.feedback_rounds} rejected answer(s) returned to the agent with the host's reason")
    return _result(host, task, model_label, status, final, rows, record.model_calls, typed_citations, notes), record


def _host_rows(host: IncidentHost, first: HostFirst) -> list[TraceRow]:
    rows = [TraceRow("pre", "host rule (no model)", f"{r.call()}", host_text(r),
                     f"{r.summary()} -> " + ("given to the agent with the task" if first.status is None else "the turn ends here"),
                     short=f"host -> {r.tool}" + ("" if r.executed else f" [{r.status}]"))
            for r in host.receipts if r.proposed_by == PROPOSER]
    if first.status is not None and not rows:
        rows.append(TraceRow("pre", "host rule (no model)", {"host_record": "answer from the verified incident record",
                                                             "host_clarification": "ask which service is meant"}[first.path],
                             "no tool needed", _quote(first.answer), short="host -> " + first.status))
    return rows


def _exit_row(check: dict[str, Any], *, returned: bool) -> TraceRow:
    if check["accepted"]:
        return TraceRow("exit", "host (exit check)", "accept the answer", "receipts and claim screens passed",
                        check["why"], short="host -> accepted")
    then = "returned to the agent with this reason" if returned else "not sent; the run ends unresolved"
    why = check["why"] + (f" ({check['detail']})" if check.get("detail") else "")
    return TraceRow("exit", "host (exit check)", "reject the answer", check["status"], f"{why} -> {then}",
                    short="host -> rejected" + (" (returned)" if returned else ""))


def _result(host: IncidentHost, task: str, model_label: str, status: str, answer: str, rows: list[TraceRow],
            model_calls: int, typed: bool, notes: list[str]) -> RunResult:
    return RunResult(title=TITLE + (" + typed cited answer" if typed else ""), model_label=model_label, task=task,
                     status=status, answer=answer, rows=rows, notes=notes + [host.action_record()],
                     counts={"model_calls": model_calls, "host_tool_requests": len(host.receipts)},
                     writes_executed=len(host.write_ledger))
