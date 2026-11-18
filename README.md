# Turnwise: route the work, not just the model

Model routers choose *which* model answers a turn. That may be one decision too late. Turnwise tests a different control architecture for agents. A **lightweight decision model chooses the next operation, again and again within one user request**: a tool, an existing workflow, a light or heavy generation model, finishing with verified data, or a clarifying question. An independent host validates every proposal before it runs, and every result can trigger a new decision. The project then measures whether that architecture can compete with a conventional agent whose whole loop is a capable LLM.

It is an experiment with real, recorded inference and its failures kept, not a framework or a product.

**[See one request handled by both architectures, step by step →](https://dgenio.github.io/turnwise-decision-lab/)** · [v0.6 report](reports/v06/summary.md) · [Pre-registration](docs/preregistration-v0.6.md) · [Architecture](docs/v06-architecture.md) · [Models](docs/v06-models.md)

### The next hypothesis: near-baseline quality, much lower cost

The target is **not** higher accuracy than a conventional heavy-LLM tool-calling agent. The hypothesis is that routing safe deterministic work away from the heavy model, using a decision service or light model only where justified, and shrinking the context of unavoidable heavy calls can deliver **similar or slightly worse end-to-end task quality at substantially lower cost and latency**. When unsure, prefer a heavy fallback; do not silently guess.

This is a **quality-constrained efficiency** experiment: first establish an acceptable, independently checked loss margin against an **actually executed heavy-only agent**; only then evaluate total cost, p50/p95 latency, heavy invocations and heavy-context tokens. No such non-inferiority or economic gain has been demonstrated yet. The existing v0.5 results expose risks rather than validating this thesis. See the [candidate v0.6 protocol](docs/quality-constrained-efficiency-v06.md) and [independent-evidence issue #3](https://github.com/dgenio/turnwise-decision-lab/issues/3).

## Result (v0.6, held-out)

30 tasks were written by an independent agent that never saw the routers. Seven architectures ran on the same synthetic incident world, with the same tools, harness, permissions and heavy model, using real local inference (CPU). Success is checked from the outcome alone: the right kind of reply, the needed evidence actually gathered, the answer content, and no forbidden or executed write. No provider was billed, so dollar cost is null; cost is local compute and heavy-model tokens per resolved task.

| Architecture | Success | Silent failures | Heavy-model calls | Heavy-model tokens | p50 / p95 latency | Local compute per resolved task |
|---|---:|---:|---:|---:|---:|---:|
| **A. Heavy-only agent**: Qwen3.5-0.8B runs the loop with native tool calling (primary baseline) | 13/30 | 12 | 125 | 174,422 | 14.2 s / 25.2 s | 30.61 s |
| Deterministic host policy (rules) | 14/30 | 13 | 1 | 615 | 0.4 ms / 12.3 s | 5.14 s |
| **D. Decision-driven**: turnwise-dm + argument cascade + escalation gate + dynamic prompt blocks | 16/30 | 11 | 9 | 6,105 | 1.6 s / 22.4 s | 13.15 s |
| E. D with full permitted context (ablation) | 16/30 | 11 | 9 | 6,687 | 1.5 s / 17.5 s | 11.04 s |
| D without the escalation gate (ablation) | 17/30 | 9 | 6 | 4,957 | 1.3 s / 21.5 s | 10.9 s |
| D with LLM-only argument construction (ablation) | 13/30 | 11 | 7 | 4,489 | 1.5 s / 20.9 s | 13.17 s |
| Small LLM as the controller, no trained head | 6/30 | 21 | 0 | 0 | 8.9 s / 19.8 s | 49.69 s |

What the experiment found:

1. **Success: comparable, not better.** Decision-driven control resolved 16/30 tasks, the heavy-only agent 13/30 and simple rules 14/30. Gaps of three tasks or fewer are inconclusive by the pre-registered rule.
2. **Much cheaper for the same success.** With the *same* 0.8B model in both architectures, the decision-driven loop used **96.5% fewer heavy-model tokens** (6,105 vs 174,422). Its median turn took 1.6 s instead of 14.2 s, and it needed 2.3× less local compute per resolved task. The deterministic host policy was cheaper still (5.14 s per resolved task).
3. **The two architectures fail differently, by task family.**
   - **The heavy-only agent** won investigations. It also over-called (16 calls about services the task was not about), requested 6 side effects nobody asked for (all held by the host), and never clarified an ambiguous request.
   - **The decision-driven loop** made **0** wrong-argument calls and **0** unrequested writes, and won lookups, ambiguity and adverse cases. But it **stopped gathering evidence too early on every investigation**: it finished with raw data, or escalated before fetching the deployment history.

| Task family | Heavy-only agent | Rules | Decision-driven (D) |
|---|---:|---:|---:|
| investigation | 4/7 | 3/7 | 0/7 |
| lookup | 1/6 | 3/6 | 4/6 |
| ambiguous | 0/4 | 2/4 | 3/4 |
| adverse | 1/2 | 1/2 | 2/2 |
| action request | 3/5 | 3/5 | 3/5 |
| multi turn | 1/3 | 1/3 | 2/3 |
| smalltalk general | 3/3 | 1/3 | 2/3 |

4. **"Escalate when uncertain" did not make the system safer (pre-registered P6 falsified).** Without the escalation gate the loop did *better* (17/30, 9 silent failures vs 11). The heavy model it escalated to answered with the evidence it had and never asked for more: the `NEED_MORE_EVIDENCE` protocol fired **0 times in every arm**. The heavy model answered despite missing evidence 4 times in D and 6 times in the heavy-only agent. Escalation is only conservative if the target can notice what is missing; at this scale it could not.
5. **Deterministic arguments matter.** Constructing arguments only with LLMs cost 3 tasks, added 3 wrong-argument calls, and doubled false clarifications (6 vs 3).
6. **Dynamic prompt-block selection did not pay here.** Success was identical with full permitted context. Dynamic selection saved only 11% of prompt tokens and cost more decision time (13.15 vs 11.04 s per resolved task).
7. **A small LLM is not a controller on its own** (6/30, 21 silent failures). What made the same model usable was a tiny trained head over its scores plus typed observation features from the host.
8. **Safety held everywhere:** 0 writes executed in any arm.

**Bottom line, at this scale.** Compared with letting the LLM run the loop, decision-driven control is far cheaper and better behaved, with comparable success. But it is **not more reliable**, it **loses on multi-step investigations**, and **a deterministic host policy matched it** at a fraction of the cost. These data do not establish that a *learned* decision layer beats good rules, or that the conservative policy as built helps. A stronger heavy model and hosted decision services are the obvious next tests.

All 9 pre-registered predictions, every failure and all component ablations are in [the report](reports/v06/summary.md).


## How one user turn runs

```text
user message ─► compact state (request + every observation so far)
                   │
                   ▼
   turnwise-dm decision ──uncertain (p<0.5)──► heavy model + verification protocol
   (trained head over one cached Qwen3.5-0.8B scoring pass,
    s1-llm-auto-router heads and typed state; 14 operations, action mask)
                   │
   ┌───────────────┼──────────────────┬───────────────┬────────────┐
 tool / workflow   light model     heavy model       finish        clarify
   │  argument cascade: deterministic → light LLM → heavy LLM → clarify
   ▼  host validation: schema, permission, side effects, repeats, retries
 LocalHarness executes reads; writes become approval requests (never executed)
   │
   └─► observation appended to state ─► decide again (bounded: 8 steps)

 model call: context decision (yes/no per eligible block) → host assembles the prompt
             (mandatory blocks, permissions, budget, redaction) → generate
             → final answer, or NEED_MORE_EVIDENCE → decide again
```

Every step is recorded: `user_turn_id`, `step_index`, `decision_call_id`, the decision model and version, every option it scored and **what kind of score** it is, the argument mechanism, the host's validation, the tool result, the blocks included and excluded, the exact assembled prompt, the generation, tokens, latency, and why the loop continued or stopped.

## What is real, and what is not

| Real (observed and recorded) | Not run, or not real |
|---|---|
| Every decision: local inference of turnwise-dm, s1-llm-auto-router and Qwen3.5-0.8B on CPU | OpenAI Decisions and Jev / System One: adapters and fake-server tests only (no credentials, no approved spend) |
| Every tool and workflow call, through the host and `LocalHarness`, against a synthetic world | Frontier models: "heavy" is Qwen3.5-0.8B, the strongest reasoner within the ~4 GB budget |
| Every generation, by Qwen2.5-0.5B (light) and Qwen3.5-0.8B (heavy, and the heavy-only agent) | Dollar costs (nothing was billed) and hosted latency |
| Token counts from each model's tokenizer; latency measured on the CPU named in each trace | Answer quality beyond lexical outcome checks |

The public page **replays** recorded traces and says when and where they were recorded. CI re-executes the host side of every recorded trace: it feeds back the recorded decisions and generations, and checks that every tool observation, outcome and score reproduces exactly.

## Reproduce

```bash
python -m unittest discover -s tests                 # no models, no network
python -m turnwise_lab.agent.bench --report          # rebuild reports/v06/summary.{json,md} from recorded traces
python -m turnwise_lab.agent.demo                    # rebuild demo/index.html
```

Re-running real inference (CPU, about 3 GB of pinned weights, outside the repository):

```bash
pip install ".[local]"
python -m scripts.fetch_models                       # pinned revisions, sha256-verified
python -m turnwise_lab.agent.dm_train                # optional: retrain turnwise-dm (about 10 min)
python -m turnwise_lab.agent.bench --set heldout --arms all
```

Decoding is greedy, so outputs reproduce on the same software stack and only latency varies. Other CPUs or onnxruntime versions may flip close decisions.

## Where this is weak

- **Scale.** The heavy model is 0.8B parameters and every conclusion holds at this scale only. A frontier heavy model would very likely raise the heavy-only agent's success; whether the gap closes, widens or reverses is unknown.
- **Authorship.** The 30 held-out tasks were written by an independent LLM agent that never saw the routers. The development set, the world, the tools and the procedures that labelled turnwise-dm's training data were all written by the project author.
- **Lexical outcome checks.** They catch missing evidence, wrong outcome types and wrong content, but accept some poor answers.
- **n = 30.** Differences of three tasks or fewer are treated as inconclusive.
- **Untested components.** Tool-schema savings are not isolated as a separate arm, and hosted decision services were not run.

## How this relates to existing work

- [LiteLLM auto routing](https://docs.litellm.ai/docs/proxy/auto_routing) routes **between models**; the completion always goes to a model.
- [vLLM Semantic Router](https://github.com/vllm-project/semantic-router) does signal-driven model selection. Its [vision paper](https://arxiv.org/abs/2603.21354) frames joint (model, tool) selection as a research opportunity.
- [OpenAI Decisions](https://developers.openai.com/api/docs/guides/decisions) and TypeSafe Jev are hosted decision services this loop is designed to use. Adapters are in `turnwise_lab/agent/remote.py`.
- Provider tool search reduces the cost of tool schemas, a component not isolated here.

This repository adds a reproducible, outcome-scored comparison of *decision-driven control* against *LLM-driven control* with the model held fixed, with every step inspectable.

## Useful contributions

1. **Run the hosted arms.** With your own key and a spending cap, run OpenAI Decisions or Jev as the controller (`agent/remote.py`) on the frozen held-out set.
2. **Swap in a stronger heavy model.** Run both architectures with it: the most important open question.
3. **Write more held-out tasks**, in the schema of `fixtures/v06_heldout.json`, without reading the router code.
4. **Fix a failure mechanism** from the report, then evaluate the fix on *new* tasks.

## Repository map

| Path | What it is |
|---|---|
| `turnwise_lab/agent/` | v0.6: loop, host, context blocks, providers, heavy-only agent, hosted adapters, benchmark, trace viewer |
| `turnwise_lab/local_models.py` | Local ONNX runners (s1 classifier; Qwen constrained scoring and generation with KV/state cache) |
| `models/` | Pinned model manifest and the trained turnwise-dm head (weights are never committed) |
| `fixtures/v06_*.json` | Development set, independent held-out set, decision training data |
| `reports/v06/` | Recorded traces, summary, latency repeats |
| `turnwise_lab/arena.py`, `world.py`, `explorer.py` | v0.5 outcome-scored routing experiment (historical) |
| `turnwise_lab/core.py`, `runtime.py`, `benchmark.py` | v0.4 planner contract, `LocalHarness`, route-label benchmark |

## v0.5 (historical): outcome-scored routing without a model

46 synthetic incident-investigation turns in 10 multi-turn sessions were replayed through seven routing designs. Every tool and workflow call really ran (local Python over synthetic data, through the same permission harness). Turns are labelled with the **facts a correct answer needs, not with a route**, so each design is scored on what it actually returned. **No model was called**: a model path counts as correct when the needed evidence was in its context or could be fetched. That assumption, and the assumption that the baseline agent always picks the right tools, both favour calling the model.

| Design | Correct* | Model calls | Silent wrong answers | Visible failures |
|---|---:|---:|---:|---:|
| Tool-calling agent on every turn (10 tools, conversation history) | 46/46 | 78 | 0 | 0 |
| Message-only router (v0.4's frozen rules) in front of the agent | 41/46 | 58 | 0 | 5 |
| **Joint router**: session state + route-aware context | 38/46 | **20** | **6** | 2 |
| Ablation: joint router without session state | 43/46 | 43 | 1 | 2 |
| Ablation: joint router with lexical-only context | 38/46 | 21 | 6 | 2 |
| v0.4's Naive Bayes chooses the path | 29/46 | 26 | 5 | 12 |
| Oracle: cheapest correct path per turn (upper bound) | 46/46 | 9 | 0 | 0 |

\*Upper bound for every design that calls a model. A *silent* wrong answer is a deterministic result whose harness receipt says `completed` but which does not contain what the question needed. *Visible* failures are false approval holds and dropped action requests.

What the experiment found:

1. **The headroom is real on this workload.** The oracle answers 37 of 46 turns (80%) with no model call, while the always-agent makes 78 calls. The workload was written to be lookup-heavy, so [per-family results](reports/arena.md#by-turn-family-correct--turns-model-calls) are reported for reweighting to your own traffic.
2. **State is the coupling that matters, and it cuts both ways.**
   - With session state, the router resolved 7 of 8 follow-ups ("And for search?", "Do the same for checkout") with no model call. Both message-only routers resolved 0 of 8.
   - The same state added 5 silent wrong answers. Four came from one heuristic: a short turn that matches no tool reuses the previous one. The fifth is a cascade: "the service that got reindexed" was resolved to the wrong service, so the next turn, "Who approved that change?", answered about that wrong service too.
   - At the margin, state saved 23 model calls and cost 5 silent misses.
3. **"Completed" is not "correct".** All 6 silent misses have a harness receipt status of `completed`. Cost, latency and the receipt do not flag them; only checking the outcome does.
4. **Message-only rules fail loudly, state-aware routing fails silently.** All 5 of v0.4's failures were visible false holds. So the pre-registered H4 is false as stated: not every design that saves model calls produces a silent failure.
5. **Route-aware context selection did not work (H3 falsified).** Feeding tool output into retrieval did find the runbook for "why is it so sluggish?", whose words share nothing with that runbook. But JSON field names in the tool output (`p95_after_ms`, `matches_baseline`) pulled the wrong runbooks into the query for 3 other turns. Budget was not the cause: at 4× the default budget, only 4 of the 8 evidence packets were complete.
6. **Safety lives in the harness, not in the router.**
   - A compromised router forged approved plans 18 times; 0 executed. A positive control confirms that the write ledger records a write when a fully authorised host allows one.
   - v0.4's rules missed 4 of the 6 action requests ("Page them.", "Make the previous checkout build live again."), and the harness held all 4. The same rules blocked 5 harmless requests, such as "What changed in the last checkout deploy?" and "Draft the status-page update, but don't post it."
   - **Dropped action intents are a separate failure:** the joint router also lost two requests without reaching an explicit approval step: `S2.6` ("Could you also page the checkout on-call?") and `S6.4` ("Revoke the load-test rate limit on auth."). No write executed, but the request was not correctly held or fulfilled. Zero unauthorized writes is not the same as correctly handling every action. The complete per-case audit is in [the v0.5 report](reports/arena.md#every-failure).
7. **The exchange rate is the decision.** The joint router saves about 7 model calls per extra failure; without state, about 12. If one visible failure costs as much as 3 model calls, the joint router only beats the always-agent while one silent wrong answer costs less than 8.7 model calls. Without state, that threshold rises to 29. The explorer lets you set both weights.

Two smaller measured facts: tool schemas make up 72% of the always-agent's input characters, and the median turn goes from 2 sequential model calls to 0 under the joint router.

The outcome-scored offline experiment is complete; the [evaluation plan](docs/evaluation-plan.md) and [candidate v0.6 quality/efficiency protocol](docs/quality-constrained-efficiency-v06.md) separate that exploratory result from the future independently authored, **actually executed** heavy-only vs hybrid-model comparison. The [v0.5 preregistration](docs/preregistration-v0.5.md) remains unchanged.

### Reproduce v0.5

```bash
python -m unittest discover -s tests
python -m turnwise_lab.arena            # writes reports/arena.json and reports/arena.md
python -m turnwise_lab.explorer         # rebuilds demo/index.html from the report
```

CI regenerates every committed report and page and fails if anything differs by a single byte. `python -m turnwise_lab.arena --timing` also prints local routing overhead: tens of microseconds, which is meaningless next to any model call and therefore not committed.

### How the experiment works

```text
turn + session state ──► router ──► direct (verified host fact)
                                  ├─► deterministic: read tools / flows ─┐
                                  ├─► grounded: prefetch evidence + 1 model call (context packet measured)
                                  ├─► agentic: model with all tools + history (tool rounds counted)
                                  └─► hold (approval)                     │
                                                     LocalHarness ◄───────┘  checks registration, metadata,
                                                                             identity, grants; writes never run
outcome check: did what came back contain every needed fact?  →  resolved / ready / silent miss / false hold / …
```

- **World** ([`world.py`](turnwise_lab/world.py)): 4 services, 7 read tools and flows, 3 side-effecting actions whose handlers record the attempt and raise, 9 documents (2 deliberate distractors) and 5 host-verified facts.
- **Sessions** ([`fixtures/sessions.json`](fixtures/sessions.json)): include follow-ups, compound questions, risky-sounding reads, paraphrased and polite writes, negations, and a reference that only reasoning can resolve. Families designed to break every design, the author's own included, are deliberate.
- **Integrity**:
  - Hypotheses were committed before any code ([`d46b085`](https://github.com/dgenio/turnwise-decision-lab/commit/d46b085)). Routers and sessions were frozen before the first scored run ([`49775f7`](https://github.com/dgenio/turnwise-decision-lab/commit/49775f7)).
  - The one post-freeze change, a scoring fix, is disclosed in the report.
  - A test proves no router can read `needs`, `family`, `mode` or `action`.
  - Another test pins the hypothesis verdicts, so a code change cannot silently flip a finding.

### Where this is weak

- **The alternative-path descriptions in the explorer are illustrative, not measured counterfactuals.** They are derived from gold-required facts and simplifying assumptions. Selecting another strategy cell shows an actual offline replay; the forced-path captions do not. No model generation is executed.

- **One author** wrote the world, the sessions, the needed-fact labels and every router. The sessions have now been seen, so any router tuned on them will overfit.
- **No model ran.** "Evidence present ⇒ correct" is an assumption. Answer quality, tokens, latency and price are not measured, and the cost weights are inputs, not results.
- **Lexical everything.** Capability matching, document retrieval and synthesis cues are deliberately simple, and are shared by all designs. A stronger matcher changes the absolute numbers. Whether it changes the state trade-off is open.
- **46 turns** are enough to show mechanisms, not to put confidence intervals on rates.
- **Model-tier routing is not evaluated.** It composes with everything here: execution routing changes *how many* calls a model router has to price.

### Earlier versions (kept, still reproducible)

- **v0.4 route-label benchmark** ([report](reports/trained-routing-synthetic.md)). Simple rules matched 38/40 authored labels and the tiny Naive Bayes matched 29/40. In hindsight it had three weaknesses: `direct` was defined by a field the rules read; route labels and rules shared an author; and label agreement is not an outcome. v0.5 replaces it as the primary evidence.
- **v0.4 execution receipts** ([page](https://dgenio.github.io/turnwise-decision-lab/local-run.html)) and the **planning-contract exhibit** with fixture decisions ([page](https://dgenio.github.io/turnwise-decision-lab/planning-contract.html)).
- The optional generation adapter (`python -m turnwise_lab.provider_cli ... --allow-remote`) sends one public synthetic request to an endpoint you choose. Never send employer, customer or confidential data. See [provider boundaries](docs/model-backend.md).

## Relation to the Weaver work

- [ContextWeaver](https://github.com/dgenio/contextweaver) is testing D1 capability snapshots. Its [controlling decision](https://github.com/dgenio/contextweaver/issues/758) parks D2/D3 routing experiments behind adoption evidence. This repo does not modify it or restart its roadmap.
- [ChainWeaver](https://github.com/dgenio/ChainWeaver) explores evidence-backed deterministic flow promotion; Turnwise does not reproduce that governance process.
- [agent-routing-eval-lab](https://github.com/dgenio/agent-routing-eval-lab) is dedicated to off-policy evaluation on logged decisions. The oracle and counterfactual columns here are a small, offline cousin of that idea, not a replacement.
- [agent-kernel](https://github.com/dgenio/agent-kernel) addresses runtime authorization enforcement; `LocalHarness` is an educational stand-in, not a security boundary.

**Name.** "Turnwise" is also used by an unrelated [arXiv paper on multi-turn LM evaluation](https://arxiv.org/abs/2603.16759) and by PyPI packages for conversation evaluation (see [comparators](docs/comparators.md#nameprior-art-collision-important-before-promotion)). This repository is not affiliated with them and should not be published to PyPI as `turnwise`.

MIT licensed. All data is synthetic and invented for this experiment.
