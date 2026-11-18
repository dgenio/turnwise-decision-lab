# Release status: v0.7 (2026-11-18)

v0.7 adds the exit gate, evidence contracts, the contract planner and a pre-registered locked-set study on the pinned local models. Results: `reports/v07/summary.md`. Mechanism: `docs/v07-exit-gate.md`. Reasoning: `docs/v07-research-assessment.md`. What review found: `docs/v07-self-review.md`. **Status: Level B evidence only (0.8B local models). Verdict for the mechanism: SHRINK.** Not done: a capable heavy model, hosted decision services, a human grader, a second domain. Next gate: `docs/v07-level-c-protocol.md` (needs owner decisions on model, budget, margin and graders).

v0.7 is stacked on v0.6 and changes nothing v0.6 froze.

## v0.6 status (unchanged)

v0.6 adds the decision-driven agent loop, real local inference and the heavy-only agent comparison. Its status is in `reports/v06/summary.md`. Not done for v0.6: hosted decision services (no credentials, no approved spend), a heavy model larger than 0.8B, and held-out tasks from a human author. **Status: exploratory and inconclusive; HOLD on any scientific claim** (owner review of PR #6, issue #5). Post-hoc audit: `reports/v06/audit.md`. Next gate: `docs/v07-gate-proposal.md`. Under the quality-constrained efficiency protocol (PR #4), the v0.6 result is inconclusive: no non-inferiority margin has been agreed, and n = 30 cannot resolve any margin narrower than about 16 pp.

## v0.5 status (unchanged)

**Public research exhibit. No production, provider-performance or cost claims.**

## Ready

- Outcome-scored experiment (`turnwise_lab.arena`): 46 synthetic turns, 7 designs, real handlers through `LocalHarness`, oracle upper bound, compromised-router red team. Hypotheses pre-registered and verdicts computed by code (`reports/arena.md`).
- Interactive explorer generated from the report (now `demo/v05-explorer.html`; `demo/index.html` is the v0.6 trace viewer).
- CI regenerates every committed report and page and fails on any byte difference. The suite runs on Python 3.10 and 3.12.
- `LocalHarness` now honours a plan's context selection (host-supplied sources only, within budget) instead of silently re-packing.
- v0.4 artefacts (route-label benchmark, execution receipts, planning-contract exhibit) are kept and still reproducible.

## Not done

- No model, decision model (Jev) or live router (LiteLLM, vLLM Semantic Router, provider tool search) has been run.
- No held-out sessions written by someone other than the author.
- No measured answer quality, tokens, latency or price.

## History

- v0.4 was merged as [PR #1](https://github.com/dgenio/turnwise-decision-lab/pull/1) on 2026-11-18, and its Pages deployment succeeded the same day.
- v0.5 is proposed in a follow-up pull request and is not merged until the maintainer approves.

## Publishing rule

Describe v0.5 as **a reproducible, outcome-scored testbed with mixed and partly negative results on authored synthetic data**. Do not quote "74% fewer model calls" without the silent-failure count beside it and the workload caveat. Leave ContextWeaver D1 untouched.

## Naming

"Turnwise" is also used by an unrelated arXiv paper on multi-turn LM evaluation and by PyPI packages for conversation evaluation. Use **Turnwise Decision Lab**, never publish a PyPI package named `turnwise`, and consider a distinct name before any wider promotion. This is a search-based conflict flag, not legal trademark clearance.
