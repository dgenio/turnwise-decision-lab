# Synthetic planning-contract replay — 2026-11-18

**Result: HOLD / no incremental benefit demonstrated on this corpus.**

Executed offline: `python -m turnwise_lab.evaluate --output reports/synthetic-contract-replay.json`.

| Arm | Authored route matches | Deep-model paths *proposed* | Classifier calls made |
|---|---:|---:|---:|
| Always-deep sanity baseline | 4/8 | 8/8 | 0 |
| Simple host policy | 8/8 | 4/8 | 0 |
| Fixture-fed planner | 8/8 | 4/8 | 7 |

The fixture-fed planner's judgments and expected labels were written by the **same author** and keyed on the exact turn string. Its 8/8 is a test of code contracts, *not predictive validity*. Similarly, zero difference between the simple rules and the fixture-fed planner does not prove a real Jev model would be useless: these eight cases are simple and undiagnostic. The additional seven calls in the fixture path are **local Python calls**, not measured API calls or latency charges.

What this replay supports:
- Verified direct answers can bypass a classifier altogether.
- A read-only flow/tool shortlist, explicit write-approval holds and deep escalation can be expressed deterministically.
- Proposed planning paths can be compared on exactly the same authored task descriptions.

What it cannot support:
- Saved dollars/tokens/latency or model-call avoidance in production.
- Calibrated decision-model probabilities, real tool outcomes, context completeness, privacy guarantees.
- Outperforming LiteLLM Auto Router, vLLM Semantic Router, native deferred tools or a capable model.

**Consequence:** Do not open a new routing feature roadmap or a ContextWeaver D2 implementation PR based on these fixtures. Next step is an externally sourced/independently labeled problem set and a fair real-baseline comparison, if an adopter cares.
