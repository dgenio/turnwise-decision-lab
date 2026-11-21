> **Note (2026-11-21).** The notes below are the historical v0.4 and v0.5 release notes, accurate for their dates and left unchanged. No release has been cut since; current status is in [docs/release-status.md](docs/release-status.md). Two gates are still open: the v0.6 release gate [#5](https://github.com/dgenio/turnwise-decision-lab/issues/5) is on **HOLD**, and the prospective evidence gate [#9](https://github.com/dgenio/turnwise-decision-lab/issues/9) (capable heavy-only baseline, independent held-out data, measured cost and latency) has **not been run**. No quality, cost or latency benefit has been established. In the v0.5 results table, "Visible failures" mixes two outcomes of the frozen report (`reports/arena.json`): for v0.4 rules the 5 are false holds (`false_hold`), and for both joint rows the 2 are dropped action requests (`action_dropped`), which is how the README labels them.

# Turnwise Decision Lab: v0.5 (2026-11-18)

**Outcome-scored, counterfactual routing experiment. No model was called.**

## Adds

- `turnwise_lab.arena`: 46 synthetic multi-turn incident turns labelled with the facts a correct answer needs, not with routes. Seven designs: always-agent, message-only v0.4 rules, a joint state-aware router, two ablations, v0.4 Naive Bayes and an oracle. All are scored on what they returned.
- `turnwise_lab.world`: real read tools and flows over synthetic data, plus write handlers that record and refuse.
- Pre-registered hypotheses (`docs/preregistration-v0.5.md`) committed before any code. Routers and sessions were frozen before the first run, and the one post-freeze scoring fix is disclosed.
- A compromised-router red team: 18 forged writes, 0 executed, with a positive control.
- `demo/index.html`: an interactive explorer with every turn × design. Each cell shows what ran, the context packet (included, dropped, not selected), the receipt vs the outcome check, and per-path counterfactuals. A failure-cost slider sits underneath.
- CI byte-identity check on all committed evidence.

## Fixes

- `LocalHarness` discarded the plan's context selection on `llm` handoffs and re-packed with a fixed mode. It now honours `plan.context_ids`, restricted to host-supplied sources within budget.

## Results (authored synthetic data; see `reports/arena.md`)

| Design | Correct* | Model calls | Silent wrong | Visible failures |
|---|---:|---:|---:|---:|
| Always-agent | 46/46 | 78 | 0 | 0 |
| v0.4 rules (message-only) | 41/46 | 58 | 0 | 5 |
| Joint router (state + route-aware context) | 38/46 | 20 | 6 | 2 |
| Joint without state | 43/46 | 43 | 1 | 2 |
| Oracle | 46/46 | 9 | 0 | 0 |

\*Correct is an upper bound for any design that calls a model.

H1, H2, H5 and H6 were supported; **H3 (route-aware context) and H4 (every saving router fails silently) were falsified.**

---

# Turnwise Decision Lab: v0.4 (2026-11-18)

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

Public source + annotated synthetic results: reviewed in [PR #1](https://github.com/dgenio/turnwise-decision-lab/pull/1), merged and deployed to GitHub Pages on 2026-11-18. Product performance claims, enterprise use and ContextWeaver roadmap integration: **not ready**. The existing D1 ContextWeaver adoption gate remains unchanged.
