# Turnwise Decision Lab — v0.4 release candidate (2026-11-18)

**Route the work, not just the model.**

## Adds

- Closed-world local execution for three real Python operations, two reasoning handoffs, and a denied side-effecting action in a six-turn scenario.
- Readable, reproducible JSON receipts and an interactive local execution exhibit (`demo/local-run.html`).
- A **genuinely fitted** stdlib-only Naive Bayes route classifier trained on 60 authored synthetic examples, then evaluated against 40 disjoint synthetic holdout prompts.
- Strong host-rules baseline and a host-preflight + classifier ablation, with per-case failure traces and null fields for unknown cost/quality.
- Tests of forged plans, action registration, side-effect and permission gates, exception handling, deterministic receipts and synthetic benchmarking.
- An optional, explicitly opted-in OpenAI-compatible generation adapter with a localhost fake-HTTP integration test. No hosted provider run has been performed.
- Comparison/prior-art notes, release boundaries, privacy guardrails and a CI matrix.

## Measured on hand-authored synthetic route labels

| Strategy | Route label matches | Hold misses | Classifier calls |
| --- | ---: | ---: | ---: |
| Strong simple host rules | 38/40 | 0/8 | 0 |
| Tiny trained classifier (without preflight) | 29/40 | 5/8 | 40 |
| Host preflight + classifier with rules fallback | 38/40 | 0/8 | 23 (2 accepted) |

**Not measured:** generative task success, live-model/provider routing, real latency or usage costs, enterprise privacy, independent-user demand, or model confidence calibration. The top-line result is **no demonstrated incremental advantage over simple rules**.

## Release gate

Public source + annotated synthetic results: **published for review in [draft PR #1](https://github.com/dgenio/turnwise-decision-lab/pull/1), not yet merged or released on GitHub Pages**. Product performance claims, enterprise use and ContextWeaver roadmap integration: **not ready**. The existing D1 ContextWeaver adoption gate remains unchanged.
