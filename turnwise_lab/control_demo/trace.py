"""One per-step trace view for every configuration: who decided, what was proposed, what the host did."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json

NATIVE_MODEL = "native model (SDK Runner)"
POLICY = "turnwise policy"
HOST = "host"


@dataclass
class Step:
    index: int
    owner: str                     # who chose this operation
    operation: str                 # call_tool | call_model | adopt_model_request | decline_model_request | answer | finish | abstain
    proposal: dict | None          # the tool call or model output this step is about
    host_validation: str           # accepted | approval_required | rejected | not_submitted | -
    observation: str               # short summary of what came back
    next_controller: str | None    # who chooses the following operation
    termination: str | None = None


@dataclass
class DemoRun:
    configuration: str
    request: str
    steps: list[Step]
    final: dict                    # kind, text, decided_by, cites
    host_receipts: list[dict]
    model_calls: int
    notes: dict = field(default_factory=dict)

    def as_json(self) -> dict:
        return {"configuration": self.configuration, "request": self.request, "steps": [asdict(s) for s in self.steps],
                "final": self.final, "host_receipts": self.host_receipts, "model_calls": self.model_calls,
                "notes": self.notes}


def _short(value) -> str:
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True, separators=(",", ":"))
    return text if len(text) <= 70 else text[:67] + "..."


def render(run: DemoRun) -> str:
    lines = [f"== {run.configuration}", f"request: {run.request}",
             f"{'#':>2}  {'decided by':<28} {'operation':<22} {'host validation':<17} {'next controller':<28} observation"]
    for s in run.steps:
        lines.append(f"{s.index:>2}  {s.owner:<28} {s.operation:<22} {s.host_validation:<17} "
                     f"{(s.next_controller or '-'):<28} {_short(s.observation)}")
        if s.termination:
            lines.append(f"{'':>4}terminated: {s.termination}")
    lines.append(f"final ({run.final['kind']}, decided by {run.final['decided_by']}): {run.final['text']}")
    lines.append(f"model calls: {run.model_calls}; host receipts: {len(run.host_receipts)}; writes executed: 0")
    return "\n".join(lines)
