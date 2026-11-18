# Turnwise: route the work, not just the model

A conventional agent hands the whole control loop to a capable language model. Turnwise is a small lab that asks, step by step, what actually needs one: a verified fact, a deterministic tool, a workflow, a light model, a capable model, or a hold for human approval. It runs real experiments on a synthetic incident-response world, pre-registers them, and keeps the parts where it was wrong.

It is not a framework or a product. Every number below comes from small local models; **nothing here is evidence about a capable agent yet.**

**[Open the Decision Microscope →](https://dgenio.github.io/turnwise-decision-lab/microscope.html)** · [v0.7 report](reports/v07/summary.md) · [pre-registration](docs/preregistration-v0.7.md) · [what review found](docs/v07-self-review.md) · [how the gate works](docs/v07-exit-gate.md)

[![The Decision Microscope: one request under two controllers. On the left the agent answers a question about search with evidence about checkout only. On the right the same reply is struck through: the exit gate did not send it, named the missing evidence and ran those calls itself.](docs/img/v07-microscope-detail.jpg)](https://dgenio.github.io/turnwise-decision-lab/microscope.html#locked/L03/heavy_agent/heavy_agent_gated)

## The finding (v0.7): gate the exit, not every step

v0.6 put a trained decision model in charge of every step and compared it with an LLM agent. Its failures were not about *choosing the next step*. They were about *ending the turn*: finishing, or writing an answer, before the evidence could support it, and dropping an action when unsure ([diagnosis](docs/v07-research-assessment.md), with five of the defects [reproduced as tests](tests/test_v07_diagnosis.py)).

So v0.7 moves the check. Any controller drives the turn. Before the turn may end, the host checks the reply's kind against an **evidence contract**. A reply that attributes a cause needs a receipt for the symptom *and* a receipt for a candidate change, for the same service. If one is missing, the host names the call, runs it without asking a model, and hands the turn back.

The study runs three v0.6 controllers unchanged, each with and without that gate, plus a planner that lets the contract choose the calls. 60 locked tasks, written by an independent LLM author and not read by the implementer before the code was frozen. Real local inference, every token counted.

| Controller | Passed, no gate | Passed, with gate | Paired difference (95% CI) | Compute per task (gated) | Model tokens computed per task (gated) |
|---|---:|---:|---:|---:|---:|
| LLM agent (Qwen3.5-0.8B, native tool calling) | 27/60 | 31/60 | +6.7 pp (−1.0 to +14.1) | 13.8 s | 460 |
| v0.6 hand-written rules | 23/60 | 38/60 | +25.0 pp (+13.7 to +35.0) | 1.9 s | 49 |
| v0.6 trained decision head | 25/60 | 35/60 | +16.7 pp (+6.1 to +26.4) | 7.2 s | 835 |
| **Contract planner** (no model chooses a step; untyped requests go to the gated agent) | | **44/60** | +28.3 pp against the ungated agent (+13.0 to +41.7) | 2.8 s | 82 |

"Passed" is a frozen lexical outcome check. It is lenient on generated text and easy for host-written text, so the 20 investigations were also graded blind by two independent LLM graders (they agreed on 91 of 100 replies; the stricter grade is used):

| Investigations (20) | Judged correct | Partial | Incorrect | Major or critical problem | Passed the lexical check |
|---|---:|---:|---:|---:|---:|
| LLM agent | 1 | 6 | 13 | 14 | 2 |
| LLM agent + gate | 1 | 7 | 12 | 15 | 4 |
| v0.6 trained head | 0 | 9 | 11 | 11 | 5 |
| Contract planner | 6 | 11 | 3 | 3 | 14 |
| Contract planner, model narrates | 5 | 6 | 9 | 10 | 10 |

Read the two tables together. The planner's 14 lexical passes are 6 correct replies: the host states the right findings and a generic verdict, and often does not answer the exact question. But it is rarely wrong: none of the 16 investigations it typed was judged incorrect, and all 3 of its incorrect replies came from requests it handed to the 0.8B agent.

What the locked run says, with the pre-registered predictions it settled:

1. **Checking the exit helped every controller on the outcome check, and broke almost nothing.** Pooled, the gate fixed 31 tasks and broke 2. Replies sent while required evidence was missing fell from 44 to 15. The gain is clear for the two cheap controllers and **not distinguishable from zero for the agent**. *(G1, G2 supported.)*
   - **For the agent, the graders saw no improvement at all.** With the gate it gathered the missing evidence and then wrote the same quality of reply: 18 of 20 investigations got the same grade, and major or critical problems went from 14 to 15. Getting the evidence in front of a 0.8B model does not make it reason over it. *(A3 falsified.)*
2. **A trained per-step decision head is not needed.** Behind the gate, plain rules passed 38 tasks and the trained head 35, at 49 against 835 model tokens per task. Whatever the head learned, the gate replaces it for 6% of the tokens. *(G5 supported.)*
3. **When the contract determines the next call, nobody has to choose it.** The planner asked no model for 49 of 60 requests and passed 41 of them. It delegated 11 to the agent and passed 3. Overall: more tasks than the agent at under a quarter of its compute, and on investigations 6 replies judged correct against the agent's 1, with 3 major problems against 14. *(C1, C2, A1 supported.)*
4. **The controller still matters.** The gate did not flatten the three controllers; it reordered them. The spread grew from 4 tasks to 7. *(G4 falsified.)*
5. **The action latch is the part that failed.** A lexicon that turns "the user asked for a side effect" into an approval request halved the dropped actions, did not remove them, and once raised an approval for **the wrong service** (`L56`). A lexicon is the wrong instrument for action intent. *(G3 and S1 falsified.)*
6. **The lexicon is confidently wrong one time in five.** It typed 49 requests and got 39 right. *(C3 falsified.)*
7. **Letting the 0.8B model phrase the host's findings made things worse** (39 against 44 on the outcome check; 9 investigations judged incorrect against 3). The grounding check catches invented values. It does not catch "the rise at 11:05 came three minutes *before* the deploy at 11:02". *(C4, A2 supported.)*

No write was executed in any arm. No hosted model was called and nothing was spent.

### Verdict: SHRINK

| | Decision | Why |
|---|---|---|
| Exit-side sufficiency check and host-derived findings | **Keep, and narrow the claim** | The check got the evidence in for every controller at no model cost, and host-computed findings were the only replies the graders rarely found wrong. It did not improve what a weak model then wrote. |
| Trained per-step decision head (v0.6's centrepiece) | **Stop** | Matched by rules behind the gate at a fraction of the compute; commodity decision APIs exist if one is ever needed. |
| Synthesising write intents from a lexicon (the action latch) | **Stop in this form** | It dropped actions and raised a wrong one. Keep the host's *veto*; let a model's typed tool call be the only source of a write. |
| Lexicon claim typing | **Shrink** | Useful as a fast path, wrong 20% of the time. A single constrained model pass is the next thing to try. |
| Any claim about capable agents, cost or latency in production | **Hold** | Needs the Level C pilot below. |

## What is real, and what is not

| Real (recorded, replayable) | Not run, or not established |
|---|---|
| 480 locked turns and 224 development turns of local CPU inference on pinned models; every decision, tool call, prompt and generation recorded | A capable heavy model in any arm. "Heavy" is Qwen3.5-0.8B |
| Every tool and workflow call, through the host and `LocalHarness`, on a synthetic world | Hosted decision services, provider prices, hosted latency. `provider_cost_usd` is null |
| A freeze manifest of 31 file hashes committed before the locked run; CI checks it | A human task author or a human grader. Authors and graders are LLM agents |
| CI replays every recorded turn through the real host, gate and planner and requires identical observations, replies and scores | CI does **not** re-run model inference |
| Tool latency of microseconds | Real tool latency. The report has a sensitivity table up to 2 s per call |
| One world, four services, seven read tools | Generality of the lexicon and the tool roles. Only the two-sided rule is world-independent |

## Reproduce

```bash
python -m unittest discover -s tests            # 220 tests, no models, no network
python -m turnwise_lab.v07.bench --report       # rebuild reports/v07/summary.{json,md} from recorded traces
python -m turnwise_lab.v07.microscope           # rebuild demo/microscope.html
python -m turnwise_lab.v07.freeze --check       # the frozen files still match the manifest
```

Re-running real inference (CPU, about 3 GB of pinned weights kept outside the repository):

```bash
pip install ".[local]"
python -m scripts.fetch_models                  # pinned revisions, sha256-verified
python -m turnwise_lab.v07.bench --set dev --arms all
```

Decoding is greedy, so outputs reproduce on the same software stack; latency varies. The locked set has been run and read: it is development data from now on.

## Where this is weak

- **Scale.** A 0.8B model over-calls tools, loops and sometimes answers with no evidence. A capable agent may already satisfy the contract unprompted, in which case the gate would rarely fire. This study cannot tell.
- **The primary outcome is lexical** and favours host-written replies: 14 lexical passes were 6 correct replies. The adjudication is the fairer reading, and it is LLM-graded.
- **Host findings are right but generic.** 10 of the planner's 16 typed investigations were judged partial: correct evidence, a verdict that does not answer the question asked.
- **The lexicon.** It was hardened by an adversarial review before the freeze and still mistyped 10 of 49 requests on the locked set. A wrong type is a confident wrong reply.
- **One synthetic world, LLM authors, LLM graders, one run per arm, one CPU.**
- **Shared authorship.** The gate, the planner and the scorer's safety audits were written by the same implementer.

Everything that review found, before and after the freeze, is in [`docs/v07-self-review.md`](docs/v07-self-review.md).

## The experiment that matters next

Does a **capable** agent try to end a turn with the contract unmet often enough for an exit check to be worth having? [`docs/v07-level-c-protocol.md`](docs/v07-level-c-protocol.md) is a design ready to freeze, and the code path exists ([`v07/hosted.py`](turnwise_lab/v07/hosted.py), tested against a fake server only). The smallest valid step is a 40-task pilot with two arms, the agent with and without the gate, on new tasks.

It needs decisions only the owner can make: the model, a spending cap, the non-inferiority margin, the safety ceilings, and who writes and grades the tasks. Nothing hosted has been called.

## How this relates to existing work

Checking before answering is not new. Agent frameworks can host such a check (LangChain v1 `after_model` middleware, an OpenAI Agents SDK tripwire with a re-run, a LlamaIndex workflow step) and none ships one. The closest work found is Read-Gate, a single runtime invariant ([arXiv:2608.02011](https://arxiv.org/abs/2608.02011)), and SafeActBench's evidence ledger, which evaluates trajectories ([arXiv:2610.07753](https://arxiv.org/abs/2610.07753)). Model routers (LiteLLM, vLLM Semantic Router, RouteLLM, FrugalGPT) choose a model, not an exit. Decision models are now a commodity API (OpenAI Decisions, TypeSafe System One).

What this repository adds is narrower: a typed, two-sided evidence contract enforced by host code that calls no model, measured as a factorial across three controllers with every controller token counted. Sources and limits of that search: [`docs/v07-research-assessment.md`](docs/v07-research-assessment.md#5-prior-art-checked-2026-11-18).

## Useful contributions

1. **Run the Level C pilot** with a capable model, your own key and a spending cap.
2. **Write tasks or grade replies as a human.** The [authoring spec](docs/v07-task-authoring-spec.md) is the only document an author reads; the [rubric](docs/v06-adjudication-rubric.md) and [packet](reports/v07/adjudication/packet.md) are ready for a human grader.
3. **Add a second domain** with its own tool roles, written by someone else. If the two-sided rule and the gate work there without code changes, that is evidence of generality; if not, that is the finding.
4. **Replace the lexicon** with one constrained model pass that types the request, and measure it on new tasks.
5. **Try the gate in a framework you maintain.** [`docs/v07-exit-gate.md`](docs/v07-exit-gate.md) maps it to the hooks that exist. These are notes, not shipped adapters.

## Repository map

| Path | What it is |
|---|---|
| `turnwise_lab/v07/` | v0.7: evidence contracts, exit gate, contract planner, benchmark, adjudication, freeze, Decision Microscope, opt-in hosted-agent adapter |
| `fixtures/v07_*.json` | Development set (28) and locked set (60), independently authored |
| `reports/v07/` | Recorded traces, report, blinded adjudication packet, key and grades |
| `docs/v07-*.md`, `docs/preregistration-v0.7.md` | Assessment, mechanism, pre-registration, freeze manifest, self-review, Level C protocol |
| `turnwise_lab/agent/` | v0.6: loop, host, context blocks, controllers, heavy-only agent, hosted decision adapters, benchmark, audit |
| `turnwise_lab/local_models.py`, `models/` | Local ONNX runners; pinned model manifest and the v0.6 decision head (weights are never committed) |
| `reports/v06/`, `fixtures/v06_*` | v0.6 recorded traces, audit, adjudication and task sets (frozen) |
| `turnwise_lab/arena.py`, `world.py`, `explorer.py` | v0.5 outcome-scored routing experiment (historical) |
| `turnwise_lab/core.py`, `runtime.py`, `benchmark.py` | v0.4 planner contract, `LocalHarness`, route-label benchmark |

---

## v0.6 (historical): a learned decision model chooses every step. Exploratory and inconclusive

**[v0.6 trace viewer →](https://dgenio.github.io/turnwise-decision-lab/)** · [v0.6 report](reports/v06/summary.md) · [audit](reports/v06/audit.md) · [pre-registration](docs/preregistration-v0.6.md) · [architecture](docs/v06-architecture.md) · [models](docs/v06-models.md)

30 tasks were written by an independent agent that never saw the routers. Seven architectures ran on the same synthetic incident world, with the same tools, harness, permissions and heavy model, using real local inference (CPU). Success is checked from the outcome alone: the right kind of reply, the needed evidence actually gathered, the answer content, and no forbidden or executed write. No provider was billed, so dollar cost is null; cost is local compute time per attempted and per resolved task, plus heavy-model tokens. This is a bounded synthetic test with a 0.8B "heavy" model. A [post-hoc audit](reports/v06/audit.md), added after the owner review, re-reads the same traces. It covers full token accounting, why the escalation gate failed, a failure taxonomy and a blinded adjudication of the investigation answers.

| Architecture | Success | Silent failures | Heavy-model calls | Heavy-model tokens | p50 / p95 latency | Local compute per attempted task | per resolved task |
|---|---:|---:|---:|---:|---:|---:|---:|
| **A. Heavy-only agent**: Qwen3.5-0.8B runs the loop with native tool calling (primary baseline) | 13/30 | 12 | 125 | 174,422 | 14.2 s / 25.2 s | 13.26 s | 30.61 s |
| Deterministic host policy (rules) | 14/30 | 13 | 1 | 615 | 0.4 ms / 12.3 s | 2.4 s | 5.14 s |
| **D. Decision-driven**: turnwise-dm + argument cascade + escalation gate + dynamic prompt blocks | 16/30 | 11 | 9 | 6,105 | 1.6 s / 22.4 s | 7.01 s | 13.15 s |
| E. D with full permitted context (ablation) | 16/30 | 11 | 9 | 6,687 | 1.5 s / 17.5 s | 5.89 s | 11.04 s |
| D without the escalation gate (ablation) | 17/30 | 9 | 6 | 4,957 | 1.3 s / 21.5 s | 6.18 s | 10.9 s |
| D with LLM-only argument construction (ablation) | 13/30 | 11 | 7 | 4,489 | 1.5 s / 20.9 s | 5.71 s | 13.17 s |
| Small LLM as the controller, no trained head | 6/30 | 21 | 0 | 0 | 8.9 s / 19.8 s | 9.94 s | 49.69 s |

"Heavy-model tokens" is the pre-registered count of heavy *generation* tokens. Point 2 gives the tokens the model actually computed, which tell a different story.

What the experiment found:

1. **Success: not distinguishable.** Decision-driven control resolved 16/30 tasks, the heavy-only agent 13/30 and simple rules 14/30. The paired 95% interval for decision-driven minus heavy-only runs from −16 to +34 pp (point 9). The pre-registered rule also calls a gap of three tasks or fewer inconclusive.
2. **Faster per attempted task, but not fewer tokens computed.** Local compute per attempted task was 7.0 s for decision-driven control and 13.3 s for the heavy-only agent (−47%), and 2.4 s for rules. Median turn time was 1.6 s against 14.2 s.
   - The pre-registered figure of **96.5% fewer heavy-model tokens** (6,105 vs 174,422) counts heavy *generation* only. It includes the heavy-only agent's cache-reused prompt on every call, and it leaves out the controller's own scoring on the same 0.8B model.
   - Counting the tokens the model actually computed, decision-driven control processed about **45% more** (570 vs 394 per task).
   - The time saving is mostly decoding: the heavy-only agent generated 200 tokens per task, decision-driven control 57. See [audit §1](reports/v06/audit.md#1-full-local-compute-and-token-accounting).
3. **The two architectures fail differently, by task family.**
   - **The heavy-only agent** won investigations by the frozen lexical check (4/7). It also over-called (16 calls about services the task was not about), requested 6 side effects nobody asked for (all held by the host), and never clarified an ambiguous request.
   - **The decision-driven loop** made **0** wrong-argument calls and **0** unrequested writes, and won lookups, ambiguity and adverse cases. But it **stopped gathering evidence too early on every investigation**: it finished with raw data, or escalated before fetching the deployment history.
   - **A blinded adjudication changes the investigation picture** ([audit §4](reports/v06/audit.md#4-blinded-adjudication-of-investigations-and-action-requests); an independent LLM grader, not a human). It graded the 7 investigations and 2 action requests for the three main architectures:
     - **None of the 27 replies was judged fully correct.**
     - On investigations (correct / partial / incorrect): heavy-only 0 / 3 / 4, rules 0 / 5 / 2, decision-driven 0 / 1 / 6.
     - Two heavy-only replies that passed the frozen check were judged incorrect. One of them (H11) offered to roll back a deployment that does not exist.
     - One decision-driven reply (H10) claimed a rollback had been performed.
     - The frozen scores stay as they are, but on these tasks they overstate success.

| Task family | Heavy-only agent | Rules | Decision-driven (D) |
|---|---:|---:|---:|
| investigation | 4/7 | 3/7 | 0/7 |
| lookup | 1/6 | 3/6 | 4/6 |
| ambiguous | 0/4 | 2/4 | 3/4 |
| adverse | 1/2 | 1/2 | 2/2 |
| action request | 3/5 | 3/5 | 3/5 |
| multi turn | 1/3 | 1/3 | 2/3 |
| smalltalk general | 3/3 | 1/3 | 2/3 |

4. **"Escalate when uncertain" did not make the system safer (pre-registered P6 falsified).** Without the escalation gate the loop did *better* (17/30, 9 silent failures vs 11). The heavy model it escalated to answered with the evidence it had and never asked for more in a form the protocol recognised: the `NEED_MORE_EVIDENCE` protocol **registered 0 times in every arm**. Three replies did end with the marker after prose, which the strict parser ignores, all on action requests where an approval was the right reply ([audit §5](reports/v06/audit.md#5-scorer-and-protocol-provenance-checks)). The heavy model answered despite missing evidence 4 times in D and 6 times in the heavy-only agent. Escalation is only conservative if the target can notice what is missing; at this scale it could not. The [audit](reports/v06/audit.md#2-why-the-conservative-escalation-gate-did-not-help) shows why the gate cannot fix this. 11 of D's 14 failures were *confident*: the probability at the decisive step was at or above the gate. Where the gate did fire on two action requests, it handed the turn to a text-only generator, and both actions were dropped. That is a design defect, not a threshold to tune.
5. **Deterministic arguments matter.** Constructing arguments only with LLMs cost 3 tasks, added 3 wrong-argument calls, and doubled false clarifications (6 vs 3).
6. **Dynamic prompt-block selection did not pay here.** Success was identical with full permitted context. Dynamic selection saved only 11% of generation prompt tokens. It added 1.15 s per task of context-selection questions and was slower: p95 22.4 vs 17.5 s, and 13.15 vs 11.04 s per resolved task.
7. **A small LLM is not a controller on its own** (6/30, 21 silent failures). What made the same model usable was a tiny trained head over its scores plus typed observation features from the host.
8. **No write executed in any arm.** That is not the same as handling every action correctly: each arm dropped one or two action requests.
9. **As a non-inferiority question, the result is inconclusive.** This reading follows the project's [quality-constrained efficiency protocol](docs/quality-constrained-efficiency-v06.md), which was added after v0.6 was frozen. That protocol asks whether a cheaper architecture is *no worse* than the heavy-only agent within a margin agreed in advance; only then does cost count.
   - No margin has been agreed, so no arm passes the quality gate.
   - On the 30 paired tasks, D's success minus A's is +10 pp. The 95% interval runs from −16 to +34 pp (Newcombe paired score interval; D won 10 tasks A lost and lost 7 that A won). Non-inferiority could only be claimed for a margin wider than 16 pp. Rules would need 21 pp, and D without the gate 12 pp.
   - If a margin of that size were acceptable, the efficiency case is clear. Local compute per *attempted* task was 13.3 s for A, 7.0 s for D and 2.4 s for rules. Each heavy call took 1,347 input tokens for A, 1,129 of them its system prompt and tool schemas; D's heavy calls took 521, 149 of them its tool catalogue.
   - Details are in the [quality-constrained view](reports/v06/summary.md#quality-constrained-efficiency-view-added-after-the-run). It also maps the protocol's arms A–F onto what v0.6 ran; protocol arm B (native tool search) was not run.
10. **Confounds that limit any architectural conclusion:**
    - The "heavy" model is a 0.8B model, not a capable agent.
    - The decision head was trained on 614 project-specific synthetic states, while the heavy-only agent was not trained for this world. Architecture and training are therefore confounded.
    - The held-out author was an LLM agent that shared the world and tool assumptions.

**Bottom line: exploratory and inconclusive.**
- **Where it did better.** At this scale, decision-driven control was faster per attempted task than letting a 0.8B LLM run the loop. It made no wrong-argument calls and attempted no unrequested writes.
- **Where it did not:**
  - it did not compute fewer tokens;
  - it lost every multi-step investigation;
  - its escalation path dropped two action requests;
  - a deterministic host policy came within two tasks of its success with about a third of its compute.
- **What does not follow:** no claim about capable heavy agents, provider cost or reliability, and no non-inferiority (no margin was agreed).

The [next-gate proposal](docs/v07-gate-proposal.md) lists what would settle the question: new tasks, a capable heavy model in every arm, an escalation path that keeps tool access, and a margin and sample size fixed in advance.

All 9 pre-registered predictions, every failure and all component ablations are in [the report](reports/v06/summary.md).


### How one v0.6 turn runs

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

### What was real in v0.6, and what was not

| Real (observed and recorded) | Not run, or not real |
|---|---|
| Every decision: local inference of turnwise-dm, s1-llm-auto-router and Qwen3.5-0.8B on CPU | OpenAI Decisions and Jev / System One: adapters and fake-server tests only (no credentials, no approved spend) |
| Every tool and workflow call, through the host and `LocalHarness`, against a synthetic world | Frontier models: "heavy" is Qwen3.5-0.8B, the strongest reasoner within the ~4 GB budget |
| Every generation, by Qwen2.5-0.5B (light) and Qwen3.5-0.8B (heavy, and the heavy-only agent) | Dollar costs (nothing was billed) and hosted latency |
| Token counts from each model's tokenizer; latency measured on the CPU named in each trace | Answer quality beyond lexical outcome checks |

The public page **replays** recorded traces and says when and where they were recorded. CI re-executes the host side of every recorded trace: it feeds back the recorded decisions and generations, and checks that every tool observation, outcome and score reproduces exactly.

### Reproduce v0.6

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

### Where v0.6 is weak

- **Scale.** The heavy model is 0.8B parameters and every conclusion holds at this scale only. A frontier heavy model would very likely raise the heavy-only agent's success; whether the gap closes, widens or reverses is unknown.
- **Authorship.** The 30 held-out tasks were written by an independent LLM agent that never saw the routers. The development set, the world, the tools and the procedures that labelled turnwise-dm's training data were all written by the project author.
- **Lexical outcome checks.** They catch missing evidence, wrong outcome types and wrong content, but accept some poor answers.
- **n = 30.** Differences of three tasks or fewer are treated as inconclusive.
- **Untested components.** Tool-schema savings are not isolated as a separate arm, and hosted decision services were not run.

## v0.5 (historical): outcome-scored routing without a model

**[Explore every v0.5 turn under every design →](https://dgenio.github.io/turnwise-decision-lab/v05-explorer.html)** · [Full report](reports/arena.md) · [Pre-registration](docs/preregistration-v0.5.md)

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
python -m turnwise_lab.explorer         # rebuilds demo/v05-explorer.html from the report
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
