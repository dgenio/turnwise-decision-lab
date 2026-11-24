# Stage 0 results, amendment 1: τ²-bench, a coding set and the tier ceiling

**Status: Experimentally measured (re-priced public trajectories, no inference by this repo).** Run on the evaluation split on 2026-11-21 under [PROTOCOL-AMENDMENT-1.md](PROTOCOL-AMENDMENT-1.md). That amendment was committed (`c5e0e0b`) before the script (`e11e266`), and both were pushed before this run. The τ-bench analysis and its verdict are in [RESULTS.md](RESULTS.md), unchanged. Issue: [#86](https://github.com/dgenio/turnwise-decision-lab/issues/86). Every token figure is an estimate (`ceil(characters / 4)`). Every share is a hindsight ceiling on trajectories that already succeeded, not a saving anyone achieved. Figures: [`results-amendment-1.json`](results-amendment-1.json).

## Verdict

**SHRINK**, by the amendment's combined rule. In every domain, coding included, the batching ceiling is at least as large as the strict oracle D0. D0 removed 0.0% everywhere except τ-bench retail (0.3%).

**SHRINK here means that neither mechanism shows headroom**, as in the τ-bench run, not that native batching captures a large saving. No D0 rule was mined in any added domain: no position key predicted a read tool in at least 90% of training-split turns with at least 20 occurrences. So D0 is 0 by construction. The batching ceiling is 1.4% to 3.2% on τ²-bench and 1.8% on coding.

The paid comparison is **not** supported. PROCEED needed D0 at 15% or more in some non-coding domain.

How the rule was walked, on P1 point estimates of the primary analysis sets:

1. **INCONCLUSIVE?** No: both added datasets were usable as specified.
2. **STOP?** No. STOP needs D1 below 15% in every non-coding domain *and* on coding. Coding (6.3%), τ²-bench airline (11.6%) and τ-bench airline (14.9%) are below. Telecom (14.8%) is below by its point estimate, but its interval (13.7% to 15.9%) contains 15%. Retail is above on both benchmarks: τ-bench 26.3%, τ²-bench 16.9% (interval 15.8% to 18.0%).
3. **SHRINK?** Yes: batching ≥ D0 in all six domains.

**How STOP was read.** #86 says STOP if D1 is below 15% "on both a coding and a non-coding set". `PROTOCOL.md` and this amendment read that as every non-coding domain, before either run. Under the narrower reading, where any one non-coding set plus the coding set is enough, STOP would fire: τ²-bench airline (11.6%) and coding (6.3%). Under either reading, the paid comparison is not supported.

## Datasets attempted

| Candidate in #86 | Used | Why |
|---|---|---|
| τ-bench historical trajectories | yes | The first pass (#97); values read from the committed `results.json` |
| τ²-bench released trajectories | **yes** | 9 default-mode files: 3 agent models × airline, retail, telecom. MIT |
| TwinRouterBench static set | **yes** | The SWE-bench slice as the coding set (40 complete instances, none excluded); every slice for the tier ceiling. Apache-2.0 |
| mini-SWE-agent trajectories | no | Public S3, but no licence stated, no per-call usage, untyped bash actions. Coding is covered by TwinRouterBench's SWE slice, built from a mini-SWE-agent-based pipeline |
| HAL traces | no | No licence tag and no dataset card, so terms of use cannot be established |

## Results: turn-removal oracles (primary analysis set, P1)

Eval split, reward 1. Share of estimated cache-aware cost removed, with a 95% cluster-bootstrap interval over tasks. In brackets: share of model turns deleted.

| Domain | Trajectories (tasks) | D2 ceiling | D1 liberal | D0 strict | Batching null |
|---|---|---|---|---|---|
| τ²-bench airline | 182 (21) | 15.5% (13.3 to 17.7) [42%] | 11.6% (9.5 to 13.7) [34%] | 0.0% | 1.4% (0.8 to 2.1) |
| τ²-bench retail | 566 (60) | 17.7% (16.8 to 18.8) [50%] | 16.9% (15.8 to 18.0) [48%] | 0.0% | 2.1% (1.6 to 2.7) |
| τ²-bench telecom | 264 (39) | 16.5% (14.9 to 17.9) [43%] | 14.8% (13.7 to 15.9) [41%] | 0.0% | 3.2% (2.6 to 3.9) |
| **Coding** (TwinRouterBench SWE-bench slice) | 18 (18) | 45.5% (42.8 to 48.6) [88%] | 6.3% (4.0 to 8.8) [23%] | 0.0% | 1.8% (0.8 to 3.2) |
| τ-bench airline (#97) | 141 (18) | 29.8% | 14.9% | 0.0% | 1.5% |
| τ-bench retail (#97) | 415 (51) | 28.9% | 26.3% | 0.3% | 4.0% |

**Caching assumption.** D1 under the other cards (P2 / P3 / P4):

| Domain | P2: no write premium | P3: no caching | P4: cache lapses at user messages |
|---|---|---|---|
| τ²-bench airline | 17.0% | 33.0% | 4.0% |
| τ²-bench retail | 25.2% | 46.2% | 5.5% |
| τ²-bench telecom | 22.3% | 39.0% | 3.8% |
| Coding | 9.5% | 22.6% | 6.3% |

As with τ-bench, the liberal ceiling depends heavily on caching. With no caching, D1 clears 15% everywhere. If the cache lapses between user messages, it falls to about 4% to 6%.

**By agent model** (τ²-bench, P1, in the order claude-3-7-sonnet / gpt-4.1 / o4-mini):

| Domain | D1 | Batching null |
|---|---|---|
| airline | 16.7% / 9.3% / 7.3% | 2.4% / 0.4% / 1.2% |
| retail | 20.8% / 13.2% / 15.6% | 2.6% / 0.7% / 2.8% |
| telecom | 14.3% / 13.4% / 17.0% | 2.1% / 3.9% / 4.7% |

gpt-4.1 is the only agent that issues several calls in one message. Its batching null is the smallest in airline and retail, but not in telecom.

**Secondary table** (all eval trajectories, P1): τ²-bench D1 13.0% / 16.8% / 13.7% (airline / retail / telecom), D0 0.0%, batching 1.6% / 2.2% / 3.3%.

**What D1 deletes** (most deleted turns per domain): airline `get_reservation_details`, `get_user_details`, `search_direct_flight`; retail `get_order_details`, `get_user_details`, `get_product_details`, `find_user_id_by_name_zip`; telecom `get_details_by_id`, `get_customer_by_phone`; coding `git diff`, `cat`, `grep`. Most deletions are lookups by an identifier that the user typed or a previous result returned.

D1 also counts write calls whose arguments are all visible, for example `update_reservation_flights`, `return_delivered_order_items` and `send_payment_request`. Under this repository's invariants a host would hold such a write for approval, so these deletions overstate what host rules could do alone.

**Coding reading.** A bash coding agent spends almost every model turn on a tool call (D2 deletes 88% of turns and 45.5% of cost), but few commands consist only of words already present in the task or earlier output (D1 6.3%). The amendment predicted a low D1 here before the run, because a single-tool bash agent is a hard case for argument extraction.

## Results: tier ceiling (TwinRouterBench, eval split by instance)

Cost of running every labelled step at its `target_tier` against running every step at `high`, under TwinRouterBench's pinned 2026 prices (high = Claude Opus 4.6, low = DeepSeek V3.2). A model switch forfeits the cache.

| Slice | Instances (steps) | Share removed (95% interval) | Notes |
|---|---|---|---|
| **SWE-bench (coding)** | 18 (150) | **−5.0%** (−22.1% to +9.4%) | 71 of 150 steps need `high`. Downgrading the rest does not pay: every switch writes the full context to the other model's cache, and switching back rewrites it at Opus prices |
| BFCL | 65 (128) | 97.0% (96.7 to 97.2) | 124 of 128 steps are `low` |
| MTRAG | 99 (99) | 95.9% (95.7 to 96.0) | Input only: single steps, outputs unobserved |
| QMSum | 66 (66) | 95.9% (95.8 to 96.0) | Input only |
| PinchBench | 2 (6) | 96.2% (95.9 to 96.4) | 8 of 12 instances excluded as incomplete; too few to read |

**SWE-bench.** The SWE-bench ceiling is negative for a structural reason. Even with perfect labels and no failed steps, writing the context to a new model's cache on each switch costs more than the downgraded steps save. Its interval includes zero. #86 cites the TwinRouterBench preprint's finding that every router lost money on that slice, but for a different reason: one under-routed step fails the trajectory.

**Non-coding slices.** Almost every step in them is low-tier-sufficient. The low tier's input price is about 20× lower (0.252 against 5.00 USD per million tokens; output 66× lower), so their ceiling sits near the price ratio. They are mostly single-turn workloads, and the labels come from successful strong-model runs.

These ceilings bound **tier downgrading**, not turn removal, and are not part of the decision rule.

## Calibration of the token estimator (τ²-bench)

Estimated tokens against provider-reported usage, on agent turns that carry it (primary analysis set):

| Domain | Input: estimate ÷ `prompt_tokens`, median (IQR) | Output: estimate ÷ `completion_tokens`, median (IQR) |
|---|---|---|
| airline (n = 1,627) | 1.05 (0.75 to 1.16) | 0.62 (0.22 to 1.00) |
| retail (n = 6,983) | 1.09 (0.88 to 1.27) | 0.55 (0.19 to 0.93) |
| telecom (n = 4,044) | 1.07 (0.89 to 1.14) | 0.60 (0.19 to 1.07) |

- **Input** is estimated within about 10% at the median, including the prefix sized from the policy text and the `v0.1.0` tool definitions.
- **Output** is undercounted: the median estimate is 0.55 to 0.62 of what the provider billed, with a wide spread. The likely cause is tokens not visible in the transcript, such as reasoning tokens (o4-mini) and tool-call formatting.

Deleting a turn would also save its unseen output, so every turn-removal share here is biased **downward** by an amount not computed. The τ-bench run had no usage to check against and carries the same kind of bias.

## Acceptance criteria in #86

| Criterion (as worded in #86) | State |
|---|---|
| Protocol committed before the script is run on the evaluation split, including the three oracle definitions and the decision rule | Met: `PROTOCOL.md` (#97) and `PROTOCOL-AMENDMENT-1.md` (`c5e0e0b`, pushed before the script and the run) |
| Results table with intervals, both null ceilings, and every dataset attempted, including those that could not be used and why | Met: the batching ceiling on every domain, the tier ceiling on TwinRouterBench (the only set with step-level tier labels), and all five candidate datasets with their dispositions |
| A stated verdict from the rule above, and a one-paragraph note of what the result does not show | Met: SHRINK, with the reading of STOP disclosed; see "What this does not show" |
| `docs/release-status.md` gains a row labelled **Experimentally measured (re-priced public trajectories, no inference by this repo)** | Met in #97; updated here |

The minimum viable experiment asked for two or more sets, at least one not coding. This run used τ-bench and τ²-bench (non-coding) and the TwinRouterBench SWE-bench slice (coding).

## Post-freeze changes

**None.** `PROTOCOL-AMENDMENT-1.md` and `headroom_amendment1.py` are unchanged since the commits that precede the evaluation run. The commit that adds this file adds only results and documentation. Keep the three commits apart (no squash merge), so the ordering stays checkable.

## Reproduce

```bash
git clone https://github.com/sierra-research/tau2-bench && git -C tau2-bench checkout 768f3d8fe8528b4f32a5096f9ed008ae50f48ead
git -C tau2-bench worktree add ../tau2-v010 v0.1.0
git clone https://github.com/CommonstackAI/TwinRouterBench && git -C TwinRouterBench checkout 1f9c3aac01d82d27d81ef1f2ff3d04f279348ecb
python -I research/stage0_headroom/headroom_amendment1.py --tau2-root tau2-bench --tau2-tools-root tau2-v010 \
    --twinrouter-root TwinRouterBench --split eval --json-out /tmp/results-amendment-1.json
```

The script refuses any input whose SHA-256 differs from the amendment's pins. Re-running the unchanged script with the same inputs on Python 3.11, 3.12 and 3.13 reproduced the committed JSON byte for byte; the re-runs only checked determinism, and no definition or input changed between them. CI does not re-run this analysis, because the data is not in the repository; `tests/test_stage0_amendment1.py` pins the definitions.

## What this does not show

- That any policy, rule set or router achieves any of these shares. They are hindsight upper bounds on successful trajectories.
- That quality survives deleting a turn or downgrading a step. Nothing was re-run.
- Real cost. Tokens are estimated, with output undercounted (see the calibration). Prices are fixed cards applied to models of other vintages, and caching is assumed, not observed.
- Anything general about coding agents from 18 constructed instances, or about latency, current frontier models, or the safety half of the hypothesis.
