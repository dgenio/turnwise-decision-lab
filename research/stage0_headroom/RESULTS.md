# Stage 0 results: avoidable-model-turn headroom on τ-bench trajectories

**Status: Experimentally measured (re-priced public trajectories, no inference by this repo).** Run on 2026-11-21 under [PROTOCOL.md](PROTOCOL.md), which was committed before the script and before this run. Issue: [#86](https://github.com/dgenio/turnwise-decision-lab/issues/86). Every token figure is an estimate (`ceil(characters / 4)`); the trajectories carry no provider usage. Every share is a hindsight ceiling, not a saving anyone achieved.

## Verdict

**SHRINK**, by the frozen decision rule: in every domain the batching ceiling is at least as large as the strict oracle D0 (airline 1.5% against 0.0%, retail 4.0% against 0.3%).

The paid comparison is **not** supported on this evidence: PROCEED needed D0 to remove at least 15% of cache-aware cost in some domain, and it removed at most 0.3%.

How the rule was walked, on the P1 point estimates of the primary analysis set:

1. INCONCLUSIVE: no. The data could be used as specified and every tool definition parsed.
2. STOP pending a coding set: no. D1 is below 15% in airline (14.9%) but not in retail (26.3%). **The threshold sits inside the airline interval** (11.7% to 18.7%), so airline alone does not settle on either side of it. Retail's interval (24.7% to 28.0%) is clear of it, so this branch would not have applied either way.
3. SHRINK: yes.

## What was measured

Trajectories of two 2024 models (`gpt-4o`, `sonnet-35-new`) on τ-bench airline and retail, from `sierra-research/tau-bench` at commit `59a200c`. Tasks were split by a hash of the task id. The training half (91 tasks, 1,092 trajectories) was used to write the script and mine the D0 rules. The evaluation half (74 tasks, 888 trajectories) was run once.

**Primary analysis set:** evaluation-split trajectories with `reward == 1`. Share of cache-aware cost removed under the primary price card P1, with a 95% interval from a bootstrap over tasks; share of model turns deleted in brackets.

| | Airline: 141 trajectories, 18 tasks, 1,170 model turns | Retail: 415 trajectories, 51 tasks, 5,510 model turns |
|---|---|---|
| **D2 ceiling** (delete every tool turn) | 29.8% (27.1 to 32.6) [50.3% of turns] | 28.9% (27.4 to 30.4) [54.9%] |
| **D1 liberal** (arguments found in earlier user or tool text) | 14.9% (11.7 to 18.7) [35.5%] | 26.3% (24.7 to 28.0) [51.2%] |
| **D0 strict** (D1, a read tool, and a rule mined on the training half) | 0.0% (0.0 to 0.0) [0.0%] | 0.3% (0.1 to 0.5) [0.7%] |
| **Batching ceiling** (null: no policy) | 1.5% (0.4 to 2.8) [3.2%] | 4.0% (2.9 to 5.2) [8.7%] |
| Tier ceiling | not computed: no step-level tier labels | not computed |

### The answer depends on the caching assumption

Same set, same oracles, other price cards (no intervals, as pre-declared).

| Share of cost removed | P1 ideal caching (primary) | P2 no write premium | P3 no caching | P4 cache lapses at every user message |
|---|---|---|---|---|
| Airline D2 / D1 | 29.8% / 14.9% | 35.5% / 19.3% | 51.5% / 34.2% | 21.8% / 7.0% |
| Retail D2 / D1 | 28.9% / 26.3% | 36.3% / 33.3% | 54.4% / 50.4% | 13.2% / 11.3% |
| Airline D0 / batching | 0.0% / 1.5% | 0.0% / 2.1% | 0.0% / 4.2% | 0.0% / 0.7% |
| Retail D0 / batching | 0.3% / 4.0% | 0.4% / 5.4% | 0.7% / 9.3% | 0.1% / 1.7% |

Counting model turns overstates the liberal ceiling about twofold against ideal caching (retail: 51% of turns, 26% of cost) and more than fourfold when the cache lapses between user messages (11%). This is consistent with the argument in [#85](https://github.com/dgenio/turnwise-decision-lab/issues/85), here on recorded trajectories with estimated tokens.

### By file

P1, primary analysis set, 95% interval over the tasks of that file.

| File | Trajectories / tasks / model turns | D2 | D1 | D0 | Batching |
|---|---|---|---|---|---|
| `gpt-4o-airline` | 39 / 14 / 341 | 13.2% (10.8 to 15.9) | 7.3% (4.8 to 10.5) | 0.0% | 0.2% (0.0 to 0.6) |
| `gpt-4o-retail` | 124 / 44 / 1,665 | 18.2% (16.9 to 19.9) | 16.6% (15.1 to 18.0) | 0.5% (0.3 to 0.8) | 1.9% (1.2 to 2.9) |
| `sonnet-35-new-airline` | 102 / 18 / 829 | 34.3% (30.7 to 38.2) | 17.0% (13.6 to 20.8) | 0.0% | 1.8% (0.4 to 3.4) |
| `sonnet-35-new-retail` | 291 / 50 / 3,845 | 32.2% (30.7 to 33.6) | 29.3% (27.7 to 31.0) | 0.2% (0.0 to 0.4) | 4.7% (3.5 to 6.0) |

The two models differ by roughly a factor of two. The exploratory section below looks at why.

### D0 rules and false fires

Rules kept from the training half (support at least 20, share at least 90%, read tool):

- **Airline: none.** No rule fired, so the false-fire rate is **unknown**, not 0.
- **Retail: one**, `TOOL:list_all_product_types → get_product_details` (91% of 67 training turns).

On the primary set the retail rule fired 47 times and was correct 41 times: a **false-fire rate of 12.8%** (0 of 27 on `gpt-4o`, 6 of 20 on `sonnet-35-new`). A false fire is a call the host would have made that the agent did not.

### What D1 deletes

Tools with the most D1-deleted turns on the primary set (the protocol asks for ten; only nine airline tools had any):

- **Airline (415 turns):** `get_reservation_details` 231, `get_user_details` 109, `search_direct_flight` 22, `update_reservation_flights` 14, `search_onestop_flight` 12, `update_reservation_passengers` 9, `cancel_reservation` 9, `update_reservation_baggages` 6, `list_all_airports` 3.
- **Retail (2,823 turns):** `get_order_details` 971, `get_user_details` 362, `find_user_id_by_name_zip` 352, `get_product_details` 325, `find_user_id_by_email` 229, `exchange_delivered_order_items` 128, `return_delivered_order_items` 114, `modify_pending_order_items` 106, `modify_pending_order_address` 99, `cancel_pending_order` 50.

D1 as frozen deletes state-changing calls too (497 of the retail turns listed above). It asks only whether the argument values were visible, not whether choosing that tool, or that moment, needed a model.

### Secondary: all evaluation trajectories, successful or not

P1 point estimates, no intervals.

| | Airline: 264 trajectories, 22 tasks, 2,894 model turns | Retail: 624 trajectories, 52 tasks, 8,640 model turns |
|---|---|---|
| D2 / D1 | 32.1% / 16.3% | 28.8% / 26.1% |
| D0 / batching | 0.0% / 2.4% | 0.3% / 4.1% |
| D0 fires, correct, false-fire rate | 0, 0, unknown | 91, 71, 22.0% |

Airline D1 is above 15% here and below it on the primary set, which is the same threshold-inside-the-interval caveat as above. The verdict uses the primary set.

## Reading the result

These four statements are supported:

1. **Host rules keyed on the previous observation recover nothing here.** At a 90% bar with at least 20 training turns, one previous-observation key in retail and none in airline predicts a read tool as the next action.
2. **Batching is also small** (1.5% and 4.0%). Few tool turns follow another tool turn in the same run with arguments that were already visible before the run began. SHRINK here means "neither mechanism has demonstrated headroom", not "native batching captures a large saving".
3. **The liberal ceiling is moderate and fragile.** 15% to 26% under ideal caching, 7% to 11% if the cache lapses between user messages, and lower again on read tools only or on a model that does not narrate (see below).
4. **Any deployable policy has to live in the gap between D0 and D1.** This run says where the gap is. It does not say whether a richer rule family or a learned gate ([#91](https://github.com/dgenio/turnwise-decision-lab/issues/91)) can reach into it.

**A limit of this verdict, stated plainly.** D0 is one pre-registered way of writing "what host rules could do": a single rule per previous observation, per domain. It is deliberately strict and it produced one rule. A rule family keyed on more state might recover more. That is a new hypothesis. It needs its own protocol and **different trajectories**, because this evaluation half has now been seen. D0 was not adjusted after the training-half development run showed it would be near zero, and it must not be adjusted now.

## Exploratory, post hoc

Not in the protocol, computed after the run, **not used for the verdict**. Reproduced by `exploratory.py`; output in `exploratory.json`. P1, primary set.

| Scope | D1 as frozen | D1 on read tools only | Share of the cost D1 removes that is text written next to a deleted call, billed as output | Tool turns that carry such text |
|---|---|---|---|---|
| Airline | 14.9% | 13.0% | 41% | 476 of 589 |
| Retail | 26.3% | 18.8% | 38% | 2,217 of 3,024 |
| `gpt-4o-airline` | 7.3% | 5.9% | 7% | 12 of 125 |
| `gpt-4o-retail` | 16.6% | 12.1% | 4% | 61 of 868 |
| `sonnet-35-new-airline` | 17.0% | 14.9% | 45% | 464 of 464 |
| `sonnet-35-new-retail` | 29.3% | 20.8% | 44% | 2,156 of 2,156 |

Two things follow, as observations and not as tested claims:

- **Close to half of the liberal ceiling on the `sonnet-35-new` files is the model's own text beside its tool calls.** That model wrote text on every tool turn; `gpt-4o` did on about 7% of them. If that text is reasoning the agent needed, deleting it is not free, and the D1 figure for a narrating model is the most optimistic number in this document.
- **Restricting D1 to read tools lowers the liberal ceiling to 13% (airline) and 19% (retail).** A write whose argument values are visible still needs a decision to make it, so the read-only figure is the more defensible ceiling.

## Post-freeze changes

**None.** `PROTOCOL.md` and `headroom.py` are unchanged since the commits that precede the evaluation run (`716eb35` and `675177b`). The commit that adds this file adds only results, the exploratory script and documentation. That ordering can be checked only while those three commits are kept apart: a squash merge would erase it.

**Update (2026-11-21, review before merge; no result changed).** A fourth commit adds one input check to `headroom.py`: it refuses to run when a domain's `tau_bench/envs/<domain>/tools/` directory holds no tool definitions. Without it, a clone containing only `historical_trajectories/` (the four pinned files) ran, gave every domain 0 tool-definition tokens, a smaller stable prefix and different cost shares, and listed nothing under `tool_definition_problems`. The reviewer hit exactly that before fetching the full repository. On a full clone at `59a200c`, `results.json` and `exploratory.json` reproduce byte for byte with the committed files, before and after this change, on Python 3.12 and 3.13. The protocol and every definition it fixes are unchanged.

Choices the protocol left open, all made in `675177b` before the evaluation run and pinned by `tests/test_stage0_headroom.py`:

- Text written next to a deleted tool call leaves the transcript; only the call and its result stay. This raises every oracle.
- A merged (batched) call keeps its original position in the transcript for input accounting. The effect on the batching ceiling is small and in its favour.
- A whole-number float argument also matches its integer form. Arguments that are not valid JSON are treated as one string.
- D0 fires are counted at every model turn with the rule's key, reply turns included, as the protocol's wording says.
- Per-file intervals resample the tasks of that file.

Differences from the sketch in #86, all fixed in the protocol before the run: D0 is a `previous observation → tool` rule plus the D1 argument test, not a per-task-type template; the directory is `research/stage0_headroom/`.

## Acceptance criteria in #86

| Criterion | State |
|---|---|
| Protocol committed before the script is run on the evaluation split | Met (`716eb35`, then `675177b`, then this commit) |
| Results with intervals and both null ceilings | Partly. Batching ceiling reported. **Tier ceiling not computed**: these trajectories carry no step-level tier labels |
| Every dataset attempted, including unusable ones | One dataset was attempted and used: the τ-bench historical trajectories. The other candidates in #86 (HAL logs, τ²-bench trajectories, mini-SWE-agent trajectories, the TwinRouterBench static set) were **not attempted** in this pass |
| Two or more sets, at least one not coding | **Not met.** One non-coding set. No coding set, so the STOP branch could only have been reported as "pending a coding set" |
| Verdict from the rule, and what the result does not show | Met, above and below |
| `docs/release-status.md` row | Added with this commit |

## What this does not show

- That any policy, rule set or learned gate achieves any of these shares. Every figure is a hindsight upper bound on trajectories that already succeeded.
- That answer quality survives deleting a turn. Nothing was re-run; later behaviour is assumed unchanged.
- Real cost. Tokens are estimated from characters, prices are one card applied to 2024 models, and caching is assumed, not observed.
- Anything about latency, coding agents, current models, or agents that already batch tool calls. τ-bench has a simulated user and lookups by identifier, which is close to a best case for argument extraction.
- Anything about the safety half of the hypothesis (host authority), which this analysis does not touch.

## Reproduce

```bash
git clone https://github.com/sierra-research/tau-bench /path/to/tau-bench
git -C /path/to/tau-bench checkout 59a200c6d575d595120f1cb70fea53cef0632f6b
python -I research/stage0_headroom/headroom.py --tau-bench-root /path/to/tau-bench --split eval \
    --json-out research/stage0_headroom/results.json
python -I research/stage0_headroom/exploratory.py --tau-bench-root /path/to/tau-bench \
    --json-out research/stage0_headroom/exploratory.json
```

The script refuses to run if a trajectory file's SHA-256 differs from the protocol. The data is third-party (MIT licence) and is not copied into this repository; `results.json` and `exploratory.json` hold aggregates only. CI does not re-run this analysis, because the data is not in the repository; `tests/test_stage0_headroom.py` pins the definitions on synthetic trajectories.
