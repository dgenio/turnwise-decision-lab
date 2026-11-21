# Stage 0 protocol: avoidable-model-turn headroom on public agent trajectories

**Status: Proposed. Frozen before any script was run on the evaluation split.** Git history is the timestamp: this file is committed before `headroom.py` and before any result. Anything changed afterwards is listed under "Post-freeze changes" in `RESULTS.md`. Issue: [#86](https://github.com/dgenio/turnwise-decision-lab/issues/86). No model is called and nothing is spent.

## Question

On trajectories of a real, capable tool-calling agent, what share of cache-aware billed cost sits in model turns whose action a host could have determined without a model?

A hindsight oracle bounds this from above: no deployable policy can remove more than its own oracle. A small ceiling ends the economic half of the hypothesis cheaply. A large one is the first real-data motivation for it.

## Data

**Non-coding set (this pass):** the trajectories published in `sierra-research/tau-bench`, directory `historical_trajectories/`, at commit `59a200c6d575d595120f1cb70fea53cef0632f6b` (MIT licence).

| File | Records | Tasks × trials | SHA-256 |
|---|---|---|---|
| `gpt-4o-airline.json` | 200 | 50 × 4 | `e9e6c0297660c537f83d4fd9c476ce7a9a86ecd2784874b7bfc13be598e37bfa` |
| `gpt-4o-retail.json` | 460 | 115 × 4 | `df01707894836168ff0ec9616b0bf08f66c7e5afcf313e5fe4f7a2f5c2ec938b` |
| `sonnet-35-new-airline.json` | 400 | 50 × 8 | `fe62fcd514b855b36f156dd4c3c7748597b392b006aff739b53337a9f3ba94d1` |
| `sonnet-35-new-retail.json` | 920 | 115 × 8 | `0df526398e9d2720c32d340815cffb04fe8c4f8a61b1f4f84bf3bb558f760131` |

The data is not copied into this repository. The script takes the path of a local clone as an argument and refuses to run if a hash differs.

**Coding set:** not selected in this pass. Until one is added under a dated amendment, the STOP branch of the decision rule cannot be evaluated (see "Decision rule").

**What was inspected before this freeze.** Only structure, over all four files: record keys, message keys, counts of messages by role, the number of assistant messages with tool calls, the fact that no assistant message carries more than one tool call, the absence of per-call token usage, and each file's mean reward. No oracle, cost or share was computed on any split.

## Split

Tasks are split by task, not by record, so every trial and both models of a task fall on the same side:

`split = "train" if int(sha256(f"{domain}:{task_id}").hexdigest()[:8], 16) % 2 == 0 else "eval"`, with `domain` in `{"airline", "retail"}`.

- **Train** is used to develop the script and to mine the D0 rules. Nothing reported comes from it.
- **Eval** is used once, for every reported number.

**Primary analysis set:** eval-split trajectories with `reward == 1`. Removing a turn is only meaningful when the original turn was right. The same figures on all eval trajectories are reported as a secondary table.

## Units

- **Model turn:** one assistant message. A **tool turn** is an assistant message with a tool call. A **reply turn** is one without. In this benchmark's loop, text that accompanies a tool call is not shown to the user, so a tool turn has no user-visible output.
- **Tokens:** `ceil(characters / 4)`, the stated estimator, applied to message content and to the tool call's name and JSON arguments. The trajectories carry no provider usage, so every token figure is an estimate. Per-message formatting overhead is ignored.
- **Stable prefix:** the system message plus the domain's tool definitions. Tool definitions are read from the benchmark's source files by parsing the literal returned by each tool's `get_info()` with `ast.literal_eval`. No benchmark code is imported or executed. If a definition cannot be parsed that way, it is counted as 0 tokens and listed in the results.

## Cost model

Only the agent's model calls are costed. For each model turn `i`:

- `input_i` = stable prefix + every message before the turn.
- `cache_read_i` = `input_j` of the previous model turn `j` in the same trajectory, provided it is at least `min_cacheable` tokens; otherwise 0. The previous turn's own output is not cached: it re-enters as fresh input.
- `fresh_i` = `input_i − cache_read_i`.
- `output_i` = the turn's own tokens.
- cost = `fresh_i × P_fresh + cache_read_i × P_cached + output_i × P_output`.

Price cards, fixed here (USD per million tokens):

| Card | Fresh input | Cache read | Output | min_cacheable | Role |
|---|---|---|---|---|---|
| **P1 primary** | 2.50 (cache-write price) | 0.10 | 10.00 | 1,024 | The decision rule uses this card. Source: `docs/live-smoke-decision-packet.md` (input 2.00, cached 0.10, cache write 2.50, output 10.00; read 2026-11-19) |
| P2 | 2.00 | 0.20 | 10.00 | 1,024 | Sensitivity: cache reads at 0.1× and no write premium |
| P3 | 2.00 | 2.00 | 10.00 | n/a | Sensitivity: no caching |
| P4 | as P1 | as P1 | as P1 | 1,024 | Sensitivity: the cache lapses at every user message (the first model turn after a user message reads nothing from cache) |

Only price ratios matter for shares. The models in the data are older than the card; that is a stated limit, not a correction to make.

## Oracles

All are computed on the same trajectories by deleting model turns and re-costing the trajectory with the model above. A deleted tool turn's call and result stay in the transcript, because the host would still run the tool: they become fresh input to the next surviving model turn. Its output tokens are no longer billed as output.

**Read tools** are tools whose name starts with `get_`, `find_`, `list_` or `search_`. Every other tool, including `think`, `calculate` and `transfer_to_human_agents`, is not a read tool.

An argument leaf is **present in context** if its string form occurs, case-insensitively, as a substring of an earlier user message or an earlier tool result in the same trajectory. Leaves are the scalar values of the arguments after flattening lists and objects. A tool call is **determinable** if every string and number leaf is present in context. Boolean and null leaves and empty argument sets count as determinable. Assistant text and the system prompt are never a source.

| Oracle | A tool turn is deleted when | Role |
|---|---|---|
| **D2 ceiling** | always | Absolute ceiling for replacing control turns. Not achievable |
| **D1 liberal** | its call is determinable | Upper bound for deterministic argument extraction. It does not ask whether the choice of tool was determinable |
| **D0 strict** | its tool is a read tool, its call is determinable, **and** a rule mined on the train split predicts that tool at that position | Closest to what host rules could do |

**D0 rules.** The key of a model turn is `START` if it is the first model turn of the trajectory, `USER` if it directly follows a later user message, and `TOOL:<name>` if it directly follows the result of tool `<name>`. On train-split trajectories with `reward == 1`, per domain and pooled over both models, a rule `key → tool` is kept when the tool is a read tool, the key occurs at least 20 times, and at least 90% of the model turns with that key are a call to that tool. On the eval split a rule **fires** at every model turn with its key. A fire is **correct** when the actual turn is a determinable call to the predicted tool; only correct fires are deleted. Every other fire is a **false fire** and is reported as a count and a rate: it is a call the host would have made that the agent did not.

**Null ceilings**, computed the same way:

- **Batching ceiling.** Within a run of consecutive tool turns with no user message between them, a tool turn after the first is merged into the first when its call is determinable from the context available *before the first turn of the run*. A merged turn is deleted as a model call and its tool-call tokens are added to the output of the first turn of the run. This is what a native agent that batches independent calls would save with no policy at all.
- **Tier ceiling.** Not computed: these trajectories carry no step-level tier labels.

## Outputs

For each domain (both models pooled), each of the four files, and each oracle and null ceiling, on the primary analysis set:

- share of model turns deleted;
- share of cache-aware cost removed under P1, with a 95% percentile interval from a cluster bootstrap over tasks (2,000 resamples, seed 86);
- the same share under P2, P3 and P4, without intervals;
- for D0: the rules kept, fires, correct fires and the false-fire rate;
- for D1: the ten tools with the most deleted turns.

The secondary table repeats the P1 shares on all eval trajectories.

## Decision rule

From #86, applied per domain to the P1 point estimates on the primary analysis set. Intervals are reported and a threshold inside an interval is called out, but the rule uses point estimates.

1. **INCONCLUSIVE** if the non-coding data cannot be used as specified here.
2. **STOP the economic claim** if D1 removes less than 15% in both domains **and** on a coding set. With no coding set in this pass, a D1 below 15% in both domains is reported as **STOP pending a coding set**.
3. **SHRINK to native features** if, in every domain, the batching ceiling is at least as large as D0.
4. **PROCEED to the paid comparison** if, in at least one domain, D0 removes at least 15% and exceeds the batching ceiling.
5. **HOLD** in every other case, for example when only the liberal oracle clears 15%. This case is not in #86 and is added here, before the run.

Rules are checked in this order and the first that applies is the verdict.

## Threats to validity, declared in advance

- **Counterfactual optimism.** Deleting a turn may change what the model does later, and the text a model writes next to a tool call may matter. Every oracle is therefore biased upward. That is acceptable for a kill test and not for a savings claim.
- **Estimated tokens.** Characters divided by four, with no provider usage to check against.
- **One benchmark, 2024 models, a simulated user.** Customer-service dialogues with lookups by identifier are close to a best case for deterministic extraction. The agent in these runs issued one tool call per turn, which inflates what batching could save relative to a model that already batches.
- **Ideal caching.** P1 and P2 assume every prefix is read from cache within its lifetime. P4 bounds the other side for user-paced dialogues.
- **The D1 match is crude.** A short value can match by accident, and a value the user paraphrased will not match. Both directions exist; D1 is described as liberal, not as exact.
- **Authoring.** The oracle definitions were written by the same reviewer who proposed the hypothesis test, after seeing the data's structure but before computing any outcome.

## What a result here will not show

That any policy achieves the oracle, that quality survives deleting turns, anything about latency, or anything about coding agents.
