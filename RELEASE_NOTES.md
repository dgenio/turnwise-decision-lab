# Turnwise Decision Lab: v0.7 (2026-11-18)

**Gate the exit, not every step.** A host-side exit gate with typed evidence contracts, measured around three controllers on a locked task set.

Stacked on v0.6 (PR #6), which it does not change: v0.6's traces, labels, scores and pre-registration are untouched and still reproduce.

## Adds

- `turnwise_lab/v07/`: evidence contracts and host-derived facts (`evidence.py`), the exit gate (`gate.py`: sufficiency, action latch, veto, grounding), gate wrappers for the three v0.6 controllers and a contract planner (`controllers.py`), a paired benchmark with a full cost ledger (`bench.py`), blinded two-grader adjudication tooling, a freeze manifest, and an opt-in hosted-agent adapter (`hosted.py`) that has only ever talked to a local fake server.
- Five new world variants (a deploy that lands after the error rise, two deploys, a second failing service, drift without a deploy, a flaky deploy log).
- Two independently authored task sets: 28 development tasks and 60 locked tasks the implementer did not read before the freeze.
- The **Decision Microscope** (`demo/microscope.html`): every task under every controller, step by step, replayed from recorded traces.
- `tests/test_v07_diagnosis.py`: five v0.6 defects reproduced against the frozen v0.6 code.

## Results (locked set, n = 60, real local inference; see `reports/v07/summary.md`)

**Scale: the "heavy" model is Qwen3.5-0.8B. Nothing here is evidence about a capable agent.**

| Controller | Without gate | With gate | Paired difference (95% CI) |
|---|---:|---:|---:|
| Heavy-only agent | 27 | 31 | +6.7 pp (−1.0 to +14.1) |
| v0.6 rules | 23 | 38 | +25.0 pp (+13.7 to +35.0) |
| v0.6 learned head | 25 | 35 | +16.7 pp (+6.1 to +26.4) |

- **Contract planner:** 44/60 at 2.8 s and 82 model tokens per task, against the agent's 27/60 at 12.3 s and 396. The outcome check is lexical and favours host-written replies.
- **Blinded adjudication of the 20 investigations** (two independent LLM graders, 91 of 100 in agreement, stricter grade used; correct / partial / incorrect): agent 1 / 6 / 13, agent with gate 1 / 7 / 12, trained head 0 / 9 / 11, planner 6 / 11 / 3, planner with model narration 5 / 6 / 9. The planner's 14 lexical passes are 6 correct replies. None of the 16 investigations it typed was judged incorrect. **The gate did not improve what the agent wrote** (A3 falsified).
- **A learned per-step head adds nothing behind the gate:** gated rules 38 against gated head 35, at 49 against 835 tokens per task.
- **Ten of fifteen pre-registered predictions supported, five falsified** (twelve computed from traces, three from the adjudication). Falsified: the action latch (it halved dropped actions but did not remove them, and once raised an approval for the wrong target), "the controller matters less behind the gate" (the spread grew), the lexicon's typing accuracy (80%, under the 85% threshold), and "the planner has the fewest serious failures" (7 against gated rules' 5), and "the gated agent has no more major problems than the ungated one" (15 against 14).
- **Safety:** no write executed in any arm.
- **Not run:** any capable heavy model, any hosted decision service, any human grader.

## Verdict for the mechanism

**SHRINK.** Keep the exit-side sufficiency check and host-derived findings, with the narrower claim that they get the right evidence in and are rarely wrong, not that they make a weak model's reply better. Stop investing in the trained per-step decision head. Do not synthesise write intents from a lexicon; let a model's typed tool call be the only source of a write and keep the host's veto. Hold every claim about capable agents until the Level C pilot (`docs/v07-level-c-protocol.md`), which needs owner approval.

---

# Turnwise Decision Lab: v0.6 (2026-11-18)

**Decision-driven agent control, measured against a heavy-only LLM agent with real local inference.**

## Adds

- `turnwise_lab/agent/`: a bounded per-turn loop (decide, validate, execute, observe, decide again), host policy, prompt-block registry and assembler, argument cascade, escalation gate, verification protocol, and full step traces.
- `turnwise-dm`: a trained decision head over one cached Qwen3.5-0.8B scoring pass, s1-llm-auto-router heads and typed state. Synthetic template-held-out validation accuracy: 0.911.
- A heavy-only agent baseline using native tool calling, plus opt-in OpenAI Decisions and System One (Jev) adapters with spending caps. The adapters were tested against fake servers only; they are not run.
- Local inference with no PyTorch: pinned, sha256-verified ONNX models (about 3 GB, never committed).
- An independent 30-task held-out set, pre-registered (`docs/preregistration-v0.6.md`) before any run.
- A trace viewer (`demo/index.html`) that replays recorded inference. The v0.5 explorer moved to `demo/v05-explorer.html`.

## Results (held-out, n = 30; see `reports/v06/summary.md`)

**Status: exploratory and inconclusive.** This is a bounded synthetic test with a 0.8B "heavy" model. Architecture and training are confounded: the decision head was trained on synthetic states from this world.

Decision-driven control vs the heavy-only agent:

- **Success:** 16 vs 13, with rules at 14. Inconclusive by the pre-registered rule.
- **Cost:** 47% less local compute per attempted task (7.0 s vs 13.3 s), and p50 1.6 s vs 14.2 s. The pre-registered "96.5% fewer heavy-model tokens" counts heavy generation only, including the heavy-only agent's cache-reused prompt. Counting every token the 0.8B model actually computed, including the controller's own scoring, decision-driven control processed about 45% *more* (`reports/v06/audit.md`).
- **By task family:** the decision-driven loop lost every investigation; the heavy-only agent lost lookups and ambiguous requests.
- **Blinded adjudication** (post hoc; independent LLM grader) of the 7 investigations and 2 action requests, for heavy-only, rules and decision-driven: none of the 27 replies was fully correct. The frozen lexical check passed two heavy-only replies that the facts contradict.
- **Escalation:** the conservative gate did not help (P6 falsified), and the verification protocol never registered a request. Three heavy-model replies did end with `NEED_MORE_EVIDENCE` after prose, which the strict parser ignores. All three came on action requests, where an approval was the right reply. Most failures were confident, so the gate could not fire; where it did fire on two action requests, the text-only fallback dropped both actions (post-hoc audit).
- **Safety:** no write was executed in any arm.
- **Quality-constrained reading** (added after the run, per `docs/quality-constrained-efficiency-v06.md` from PR #4): inconclusive. No non-inferiority margin has been agreed. Decision-driven minus heavy-only success is +10 pp, with a paired 95% interval of −16 to +34 pp. Local compute per attempted task was 7.0 s vs 13.3 s.

---

# Turnwise Decision Lab: v0.5 (2026-11-18)

**Outcome-scored, counterfactual routing experiment. No model was called.**

## Adds

- `turnwise_lab.arena`: 46 synthetic multi-turn incident turns labelled with the facts a correct answer needs, not with routes. Seven designs: always-agent, message-only v0.4 rules, a joint state-aware router, two ablations, v0.4 Naive Bayes and an oracle. All are scored on what they returned.
- `turnwise_lab.world`: real read tools and flows over synthetic data, plus write handlers that record and refuse.
- Pre-registered hypotheses (`docs/preregistration-v0.5.md`) committed before any code. Routers and sessions were frozen before the first run, and the one post-freeze scoring fix is disclosed.
- A compromised-router red team: 18 forged writes, 0 executed, with a positive control.
- `demo/index.html`: an interactive explorer with every turn × design. Each cell shows what ran, the context packet (included, dropped, not selected), the receipt vs the outcome check, and per-path counterfactuals. A failure-cost slider sits underneath.
- CI byte-identity check on all committed evidence.

## Fixes

- `LocalHarness` discarded the plan's context selection on `llm` handoffs and re-packed with a fixed mode. It now honours `plan.context_ids`, restricted to host-supplied sources within budget.

## Results (authored synthetic data; see `reports/arena.md`)

| Design | Correct* | Model calls | Silent wrong | Visible failures |
|---|---:|---:|---:|---:|
| Always-agent | 46/46 | 78 | 0 | 0 |
| v0.4 rules (message-only) | 41/46 | 58 | 0 | 5 |
| Joint router (state + route-aware context) | 38/46 | 20 | 6 | 2 |
| Joint without state | 43/46 | 43 | 1 | 2 |
| Oracle | 46/46 | 9 | 0 | 0 |

\*Correct is an upper bound for any design that calls a model.

H1, H2, H5 and H6 were supported; **H3 (route-aware context) and H4 (every saving router fails silently) were falsified.**

---

# Turnwise Decision Lab: v0.4 (2026-11-18)

**Route the work, not just the model.**

## Adds

- Closed-world local execution for three real Python operations, two reasoning handoffs, and a denied side-effecting action in a six-turn scenario.
- Readable, reproducible JSON receipts and an interactive local execution exhibit (`demo/local-run.html`).
- A **genuinely fitted** stdlib-only Naive Bayes route classifier trained on 60 authored synthetic examples, then evaluated against 40 disjoint synthetic holdout prompts.
- Strong host-rules baseline and a host-preflight + classifier ablation, with per-case failure traces and null fields for unknown cost/quality.
- Tests of forged plans, action registration, side-effect and permission gates, exception handling, deterministic receipts and synthetic benchmarking.
- An optional, explicitly opted-in OpenAI-compatible generation adapter with a localhost fake-HTTP integration test. No hosted provider run has been performed.
- Comparison/prior-art notes, release boundaries, privacy guardrails and a CI matrix.

## Measured on hand-authored synthetic route labels

| Strategy | Route label matches | Hold misses | Classifier calls |
| --- | ---: | ---: | ---: |
| Strong simple host rules | 38/40 | 0/8 | 0 |
| Tiny trained classifier (without preflight) | 29/40 | 5/8 | 40 |
| Host preflight + classifier with rules fallback | 38/40 | 0/8 | 23 (2 accepted) |

**Not measured:** generative task success, live-model/provider routing, real latency or usage costs, enterprise privacy, independent-user demand, or model confidence calibration. The top-line result is **no demonstrated incremental advantage over simple rules**.

## Release gate

Public source + annotated synthetic results: reviewed in [PR #1](https://github.com/dgenio/turnwise-decision-lab/pull/1), merged and deployed to GitHub Pages on 2026-11-18. Product performance claims, enterprise use and ContextWeaver roadmap integration: **not ready**. The existing D1 ContextWeaver adoption gate remains unchanged.
