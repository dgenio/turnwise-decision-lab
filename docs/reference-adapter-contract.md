# Reference adapter contract — implementation checklist

This is a **design contract**, not a claim that an adapter already exists.

```python
from dataclasses import dataclass
from typing import Literal

@dataclass(frozen=True)
class StepAction:
    kind: Literal["direct", "call_tool", "call_light", "call_heavy", "finish", "hold"]
    reason: str
    fact_id: str | None = None  # for direct: host-verifiable, scoped and provenance-backed
    evidence_receipts: tuple[str, ...] = ()
    tool_id: str | None = None
    args: dict | None = None
    context_spec: dict | None = None

class StepPolicy:
    def decide(self, snapshot) -> StepAction: ...

# Existing framework owns the loop, state, tool registry, approvals and tracing.
# Adapter invokes policy at observation boundaries, then delegates to the host.
```

**Acceptance tests before implementation is considered credible**
- `direct` is accepted only for independently host-verified facts with correct referent, provenance, freshness, permission and answer sufficiency; otherwise hand off to a capable model or explicit hold.
- No tool execution without host validation; action requests are executed with explicit approval or held visibly.
- Ambiguous references, missing evidence and causal investigations escalate to a capable model.
- Consecutive decisions in one turn are traced; budget exhaustion terminates observably.
- Errors from a direct tool do not turn into silent success.
- Light-model and decision-service overhead is included in end-to-end accounting.
- The unmodified heavy-only agent runs with the same tools and permissions.
- No access to evaluation labels at runtime; frozen held-out examples are never used for tuning.

**Next:** implement against one framework in a separate PR, with prospective tests. No hosted inference or spending without explicit authorization.
