# Reference adapter contract — implementation checklist

This is a **design contract**, not a claim that an adapter already exists.

```python
from dataclasses import dataclass
from typing import Any, Literal, Mapping, Protocol

ActionKind = Literal["direct", "call_tool", "call_light", "call_heavy", "finish", "hold"]

@dataclass(frozen=True)
class StepAction:
    """Untrusted policy proposal, NOT execution authority."""

    kind: ActionKind
    reason: str
    fact_id: str | None = None
    evidence_receipts: tuple[str, ...] = ()
    tool_id: str | None = None
    proposed_args: dict[str, Any] | None = None
    context_spec: dict[str, Any] | None = None
    answer: str | None = None
    approval_request: str | None = None

    def __post_init__(self) -> None:
        # Python type hints and frozen dataclasses do not validate incoming data.
        if self.kind not in {"direct", "call_tool", "call_light", "call_heavy", "finish", "hold"}:
            raise ValueError("unknown action kind")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("action reason is required")
        if self.kind == "direct":
            if not isinstance(self.fact_id, str) or not self.fact_id or not self.evidence_receipts:
                raise ValueError("direct requires a fact ID and evidence receipts")
        elif self.fact_id is not None:
            raise ValueError("fact_id is only valid for direct")
        if self.kind == "call_tool":
            if not isinstance(self.tool_id, str) or not self.tool_id or self.proposed_args is None:
                raise ValueError("call_tool requires a tool ID and proposed arguments")
        elif self.tool_id is not None or self.proposed_args is not None:
            raise ValueError("tool fields are only valid for call_tool")
        if self.kind == "finish":
            if not isinstance(self.answer, str) or not self.answer.strip():
                raise ValueError("finish requires a nonempty answer")
        elif self.answer is not None:
            raise ValueError("answer is only valid for finish")
        if self.context_spec is not None and self.kind not in {"call_light", "call_heavy"}:
            raise ValueError("context_spec is only valid for model calls")
        if self.approval_request is not None and self.kind != "hold":
            raise ValueError("approval_request is only valid for hold")

class StepPolicy(Protocol):
    def decide(self, snapshot: Mapping[str, Any]) -> StepAction: ...

# LangGraph/LangChain owns the graph, state and model/tool invocation.
# A separate host gate checks each proposed action against identity,
# permissions, registered capabilities, evidence, approvals and budgets.
```

**Authority boundary:** this dataclass only checks **structural shape**; it cannot validate receipt provenance, fact freshness, correct referent, permission, intent, approved side effects or answer truth. `proposed_args` are not `validated_args`; the host must validate and defensively copy them before execution. `frozen=True` does not make nested dictionaries immutable. For `HOLD`, an approval request may be absent for clarification/refusal, but any side-effect intent must remain recorded and visible. Do not treat this design snippet as an implemented adapter.

**LangGraph composition:** a policy node returns a proposal. Route through an explicit validation node before any direct answer, tool call, terminal `finish` or approval path; model nodes append their observations and return to policy. Prefer conditional edges for pure routing, and `Command(update=..., goto=...)` when updating state and choosing the destination together. Never combine dynamic routing and a static outgoing edge from the same node. For approval, use a checkpointer and an interrupt/resume path with idempotent effects and a fresh authorization check. See [the upstream API fit review](framework-integration-roadmap.md#initial-upstream-api-fit-python-checked-2026-11-18).

**Acceptance tests before implementation is considered credible**
- `direct` is accepted only for independently host-verified facts with correct referent, provenance, freshness, permission and answer sufficiency; otherwise hand off to a capable model or explicit hold.
- Invalid action shapes (e.g. `call_tool` without args, `direct` without receipts, `finish` without an answer, or fields from the wrong action variant) fail closed.
- No tool execution without host validation; action requests are executed with explicit approval or held visibly.
- Ambiguous references, missing evidence and causal investigations escalate to a capable model.
- Consecutive decisions in one turn are traced; budget exhaustion terminates observably.
- Interrupt/resume with an action intent never duplicates side effects, and approval is rechecked after resume.
- Errors from a direct tool do not turn into silent success.
- Light-model and decision-service overhead is included in end-to-end accounting.
- The unmodified heavy-only agent runs with the same tools and permissions.
- No access to evaluation labels at runtime; frozen held-out examples are never used for tuning.

**Next:** implement against one framework in a separate PR, with prospective tests. No hosted inference or spending without explicit authorization.
