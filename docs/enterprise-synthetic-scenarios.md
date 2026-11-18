# Proposed enterprise evaluation cases (fully synthetic)

These are architectural hypotheses inspired by generic enterprise AI/operations use cases. They are **not** a representation of any specific employer's architecture, data, governance policies or production measurements. No corporate data should be copied to a public repository.

| Family | User turn / trigger | Strong baseline | Hypothesized value of per-turn planning | Protected boundary / key risk |
|---|---|---|---|---|
| Rich employee assistant | "Find the relevant policy and show me the ticket status" | Native tool search + standard LLM | Select authorized read tool, current ticket context, and slim schema; leave irrelevant conversation out | Enterprise data residency, access scope, no unauthorized task mutation |
| Incident/support triage | "Investigate an inconsistency in network inventory" | Rules + query tool + reasoning agent | Deterministic anomaly checks before model; escalate only unexplained exceptions | No customer identifiers in external classifier, evidence grounding, owner handoff |
| Voice operations | "Summarize what changed in this interaction" | Small/fast model always | Skip non-generative checks; latency-aware tier based on task + phase | Critical p95 latency, transcript privacy, false negatives |
| GenAI platform / evaluation | "How should this turn be executed?" | Existing gateway router | Separate *need for tool, model complexity, context surface* and measure their interactions | Routing drift, policy compliance and extra hop cost |
| Known operational flow | "Validate capability schema before deploying" | Plain Python / CI | Run approved deterministic flow without intermediate model reasoning | Review required before code-changing or deploying |

## How to test fairly

1. Collect anonymous, approved **task patterns**, not enterprise transcripts. Write fresh synthetic fixtures whose labels are validated by domain owners.
2. Pre-register failure costs (wrong answer, tool exclusion, unsafe write, privacy exposure, latency blow-up) before choosing probability thresholds.
3. Use a strong deterministic baseline and current native search/router baseline; do not compare against a naïve always-large LLM only.
4. Track the separate contribution of `need_tool`, `model_tier`, and `context_pack`. These are distinct ablations; improvement in one cannot be credited to another.
5. Evaluate counterfactual routes in shadow first, then use a small guarded canary if supported by evidence.
6. Validate on multi-turn transitions and after upstream schema/policy/model updates. Pin versions; recalibrate and roll back when error costs regress.

## Potential production topology

```text
in-house assistant/agent host
  -> rule-only bypass / hard residency policy
  -> local or approved decision model over bounded turn state
  -> route plan: no model | existing deterministic flow | tool+LLM | LLM only
  -> authorized context retrieval / context compilation
  -> existing model gateway / tier selection
  -> policy-enforced tool/flow execution
  -> structured trace + quality evaluation
```

The decision model is **not** the enterprise security boundary. The only legitimate place to perform authorized tool operations is the existing host's enforcement layer. The model can say `flow`; that is not authorization to run it.
