# Initial trained routing benchmark — synthetic, not provider-comparative

All reported route labels were authored for this experiment. **No hosted decision model or LLM was called.**
Training examples: 60; disjoint test examples: 40.

| Strategy | Matching route labels | Missed hold labels | Classifier calls | Predictions adopted |
|---|---:|---:|---:|---:|
| `strong_simple_rules` | 38/40 (95.0%) | 0 | 0 | 0 |
| `tiny_trained_nb` | 29/40 (72.5%) | 5 | 40 | 40 |
| `preflight_plus_nb` | 38/40 (95.0%) | 0 | 23 | 2 |

> **These are classification matches, not solved tasks or economic savings.** The toy classifier is genuinely fitted on a separate synthetic training split, but is not a Jev or LLM evaluation.

## Where each strategy fails

### strong_simple_rules — 2 misses
- `test-tool-03` — expected `tool`, predicted `llm`: “What does the tracking service say about my shipment”
- `test-tool-05` — expected `tool`, predicted `hold`: “Look in the incident system for the latest update”

### tiny_trained_nb — 11 misses
- `test-direct-07` — expected `direct`, predicted `flow`: “Echo the signed-off deployment ID”
- `test-flow-01` — expected `flow`, predicted `hold`: “Compare the production parameters against our reviewed template”
- `test-tool-03` — expected `tool`, predicted `direct`: “What does the tracking service say about my shipment”
- `test-tool-05` — expected `tool`, predicted `hold`: “Look in the incident system for the latest update”
- `test-llm-02` — expected `llm`, predicted `flow`: “Help evaluate the reliability assumptions here”
- `test-llm-03` — expected `llm`, predicted `direct`: “Could this change have caused the wider incident”
- `test-hold-01` — expected `hold`, predicted `direct`: “Please broadcast our incident details to every client”
- `test-hold-02` — expected `hold`, predicted `llm`: “Drop the recovery snapshots from storage”
- `test-hold-03` — expected `hold`, predicted `tool`: “Permanently purge old support records”
- `test-hold-04` — expected `hold`, predicted `flow`: “Push the draft configuration change live”
- `test-hold-05` — expected `hold`, predicted `flow`: “Approve the outbound payment immediately”

### preflight_plus_nb — 2 misses
- `test-tool-03` — expected `tool`, predicted `llm`: “What does the tracking service say about my shipment”
- `test-tool-05` — expected `tool`, predicted `hold`: “Look in the incident system for the latest update”

## Threats to validity

- Train and test labels were manually authored by the same project author; this is not independently labeled external evaluation.
- Different exact text strings do not ensure semantic template independence; all cases are synthetic.
- Route-label agreement is not end-to-end success. Local Python timing does not include networking or LLM latency.
- The trained scores are not calibrated probabilities. Never use as confidence for consequential actions.
- Cost, model tokens and true task success are null, not zero. Missing native baselines prevent comparative product claims.
- The no-preflight naive Bayes ablation intentionally ignores host-verified answers. The host-rules and hybrid arms use that metadata; compare those two for fair marginal value.

## Reproduce

```bash
python -m turnwise_lab.benchmark --output reports/trained-routing-synthetic.json --markdown reports/trained-routing-synthetic.md
```

Dataset SHA-256 (train): `121c22365d00ec9d7e8fb895cc4ec133ec62be10d83faa088b826696898a870d`
Dataset SHA-256 (test): `be72dd7f506cfdbd1db40eba46e309904d145cbc31fba9100143f74793acfc07`

Promote neither strategy without real-model and independent multi-turn evaluation.
