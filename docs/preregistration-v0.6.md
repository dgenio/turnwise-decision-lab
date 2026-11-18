# Pre-registration: decision-driven agent control vs a heavy-only agent (v0.6)

**Committed before any arm was run on the held-out set.** The held-out file, decision head, training data and code are frozen by this commit. Any post-freeze change is listed in `reports/v06/summary.md`.

## Research question

Can a lightweight decision-driven control architecture compete with, or outperform, a conventional agent whose control loop is run entirely by a capable LLM, **without reducing task success**?

Correctness and safety come first. Only after them does the comparison look at cost: local compute and heavy-model tokens per correctly resolved task. A cheaper architecture that is materially less reliable does not win.

## Frozen inputs

| Input | SHA-256 (prefix) | Note |
|---|---|---|
| `fixtures/v06_heldout.json` | `2995de1d9902b3fe` | 30 scenarios written by an independent agent from a world/tool specification only. It was told not to read routers, prompts, few-shot examples or training data. The author validated the schema, not the content. |
| `models/turnwise-dm-head.json` | `bf9b64ea98d8dcef` | Trained decision head. Template-held-out *synthetic* validation accuracy: 0.911. L2 and temperature were selected on that same split, so 0.911 is optimistic. |
| `fixtures/v06_dm_train.jsonl` | `28f3afb6d5f0edb0` | 614 synthetic states, labelled by procedural oracles over phrasing templates. No v0.5 data, no showcase sentences, no held-out content. |
| `fixtures/v06_dev.json` | `6b81b8f0e74d87d9` | Author-written development set, used for development and the public demo. **Not** evidence. |

## Models (local CPU, pinned in `models/local_models.json`)

- **Heavy tier, and the heavy-only agent:** Qwen3.5-0.8B (q4 ONNX). On development prompts it was the strongest reasoner within the ~4 GB download budget. Qwen2.5-1.5B int8 was rejected after it produced repetition and inverted facts. Within budget, "heavy" means "the most capable model available", not a frontier model.
- **Light tier:** Qwen2.5-0.5B (int8).
- **Decision layer (turnwise-dm):** a trained multinomial logistic head over three inputs: one cached constrained-scoring pass of Qwen3.5-0.8B (14 operation scores, **no decoding**), s1-llm-auto-router head outputs, and typed state features. **The decision layer shares weights with the heavy model.** The comparison therefore holds the model fixed and varies the **control mechanism**: trained head over constrained scores, versus the model generating its own tool calls.
- Decoding is greedy, so repeated runs are identical. Latency variability is reported from repeats of the showcase scenarios.

## Arms

| Arm | Control loop | Context for generation | Status |
|---|---|---|---|
| **A. heavy_agent** (primary baseline) | Qwen3.5-0.8B native tool calling, unlimited bounded steps, tool output returned to it, system+tools prefix cached across turns | conversation + incident record + concise schemas of all 10 tools; tool output rendered the same way as in D | run |
| rules | deterministic host policy | heuristic blocks | run |
| **D. dm_dynamic** | turnwise-dm + deterministic→light→heavy argument cascade + conservative escalation (gate 0.5) + verification protocol | decision-model block selection (yes/no per block) | run |
| E. dm_full | as D | all permitted blocks (fixed/full context) | run |
| dm_nogate | as D, no escalation gate | as D | run (ablation 3) |
| dm_llm_args | as D, no deterministic argument stage | as D | run (ablation 2) |
| gen_chooser | Qwen3.5-0.8B constrained choice alone (no trained head) | as D | run (small-LLM controller) |
| B. OpenAI Decisions controller | adapter in `agent/remote.py` | | **not run**: no credentials, no approved spend |
| C. Jev / System One controller | adapter in `agent/remote.py` | | **not run**: no credentials, no approved spend |

Component ablations:

1. Decision-based control: D vs A vs rules.
2. Deterministic arguments: D vs dm_llm_args.
3. Conservative escalation: D vs dm_nogate.
4. Dynamic context: D vs E.
5. Reduced or deferred tool schemas: **no separate arm**. The decision architecture never sends tool schemas to the generating model, so schema tokens are reported for A only. Any saving from this cannot be separated from (1) in this run.

## Outcome scoring (`agent/bench.py`, independent of routing)

- **Success:** the right outcome type (answer / clarify / approval request), all `required_facts` actually gathered by executed tools, the answer passing the `answer_must_include` / `answer_must_not_include` lexical checks, no forbidden call requested, and no write executed.
- **Separately reported:** silent failures (an answer was returned but failed the checks), dropped actions, false clarifications, wrong-argument calls, rejected proposals, unnecessary heavy calls, unnecessary escalations, verification requests and recoveries, decision latency and tokens, heavy tokens, end-to-end p50/p95, and local compute seconds per success.
- **Cost:** `provider_cost_usd` is null. Nothing was billed, and no price is attached to local compute.

## Decision rules and predictions

With n = 30, differences of 3 or fewer successes (≤10 pp) are treated as **inconclusive**.

| ID | Prediction | Falsified if |
|---|---|---|
| P1 | D's success is within 3 tasks of A's (comparable) | the gap is 4 tasks or more, in either direction (reported as a win or loss) |
| P2 | D uses ≥50% fewer heavy-model tokens than A | reduction < 50% |
| P3 | D's p50 end-to-end latency is lower than A's | it is not |
| P4 | gen_chooser succeeds on ≥4 fewer tasks than D (a small LLM alone is a weak controller) | gap < 4 |
| P5 | rules succeed within 3 tasks of D | gap ≥ 4 |
| P6 | dm_nogate has ≥ as many silent failures as D | fewer |
| P7 | dm_llm_args has ≥ as many wrong-argument calls plus false clarifications as D | fewer |
| P8 | E's success is within 3 tasks of D's, and D uses fewer heavy prompt tokens than E | either part fails |
| P9 | 0 writes executed in every arm | any write executed |

## Threats to validity, stated in advance

- **Small models.** The heavy tier is 0.8B, and any conclusion holds at this scale only. A frontier heavy model would likely raise A's success; whether it would also change the gap is unknown.
- **Authorship.** The held-out author is itself an LLM agent, though it never saw the router internals. The author of the world, the tools and the dev set also wrote the decision procedures that labelled the training data.
- **Answer checks are lexical** and accept some poor answers (for example, the greeting check has no content requirement).
- **Latency** is local CPU latency with prefix caching, not hosted-provider latency.
- **Development tuning.** The few-shot decision prompt, the generation prompt blocks, the evidence rendering and the runbook-retrieval query were all tuned on development scenarios. None was tuned on held-out data.
