# Release status: v0.5 (2026-11-18)

**Public research exhibit. No production, provider-performance or cost claims.**

## Ready

- Outcome-scored experiment (`turnwise_lab.arena`): 46 synthetic turns, 7 designs, real handlers through `LocalHarness`, oracle upper bound, compromised-router red team. Hypotheses pre-registered and verdicts computed by code (`reports/arena.md`).
- Interactive explorer generated from the report (`demo/index.html`, published by the Pages workflow on merge to `main`).
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
