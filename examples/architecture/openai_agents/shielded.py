"""S -- The same agent, shielded by the host, on the OpenAI Agents SDK. NOT Turnwise Core.

Same task, same ``build_agent(...)`` (instructions, tools, model), same host. Unlike arm B, **the model keeps
control of the loop**: this is ``Agent`` + ``Runner.run_sync``, as in arm A. What the host adds is at the
boundaries (see ``shielded_native.py``): rules before the agent, ``IncidentHost.execute`` on every tool call,
and a gate on the finished answer that can send it back with the reason, up to a bound.

By default the agent's *final output type* is ``CitedAnswer`` (``Agent.clone(output_type=...)``; tools, loop and
instructions unchanged), so the exit gate can check the citations the way ``FINISH`` checks a model's. With
``typed_citations=False`` the agent answers in plain text and the gate can only ask whether the required
evidence exists at all, which is weaker.

Only public SDK APIs are used: ``Agent.clone``, ``output_type``, ``Runner.run_sync``, ``RunResult.to_input_list``.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from agents import ModelSettings, RunConfig, Runner, ToolCallOutputItem

from ..cited_answer import CitedAnswer
from ..incident_env import HostSession, IncidentHost
from ..shielded_native import (ARM, EXIT_GATE, HOST_RULE, ExitVerdict, ShieldReport, counts, exit_check, first_message,
                               host_rules, prefetch, return_message, withheld_answer)
from ..trace import RunResult, TraceRow, conventional_rows, host_text, receipt_id_from_output, status_tag
from .conventional import _decision, build_agent

NATIVE = "LLM (inside the SDK Runner loop)"
_RULE_TEXT = {"write": "the user asked for a write: only the host may dispose of it",
              "record": "a host-verified record answers this question",
              "clarification": "the question is service-scoped and names no service"}
_RULE_PATH = {"write": "host_write_rule", "record": "host_record", "clarification": "host_clarification"}
_RULE_HOST = {"write": "validated; the write is HELD for human approval or refused, never executed",
              "record": "value read from the host's verified record (no model call)",
              "clarification": "run stops and asks the user (no model call)"}


def run_shielded(task: str, model: Any, *, model_label: str, typed_citations: bool = True, checklist: bool = False,
                 max_exit_returns: int = 1, max_turns: int = 10, model_settings: ModelSettings | None = None,
                 host: IncidentHost | None = None) -> tuple[RunResult, ShieldReport]:
    """Run one task under arm S. ``host`` may be passed in so a caller can read its receipts whatever happens."""
    host = host or IncidentHost(task)
    title = f"{ARM} -- OpenAI Agents SDK (host rules + Agent + Runner.run_sync + host exit gate)"
    rows: list[TraceRow] = []

    def done(report: ShieldReport, answer: str, notes: list[str]) -> tuple[RunResult, ShieldReport]:
        return RunResult(title, model_label, task, report.status, answer, rows, notes + [host.action_record()],
                         counts(report, host), writes_executed=len(host.write_ledger)), report

    settled = host_rules(host)
    if settled is not None:
        rows.append(TraceRow("H1", HOST_RULE, _RULE_TEXT[settled.rule],
                             "; ".join(host_text(r) for r in settled.receipts) or _RULE_HOST[settled.rule], "run ends",
                             short=f"host rule -> {settled.rule} [{settled.status}]"))
        return done(ShieldReport(settled.status, _RULE_PATH[settled.rule]), settled.answer,
                    ["settled by a host rule before any model call"])

    read = prefetch(host)
    for i, r in enumerate(read, start=1):
        rows.append(TraceRow(f"H{i}", HOST_RULE, f"read {r.call()}: evidence the host's own contract requires",
                             host_text(r), f"{r.summary()} -> given to the agent with the task",
                             short=f"host rule -> read {r.tool}" + status_tag(r)))
    report = ShieldReport("native_agent_failed", "native_agent", native_called=True,
                          prefetched=tuple(r.id for r in read))
    agent = build_agent(model, model_settings, checklist=checklist)
    if typed_citations:
        agent = agent.clone(output_type=CitedAnswer)  # tools, loop and instructions are unchanged
    notes = ["the agent chose its own operations; the host checked every tool call and the finished answer",
             "typed final answer: the exit gate checked the citations the agent declared" if typed_citations else
             "plain final answer: the agent declares no citations, so the exit gate's provenance check is weak"]
    conversation: Any = first_message(host, read)
    turn_offset = 0
    verdict: ExitVerdict | None = None
    for attempt in range(max_exit_returns + 1):
        before = len(host.receipts)
        try:
            result = Runner.run_sync(agent, conversation, context=HostSession(host, actor="llm"),
                                     max_turns=max_turns, run_config=RunConfig(tracing_disabled=True))
        except Exception as exc:  # a failed run is a named status, never an answer; no hidden retry
            report.failure = f"{type(exc).__name__}: {' '.join(str(exc).split())[:200]}"
            for r in host.receipts[before:]:  # tool calls the agent made before it failed stay visible
                rows.append(TraceRow(f"{turn_offset + 1}+", NATIVE, f"tool call {r.call()}", host_text(r), r.summary(),
                                     short=f"LLM -> tool {r.tool}" + status_tag(r)))
            rows.append(TraceRow("X", NATIVE, "the agent run failed", "no answer to check",
                                 f"FAILED: {report.failure}", short="LLM -> run failed"))
            return done(report, "Unresolved: the native agent did not finish; no answer is claimed.", notes)
        report.model_calls += len(result.raw_responses)
        rows.extend(_native_rows(result, host, turn_offset))
        turn_offset += len(result.raw_responses)
        if typed_citations:
            out: CitedAnswer = result.final_output
            report.native_answer, report.cited = out.text, tuple(out.cited_receipts)
        else:
            report.native_answer, report.cited = str(result.final_output), None
        verdict = exit_check(host, report.native_answer, report.cited)
        report.verdicts.append(verdict)
        returning = not verdict.accepted and attempt < max_exit_returns
        rows.append(TraceRow(
            f"G{attempt + 1}", EXIT_GATE,
            "check the finished answer against host receipts"
            + (f"; declared citations [{', '.join(report.cited)}]" if report.cited is not None else ""),
            ("accepted" if verdict.accepted else "REJECTED") + f": {verdict.why}"
            + (f" ({verdict.detail})" if verdict.detail else "")
            + (". Causal correctness is NOT verified." if verdict.accepted else ""),
            "run ends" if verdict.accepted else
            "returned to the agent with the reason" if returning else "answer withheld; run ends",
            short="exit gate -> " + ("accepted" if verdict.accepted else
                                     "rejected, back to the agent" if returning else f"rejected [{verdict.status}]")))
        if not returning:
            break
        report.exit_returns += 1
        conversation = result.to_input_list() + [{"role": "user", "content": return_message(verdict)}]
    report.status = verdict.status
    return done(report, report.native_answer if verdict.accepted else withheld_answer(verdict), notes)


def _native_rows(result: Any, host: IncidentHost, turn_offset: int) -> list[TraceRow]:
    """The agent's own decisions in this attempt, numbered after the turns of earlier attempts."""
    turns = [_decision(response.output) for response in result.raw_responses]
    receipt_for_call = {}
    for item in result.new_items:
        if isinstance(item, ToolCallOutputItem):
            raw = item.raw_item
            call_id = raw.get("call_id") if isinstance(raw, dict) else getattr(raw, "call_id", None)
            rid = receipt_id_from_output(item.output)
            if call_id and rid:
                receipt_for_call[call_id] = rid
    rows = conventional_rows(turns, host.receipts, receipt_for_call=receipt_for_call, controller=NATIVE,
                             loop_name="the SDK Runner")
    out = []
    for row in rows:
        row = replace(row, step=str(turn_offset + int(row.step)))
        if row.decision.startswith("final answer"):  # under arm S the answer is not the end: the gate sees it next
            row = replace(row, decision="final answer (no tool call) -> goes to the host exit gate",
                          host="checked by the host exit gate (next row)", short="LLM -> final answer, to the exit gate")
        out.append(row)
    return out
