# Release status

**Last reconciled with `main`: 2026-11-20** (after PRs [#53](https://github.com/dgenio/turnwise-decision-lab/pull/53), [#54](https://github.com/dgenio/turnwise-decision-lab/pull/54), [#56](https://github.com/dgenio/turnwise-decision-lab/pull/56) and [#58](https://github.com/dgenio/turnwise-decision-lab/pull/58)). Public research exhibit. **No production, provider-performance, quality or cost claims.**

Only what is merged into `main` is current. Open PRs, and PRs merged into stacked experimental branches, are not evidence of what `main` does.

## Evidence layers

| Layer | Where | Status |
|---|---|---|
| v0.4 route-label benchmark, execution receipts, planning-contract exhibit | `main` ([PR #1](https://github.com/dgenio/turnwise-decision-lab/pull/1), merged 2026-11-18) | **Historical**, still reproducible. No gain over simple rules |
| v0.5 outcome-scored routing arena and explorer | `main` ([PR #2](https://github.com/dgenio/turnwise-decision-lab/pull/2), merged 2026-11-18) | **Experimentally measured** on authored synthetic data; **no model called**. Mixed and partly negative |
| Hypothesis, parity preflight, architecture gate | `main` (PRs [#4](https://github.com/dgenio/turnwise-decision-lab/pull/4), [#8](https://github.com/dgenio/turnwise-decision-lab/pull/8), [#29](https://github.com/dgenio/turnwise-decision-lab/pull/29), [#30](https://github.com/dgenio/turnwise-decision-lab/pull/30), [#35](https://github.com/dgenio/turnwise-decision-lab/pull/35)) | **Proposed** (docs); parity preflight **implemented and tested** |
| Turnwise Core architecture demo, OpenAI Agents SDK + LlamaIndex | `main` (PRs [#51](https://github.com/dgenio/turnwise-decision-lab/pull/51), [#52](https://github.com/dgenio/turnwise-decision-lab/pull/52), merged 2026-11-19) | **Demonstrated with simulated inference.** Real SDK code paths; simulated model; `--live` **not tested** |
| v0.6 decision-driven loop with local 0.8B inference | [PR #6](https://github.com/dgenio/turnwise-decision-lab/pull/6), open | **Held / inconclusive.** 0/7 investigations for the decision-driven arm; confident silent misses; release gate [#5](https://github.com/dgenio/turnwise-decision-lab/issues/5) |
| P0 host safety + typed per-step control (v0.6 runtime) | [PR #37](https://github.com/dgenio/turnwise-decision-lab/pull/37), draft; [#47](https://github.com/dgenio/turnwise-decision-lab/pull/47) merged **into #37's branch**, not `main` | **Held.** Mechanism tests only |
| v0.7 exit gate, locked synthetic study | [PR #38](https://github.com/dgenio/turnwise-decision-lab/pull/38), draft | **Held.** Reported SHRINK under a weak model; no capable baseline |
| v0.8 request-bound approval authority | [PR #46](https://github.com/dgenio/turnwise-decision-lab/pull/46), draft; [#48](https://github.com/dgenio/turnwise-decision-lab/pull/48) merged **into #46's branch**, not `main` | **Held** |
| Prompt budgets, remote spend reservations | [#31](https://github.com/dgenio/turnwise-decision-lab/pull/31), [#44](https://github.com/dgenio/turnwise-decision-lab/pull/44), open | **Held** |
| Real-model provider readiness | `main` (PRs [#54](https://github.com/dgenio/turnwise-decision-lab/pull/54), [#56](https://github.com/dgenio/turnwise-decision-lab/pull/56), [#58](https://github.com/dgenio/turnwise-decision-lab/pull/58)) | **Offline path verified; real-model smoke INCONCLUSIVE**: owner-dispatched [run 44520205372](https://github.com/dgenio/turnwise-decision-lab/actions/runs/44520205372) returned HTTP 429 for all ten requests ([per-configuration sanitized evidence](../reports/live-smoke-44520205372.md)), no model outputs, usage records or writes; estimated USD 0.32729 reserved, actual billing unknown. Subsequent offline correction stops at the first 429 and exports sanitized evidence. A second one-shot authorization is proposed in [#60](https://github.com/dgenio/turnwise-decision-lab/pull/60), not dispatched. |
| Capable heavy-only baseline, independent held-out data, measured cost and latency | Study gate [#9](https://github.com/dgenio/turnwise-decision-lab/issues/9) | **Not tested** |

Closed without merging (superseded): #7, #10, #26, #27, #32, #33, #36, #45, #50.

## What CI verifies on `main`

`.github/workflows/tests.yml`, on every push and PR:

- **`test`** (Python 3.10, 3.12): the full unittest suite (framework tests skip), then regenerates every committed v0.4/v0.5 report and page and fails on any byte difference.
- **`architecture-examples`** (Python 3.11, 3.12): installs the pinned `openai-agents==0.25.0`, `llama-index-core==0.14.26` and `llama-index-llms-openai==0.9.0`, runs architecture tests with skips counted as failures and network proxied to a dead port, regenerates byte-identical `sample_output/`, and rehearses the four provider paths against a local simulated HTTP provider without any paid inference.

CI proves reproducibility and control-flow properties. It does not test real inference, quality, cost or latency.

`.github/workflows/pages.yml` publishes `demo/` to [GitHub Pages](https://dgenio.github.io/turnwise-decision-lab/) on pushes to `main` that touch `demo/`.

## Not done

- One **attempted** paid provider smoke on `main` hit HTTP 429 on all ten requests; no actual model output was obtained. There is still **no verified real-model behavior**, and no live decision model (Jev) or other router has been benchmarked.
- No held-out sessions written by someone other than the author.
- No measured answer quality, tokens, latency or price.

## Publishing rule

Describe the project as **a reproducible research lab with a simulated-inference architecture demonstration and mixed, partly negative results on authored synthetic data**. Do not quote "74% fewer model calls" without the silent-failure count beside it and the workload caveat. Do not describe the architecture demo as a performance result. Leave ContextWeaver D1 untouched.

## Naming

"Turnwise" is also used by an unrelated arXiv paper on multi-turn LM evaluation and by PyPI packages for conversation evaluation. Use **Turnwise Decision Lab**, never publish a PyPI package named `turnwise`, and consider a distinct name before any wider promotion. This is a search-based conflict flag, not legal trademark clearance.

## History

- 2026-11-18: v0.4 merged ([PR #1](https://github.com/dgenio/turnwise-decision-lab/pull/1)) and deployed to Pages; v0.5 merged ([PR #2](https://github.com/dgenio/turnwise-decision-lab/pull/2)). An earlier version of this page said v0.5 was not yet merged; that was true when written.
- 2026-11-19: Turnwise Core selected as the primary architecture to demonstrate and falsify ([audit](architecture-fit-audit-2026-11-18.md)); architecture demo merged (#51, #52).

- 2026-11-20: Reconciled the first paid smoke (429, no model outputs) and added [PR consolidation/evidence gates](pr-consolidation-gates-2026-11-20.md). No second run or quality claim.
