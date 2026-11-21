# Stage 0 protocol, amendment 1 (2026-11-21): a coding set, the tier ceiling and the remaining candidate datasets

**Status: Proposed. Frozen before any oracle, cost or share was computed on any split of the data added here.** Git history is the timestamp: this file is committed before `headroom_amendment1.py` and before any result. [`PROTOCOL.md`](PROTOCOL.md) is unchanged and still governs the τ-bench analysis recorded in [`RESULTS.md`](RESULTS.md). Anything changed after this freeze is listed under "Post-freeze changes" in `RESULTS-AMENDMENT-1.md`. Issue: [#86](https://github.com/dgenio/turnwise-decision-lab/issues/86). No model is called and nothing is spent.

## Why an amendment

The first pass (#97) left three #86 acceptance criteria open, and `PROTOCOL.md` itself says the STOP branch needs "a dated amendment" that adds a coding set:

1. the **tier ceiling** was not computed, because τ-bench has no step-level tier labels;
2. only one of the candidate datasets named in #86 was **attempted**;
3. there was **no coding set**.

Everything not stated here is as in `PROTOCOL.md`: the estimator, the cost model and the four price cards, the oracle definitions, the batching ceiling, the D0 rule thresholds, the bootstrap (2,000 resamples over tasks, seed 86) and the outputs.

## Candidate datasets and their disposition

Decided from licence and structure only (see "What was inspected before this freeze").

| Candidate (#86) | Attempted | Used | Reason |
|---|---|---|---|
| τ-bench historical trajectories | yes (#97) | **yes**, unchanged | `PROTOCOL.md`, results in `RESULTS.md` |
| τ²-bench released trajectories | yes | **yes**, non-coding | MIT. The paper's trajectories, with tool calls, tool results and provider-reported token usage per message |
| TwinRouterBench static set | yes | **yes**: SWE-bench slice as the coding set; every slice for the tier ceiling | Apache-2.0. Step-level `target_tier` labels; the SWE-bench slice holds 40 complete step sequences of a bash-tool coding agent with structured tool calls |
| mini-SWE-agent trajectories (SWE-bench `experiments`, bash-only submissions) | yes | no | The trajectories sit in a public S3 bucket that lists without credentials. No licence is stated for them (the repository README says only that logs are "publicly accessible and meant to enable greater reproducibility"). They carry no per-call token usage, and their actions are untyped bash text in markdown. The coding domain is covered by the TwinRouterBench SWE-bench slice, which comes from a mini-SWE-agent-based pipeline, carries structured calls and tier labels, and is Apache-2.0 |
| HAL traces (`agent-evals/hal_traces` on Hugging Face) | yes | no | Public and ungated; the archives are not encrypted (first local-file header checked by a 64-byte range request). The dataset has **no licence tag and no dataset card or README**, so its terms of use cannot be established. No archive was downloaded |

## Data pins

The data is not copied into this repository. The script takes local paths and refuses to run if a hash differs.

**τ²-bench**, `sierra-research/tau2-bench` at commit `768f3d8fe8528b4f32a5096f9ed008ae50f48ead`, directory `data/tau2/results/final/`, the nine default-mode files (agent model × domain; user simulator `gpt-4.1-2025-04-14`; 4 trials each). The `telecom-workflow` files are a non-default mode and are not used.

| File | SHA-256 |
|---|---|
| `claude-3-7-sonnet-20250219_airline_default_gpt-4.1-2025-04-14_4trials.json` | `40a2c6a246eab27db5cdefda895fbe7f44be78a23d300817248534aa606d66de` |
| `claude-3-7-sonnet-20250219_retail_default_gpt-4.1-2025-04-14_4trials.json` | `ed41dbd18c080154156484e3a0122c095e324a11367a640d88e15956daed7b9d` |
| `claude-3-7-sonnet-20250219_telecom_default_gpt-4.1-2025-04-14_4trials.json` | `f49e540896fe91ab8631647f02eb777ef6fed5a6ebec545f43e71d0504e227b2` |
| `gpt-4.1-2025-04-14_airline_default_gpt-4.1-2025-04-14_4trials.json` | `31d19e79b8ddc5934a60701f913ff5fefb41dee5e68f7b813c26254ab2e2d5c8` |
| `gpt-4.1-2025-04-14_retail_default_gpt-4.1-2025-04-14_4trials.json` | `5fc5b96ada0fe46a463eaed98d1bfed9947fe073bac052290162dae18d71394e` |
| `gpt-4.1-2025-04-14_telecom_default_gpt-4.1-2025-04-14_4trials.json` | `8e1793f57a9e216514dbce1f93b44b0592d5904f1c5b97ab711906782107a1f2` |
| `o4-mini-2025-04-16_airline_default_gpt-4.1-2025-04-14_4trials.json` | `6a3a354c9bce42b52905af096e9cea6f555548acbb17b567fd403c356df7b4ec` |
| `o4-mini-2025-04-16_retail_default_gpt-4.1-2025-04-14_4trials.json` | `7135f38bbbbd46d6babe830574c8623bb276d8fd6da316580b905cf513853f98` |
| `o4-mini-2025-04-16_telecom_default_gpt-4.1-2025-04-14_4trials.json` | `1f46a6f296694bdb3ae203e6b379cdada0b8f17b648a4cf90d6343de1f1fb070` |

Tool definitions: the commits recorded in these files (`c30d59aa…` for airline and retail, `f125e68a…` for telecom) are not reachable from any public ref. Tool definitions are therefore taken from the earliest public release, tag `v0.1.0` (`37199f36924c8896f5e048360691f8476cd89ba1`, 2025-06-10), files `src/tau2/domains/<domain>/tools.py`, SHA-256 `3987f21c…aa26` (airline), `7063727d…613f` (retail), `38855243…9d01` (telecom). This is an approximation of what the runs saw and is reported as one.

**TwinRouterBench**, `CommonstackAI/TwinRouterBench` at commit `1f9c3aac01d82d27d81ef1f2ff3d04f279348ecb`:

| File | SHA-256 |
|---|---|
| `data/static/question_bank.jsonl` | `5b4f90c24643b214a9b0f26bf4e05afc742554262f4ef405e0b3b4a4cce503f4` |
| `data/dynamic/tier_to_model.json` | `10c14b0c2d2a8fd096280504c7aae9acf948abf74f590bd6ea8ac6689d138c4f` |
| `data/dynamic/model_pricing.json` | `1638ca92ea47ee4c70db09e078c58a71fa85bde623d76123d421b1c11749832a` |

## What was inspected before this freeze

Structure only. No oracle, cost or share was computed on any split of τ²-bench or TwinRouterBench.

- **τ²-bench:** the file list; record, simulation and message keys; message counts by role; tool calls per message by role (gpt-4.1 issues up to 12 calls in one message; the other agents one); the `requestor` field (in telecom the user simulator makes its own tool calls); `usage` keys (`prompt_tokens`, `completion_tokens`) and their coverage (91% to 94% of agent messages); the `info` block (`environment_info.policy` holds the agent policy text; `tool_defs` is null); the generating commits and the fact that they are not public; in `v0.1.0`, that tools are methods decorated `@is_tool(ToolType.…)` and how many there are per domain (15, 16, 13).
- **TwinRouterBench:** the manifest; row keys; rows per slice (swebench 336, bfcl 248, mtrag 193, qmsum 145, pinchbench 48); that all 40 SWE-bench instances have complete step sequences; label counts per slice (swebench: high 168, low 94, mid_high 41, mid 33; all slices: low 689, high 170, mid 62, mid_high 49); the tool-call shape of the SWE-bench slice (one tool, `bash`, argument `command`, one to four calls per message); the `total_steps` distribution per slice; the pricing, tier-map and TTL tables.
- **mini-SWE-agent:** one submission's `metadata.yaml` (S3 paths, totals of cost and calls) and a three-key S3 listing. No trajectory file was opened.
- **HAL:** the file list with sizes and one 64-byte range read. No archive was downloaded.

The author of this amendment reviewed #97 and reproduced its τ-bench results, so the τ-bench verdict (SHRINK) and its figures were known when this was written.

## Split

The `PROTOCOL.md` formula, with new domain keys, so the new splits are independent of the τ-bench split already used:

`split = "train" if int(sha256(f"{key}:{task_id}").hexdigest()[:8], 16) % 2 == 0 else "eval"`

with `key` = `tau2-airline`, `tau2-retail`, `tau2-telecom` (τ²-bench `task_id`) and `swebench` (TwinRouterBench `instance_id`). For the tier ceiling's other slices, `key` = `twinrouter-<benchmark>`.

**Primary analysis set:** eval split, reward 1. τ²-bench: `reward_info.reward == 1`. TwinRouterBench SWE-bench slice: every trajectory is treated as reward 1, because its labels were built from successful trajectories; this is stated, not checked.

## τ²-bench: the agent's transcript

- **What the agent sees:** assistant messages, tool messages whose `requestor` is `assistant`, and user messages that carry no tool calls. User messages with tool calls, and tool messages whose `requestor` is `user`, belong to the user simulator's own environment and are left out.
- **Several calls in one turn.** A tool turn is an assistant message with at least one tool call. Its name, for D0 keys and rules, is its first call's name, as in `PROTOCOL.md`. Its call tokens are the sum over its calls of `tokens(name) + tokens(JSON arguments)`. The turn is **determinable** when every call is, and a **read call** when every call's tool is a read tool. D0 deletes it when it is a determinable read call and a rule predicts its name. The batching ceiling uses turn-level determinability as in `PROTOCOL.md`.
- **Read tools:** the `PROTOCOL.md` name-prefix rule, unchanged. Its agreement with τ²-bench's own `ToolType.READ` labels in `v0.1.0` is reported, not used.
- **Stable prefix:** `tokens(environment_info.policy)` from each file, plus the tool definitions. Each method decorated `@is_tool` in `v0.1.0`'s `tools.py` is parsed with `ast`, never imported or executed, and rendered as the JSON of its name, docstring, and parameter names with their annotation source; that JSON is tokenised with the estimator. Telecom uses the agent's `tools.py` only, not `user_tools.py`.
- **Calibration (reported, not used in any share).** For agent turns that carry provider usage, the ratio of estimated input tokens (prefix plus transcript before the turn) to `prompt_tokens`, and of estimated output tokens to `completion_tokens`: median and interquartile range per domain, on the primary analysis set.

## TwinRouterBench SWE-bench slice: the coding set

- **Trajectory.** For each instance, the messages of its last step (`step_index == total_steps`) are the transcript up to the final model call. They are followed by that final model turn, whose output is not in the data: it is a model turn with 0 output tokens that no oracle deletes, so it appears identically in every cost. The messages of step *k* must be a prefix of those of step *k + 1*; an instance that fails this is excluded and counted.
- **Prefix:** the system message. The data carries no tool definitions; they count as 0 tokens.
- **Bash calls as tool calls.** A call's `command` is tokenised with `shlex` (POSIX mode, punctuation characters split) and cut into segments at `&&`, `||`, `;`, `|` and `&`. A segment's *program* is its first word, or its first two words when the first is `git`. Segments whose program is `cd` are ignored for the program checks.
  - The call's **name** is the program of its first remaining segment.
  - The call is a **read call** when there is no `>`, `>>` or `tee` anywhere and every remaining segment is read-only. A segment is read-only when its program is one of `cat head tail ls find grep egrep rg nl wc pwd file stat tree sort uniq cut diff`, or is `sed` with `-n` and without `-i`, or is `git diff`, `git log`, `git show` or `git status`.
  - Its **leaves** are every word left after removing each segment's program words, words that start with `-`, and the operators. The call is **determinable** when every leaf is present in context, under the `PROTOCOL.md` rule. A command `shlex` cannot parse is neither a read call nor determinable.
- **D0 rules:** as in `PROTOCOL.md`, with these names. A rule is kept only when its predicted name is one of the read-only programs above, `sed` or a read-only `git` subcommand. A fire is correct only when the turn is a determinable read call with that name.
- Several calls in one turn are handled as for τ²-bench.

## Tier ceiling (TwinRouterBench, every slice with labels)

- **Unit:** a labelled step is one model call. Its input is the step's messages, estimated as above, including tool-call JSON. Its output is the new assistant message in the next step's messages, or 0 tokens when that is not observed (the last step of an instance, and every single-step row).
- **Completeness:** an instance whose labelled steps do not form the full sequence `1 … total_steps` is excluded and counted.
- **Prices:** TwinRouterBench's `model_pricing.json`, through `tier_to_model.json`, as pinned above. Fresh input is priced at the higher of `input_per_m` and `cache_write_per_m`, following P1's convention that fresh input is written to cache without letting a published write price below the input price make fresh input cheaper. Cache reads are priced at `cache_read_per_m` and output at `output_per_m`.
- **Caching:** as in `PROTOCOL.md` (the previous call's input is read from cache when it is at least 1,024 tokens), but only when the previous call used the **same model**. A model switch reads nothing and writes the full input: the cache is per model.
- **Baseline:** every step at the `high` tier. **Tier ceiling:** every step at its `target_tier`. Share removed = 1 − tiered cost / baseline cost.
- **Reported** per slice on the eval split by instance, with a 95% cluster-bootstrap interval over instances (2,000 resamples, seed 86); all instances as a secondary figure. Slices with no observed outputs are labelled input-only.

The tier ceiling is a null ceiling, reported for comparison. It is not part of the decision rule.

## Decision rule for the combined verdict

Applied to P1 point estimates on the primary analysis sets. The τ-bench values are read from the committed `results.json` (#97), not recomputed. **Non-coding domains:** τ-bench airline and retail; τ²-bench airline, retail and telecom. **Coding:** the TwinRouterBench SWE-bench slice.

1. **INCONCLUSIVE** if neither dataset added here can be used as specified.
2. **STOP the economic claim** if D1 removes less than 15% in every non-coding domain **and** on the coding set.
3. **SHRINK to native features** if, in every domain, coding included, the batching ceiling is at least as large as D0.
4. **PROCEED to the paid comparison** if, in at least one non-coding domain, D0 removes at least 15% and exceeds the batching ceiling.
5. **HOLD** in every other case.

Rules are checked in this order and the first that applies is the verdict. A threshold inside an interval is called out. The τ-bench-only verdict recorded in `RESULTS.md` stands as recorded.

## Threats to validity, declared in advance

Those of `PROTOCOL.md`, plus:

- **The coding set is small and constructed.** 40 instances, about half of them in the eval split, built by TwinRouterBench's routing pipeline from successful runs. The final model turn's output is unknown. The bash mapping and its read-only list were written by this amendment's author after seeing the data's structure and the τ-bench result, but before computing anything on this data. A single-tool bash agent is a hard case for argument extraction, so D1 is expected to be low on it; that is a property of coding agents, not a defect of the definition.
- **τ²-bench:** paper-era tasks from before the task fixes in v1.0.0; tool definitions approximated from `v0.1.0`; tokens estimated, with the error reported by the calibration.
- **Tier ceiling:** 2026 OpenRouter prices for TwinRouterBench's own model pool, applied to its trajectories; labels conditional on a successful strong-model trajectory; single-step slices are input-only.

## What a result here will not show

That any policy achieves an oracle, that quality survives deleting a turn or downgrading a step, anything about latency, or anything about agents and workloads unlike these. Every figure is a hindsight upper bound on trajectories that already succeeded.
