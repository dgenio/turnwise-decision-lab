# Level C protocol: the exit gate against a capable agent (prepared, not run)

**Status: a design ready to be frozen. Nothing here has been run. No spend is authorised.** It makes [issue #9](https://github.com/dgenio/turnwise-decision-lab/issues/9) executable for the mechanism studied in v0.7. Every item marked *(owner)* is a decision for the project owner and must be fixed before any call is made.

## Why this is the experiment that matters

v0.7 measured the exit gate around a 0.8B model that over-calls tools, loops and sometimes answers with no evidence at all. A capable agent may already gather both sides of a causal question unprompted. Then one of two things is true, and they point in opposite directions:

- the gate rarely fires, costs almost nothing, and its value is a small safety margin (dropped actions, unsupported claims) against a small typing risk; or
- capable agents still exit early often enough for the gate to matter. *Sufficient Context* ([arXiv:2411.06037](https://arxiv.org/abs/2411.06037)) and SafeActBench ([arXiv:2610.07753](https://arxiv.org/abs/2610.07753)) report that strong models answer on insufficient context and stop with incomplete investigation, which makes this plausible but does not establish it for this setting.

Level B cannot tell these apart. That is the whole reason for Level C.

## Arms

All arms use the same host, tools, permissions, step limit and the **same capable model** *(owner: which model)*.

| Arm | What it is | Code path |
|---|---|---|
| A | Capable heavy-only agent, provider-native tool calling | `v07/hosted.py` `run_hosted_agent(gate=None)` |
| A+G | A behind the exit gate | `run_hosted_agent(gate=ExitGate())` |
| B | A with provider-native tool search or deferred schemas, where the provider has it | not implemented; isolates the schema share |
| C | Contract planner; untyped requests go to A+G | `run_contract_turn(fallback=functools.partial(run_hosted_agent, chat=chat))`; tested against a fake server |
| C-N | C, with the capable model narrating the host findings | `narrate=True` |
| R+G | v0.6 rules behind the gate, capable model for generation | optional |

The learned head (`dm_dynamic`) is **not** carried into Level C unless v0.7's locked run shows it adds something behind the gate (prediction G5). A decision-service arm (OpenAI Decisions, System One) is optional and needs its own cap.

## Data

- **New tasks.** v0.7's locked set is now seen. A new locked set is written by an author who has seen no v0.7 trace or failure, preferably a human *(owner: who)*, from [`v07-task-authoring-spec.md`](v07-task-authoring-spec.md). Multi-turn sessions and investigations with wrong premises must be well represented.
- **A wider world before the run.** One incident world with four services is the weakest part of the design. At least one more domain with different tool roles should be added, with its `EVIDENCE` metadata written by someone other than the gate's author. If the two-sided rule and the gate need no code change to work there, that is evidence of generality; if they do, that is the finding.
- **Splits.** Development and calibration tasks separate from the locked tasks; the locked file hashed in a freeze manifest before any arm runs (`v07/freeze.py` already does this).

## Outcomes

1. **Quality gate.** Paired non-inferiority of C (and of A+G) against A on blinded adjudicated correctness, margin δ *(owner)*, one-sided α = 0.025, Newcombe paired interval.
2. **Safety gate.** 0 executed unauthorised writes. Ceilings *(owner)* on dropped actions and on unsupported or contradicted causal claims of major or critical severity.
3. **Efficiency, only if both gates pass.** Provider-billed cost per attempted task with cached tokens priced separately, p50 and p95 latency, tool calls, and the gate's own overhead (extra tool calls, regenerations). Material threshold *(owner)*.

The primary outcome must be **adjudicated**, not lexical. v0.6 and v0.7 both show the lexical check passes replies the facts contradict, and that it favours host-written text. At least two graders, at least one human *(owner)*, disagreements recorded.

## Sample size

For a paired non-inferiority test with a true difference of 0, one-sided α = 0.025 and 80% power: n ≈ 7.84 · q / δ², where q is the share of tasks on which the two arms disagree.

| q (discordance) | δ = 15 pp | δ = 10 pp | δ = 5 pp |
|---:|---:|---:|---:|
| 0.40 | ~140 | ~315 | ~1,255 |
| 0.25 | ~90 | ~200 | ~785 |
| 0.10 | ~35 | ~80 | ~315 |

With a capable model both arms should succeed on most tasks, so q is likely to be far lower than in v0.6 or v0.7. A **pilot of about 40 tasks** estimates q before the size is fixed; the pilot tasks are then development data.

## Cost estimate method (no price is asserted here)

Per task: (model calls) × (uncached input + cached input + output tokens) at the provider's published prices on the day. v0.7's traces give the call counts and the tool-result sizes for this world; the system prompt and tool schemas are about 1,400 tokens and are cacheable. The adapter requires the prices as arguments, enforces the cap before every request and records provider-reported usage, so the estimate is checked against reality from the first call.

## What needs owner approval

1. The capable model and whether it is hosted or local (a 7–8B quantised local model exceeds the current ~4 GB download budget and is slow on CPU).
2. A spending cap in USD, if hosted.
3. δ, the two safety ceilings and the material efficiency threshold.
4. The task author and the graders.
5. Whether to add a second domain first (recommended).

## Smallest valid next step

A **40-task pilot with arms A and A+G only**, on new tasks, one capable model, a declared cap. It answers one question cheaply: *how often does a capable agent try to exit with the contract unmet?* If the answer is "almost never", the gate's case rests on safety alone and the project should SHRINK to that. If it is "often", the full design above is worth its cost.
