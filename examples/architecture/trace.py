"""Trace rows that name the controller of every operation, and their rendering.

Both architectures produce the same row shape, so the only thing that changes
between two printed traces is what actually changed: who decided each step,
and where each observation went next.
"""
from __future__ import annotations

import json
import textwrap
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

from .incident_env import Receipt


@dataclass(frozen=True)
class TraceRow:
    step: str
    controller: str  # who chose this operation
    decision: str  # what was chosen
    host: str  # what the host did with it
    observation: str  # what came back, and where it went
    why: str = ""  # the controller's stated reason, if it has one
    short: str = ""  # one-line label for the side-by-side view


@dataclass
class RunResult:
    title: str
    model_label: str
    task: str
    status: str
    answer: str
    rows: list[TraceRow]
    notes: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    writes_executed: int = 0


@dataclass(frozen=True)
class NativeTurnItem:
    """One item a model emitted in a conventional framework loop."""

    kind: str  # "tool_call" | "answer" | "text" (text the model sent alongside tool calls)
    tool: str = ""
    arguments: str = ""
    text: str = ""
    call_id: str = ""  # the framework's id for this tool call


def receipt_id_from_output(output: object) -> str | None:
    """The host receipt id inside a tool result the framework returned (our tools return receipt JSON)."""
    try:
        data = json.loads(output) if isinstance(output, str) else None
    except ValueError:
        return None
    return data.get("receipt") if isinstance(data, dict) and isinstance(data.get("receipt"), str) else None


def conventional_rows(turns: Sequence[Sequence[NativeTurnItem]], receipts: Sequence[Receipt], *,
                      receipt_for_call: Mapping[str, str], controller: str, loop_name: str) -> list[TraceRow]:
    """Rows for a native agent loop: each model response is one LLM decision.

    Tool calls are paired with host receipts by the framework's call id, never by order: frameworks may
    run several tool calls of one response concurrently, in any order.
    """
    rows: list[TraceRow] = []
    by_id = {r.id: r for r in receipts}
    for i, items in enumerate(turns, start=1):
        for item in items:
            if item.kind == "text":
                rows.append(TraceRow(str(i), controller, "text alongside the tool call(s) (not a decision)",
                                     "not consulted", _quote(item.text), short="LLM -> text beside tool calls"))
            elif item.kind == "tool_call":
                receipt = by_id.get(receipt_for_call.get(item.call_id, ""))
                host = ("no host receipt: the framework did not invoke the tool" if receipt is None
                        else _host_text(receipt))
                obs = "" if receipt is None else receipt.summary()
                rows.append(TraceRow(str(i), controller, f"tool call {item.tool}({_args(item.arguments)})", host,
                                     f"{obs} -> appended to the conversation; the LLM decides again".lstrip(" ->"),
                                     short=f"LLM -> tool {item.tool}" + status_tag(receipt)))
            else:
                rows.append(TraceRow(str(i), controller, f"final answer (no tool call) -> {loop_name} ends the run",
                                     "not consulted: the run ends when the model stops calling tools",
                                     _quote(item.text), short="LLM -> final answer, run ends"))
    return rows


def _args(arguments: str) -> str:
    try:
        data = json.loads(arguments) if arguments else {}
    except ValueError:
        return arguments
    return ", ".join(f"{k}={v}" for k, v in data.items()) if isinstance(data, dict) else arguments


def status_tag(receipt: Receipt | None) -> str:
    if receipt is None:
        return " [not run]"
    return "" if receipt.executed else " [" + {"held_for_approval": "held"}.get(receipt.status, receipt.status) + "]"


def host_text(receipt: Receipt) -> str:
    return _host_text(receipt)


def _host_text(r: Receipt) -> str:
    return {"executed": f"validated and executed -> {r.id}",
            "held_for_approval": f"validated; HELD for human approval (not executed) -> {r.id}",
            "rejected": f"REJECTED -> {r.id}: {r.reason}",
            "error": f"executed with ERROR -> {r.id}: {r.reason}"}.get(r.status, r.status)


def _quote(text: str, limit: int = 160) -> str:
    text = " ".join(text.split())
    return '"' + (text if len(text) <= limit else text[: limit - 3] + "...") + '"'


def render(result: RunResult, *, width: int = 100) -> str:
    out = [f"=== {result.title} ===",
           f"model : {result.model_label}",
           f"task  : {result.task}", ""]
    label_w = 12
    for row in result.rows:
        out.append(f"STEP {row.step}")
        fields = [("controller", row.controller), ("decision", row.decision)]
        if row.why:
            fields.append(("why", row.why))
        fields += [("host", row.host), ("observation", row.observation)]
        for name, value in fields:
            if not value:
                continue
            wrapped = textwrap.wrap(value, width=width - label_w - 4) or [""]
            out.append(f"  {name:<{label_w}}: {wrapped[0]}")
            out.extend(f"  {'':<{label_w}}  {line}" for line in wrapped[1:])
    out += ["", f"RESULT  {result.status}"]
    for line in textwrap.wrap(result.answer, width=width - 8):
        out.append(f"        {line}")
    for note in result.notes:
        wrapped = textwrap.wrap(note, width=width - 10)
        out.append(f"  note: {wrapped[0]}")
        out.extend(f"        {line}" for line in wrapped[1:])
    if result.counts:
        out.append("  counts: " + ", ".join(f"{k}={v}" for k, v in result.counts.items())
                   + "  (operation counts in this run only; not a cost, latency or quality measurement)")
    out.append(f"  writes executed: {result.writes_executed}")
    return "\n".join(out)


def render_side_by_side(left: RunResult, right: RunResult, *, col: int = 58) -> str:
    """Who chose each operation, in order, for two runs of the same task."""
    a = [f"{r.step:>4}  {r.short}" for r in left.rows]
    b = [f"{r.step:>4}  {r.short}" for r in right.rows]
    out = ["=== Side by side: who chose each operation ===",
           f"{'A: ' + left.title.split(' -- ')[0]:<{col}} | B: {right.title.split(' -- ')[0]}",
           f"{'-' * col}-+-{'-' * col}"]
    for i in range(max(len(a), len(b))):
        x = a[i] if i < len(a) else ""
        y = b[i] if i < len(b) else ""
        out.append(f"{x[:col]:<{col}} | {y[:col]}")
    out.append(f"{'  result: ' + left.status:<{col}} |   result: {right.status}")
    return "\n".join(out)


def summarize_controllers(rows: Iterable[TraceRow]) -> dict[str, int]:
    """How many operations each controller chose (policy / LLM / native agent)."""
    counts: dict[str, int] = {}
    for row in rows:
        key = row.controller.split(" (")[0]
        counts[key] = counts.get(key, 0) + 1
    return counts
