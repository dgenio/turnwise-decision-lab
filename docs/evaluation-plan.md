# Evaluation plan — completed v0.5 offline experiment and proposed next gate

> **v0.6 update (2026-11-18).** Parts of the next gate have now been executed, with real local inference: an independently written held-out set (n = 30), observed model invocations, a heavy-only agent baseline and component ablations. See [`preregistration-v0.6.md`](preregistration-v0.6.md) and [`reports/v06/summary.md`](../reports/v06/summary.md). Still not executed: hosted decision services, a frontier-scale heavy model, human-authored tasks and dollar costs. The v0.5 text below is unchanged.

**Status (2026-11-18):** The v0.5 **offline, authored-synthetic** arena has been executed. This document is the forward-looking evaluation plan, **not** the pre-registration for that run. The contemporaneous pre-registration is [`preregistration-v0.5.md`](preregistration-v0.5.md), the reproducible result is [`reports/arena.md`](../reports/arena.md), and the earlier v0.4 route-label exercise remains separately documented.

The v0.5 run does **not** establish generative answer quality, production success, cost or latency savings, calibrated confidence, superiority to a provider-native router, or market demand. **No model or hosted decision service was called.** Every deterministic read/flow call ran locally; all model paths were scored under explicit optimistic evidence-availability assumptions.

## What v0.5 actually established on its authored workload

- **46 turns across 10 synthetic multi-turn sessions**, seven routing designs. The same author created the world, cases, gold fact requirements and policies. The 46 cases have now been seen; no subsequent tuning on these cases can count as held-out validation.
- The assumed perfect tool-calling agent had **46/46 potentially correct outcomes and 78 counted model calls**; the session-state joint router had **38/46 potentially correct outcomes, 20 counted model calls, six silent misses and two dropped action requests**. These are **not** observed model invocations or real task outcomes.
- The joint router resolved **7/8** follow-up lookups/flows without model calls, but state reuse also propagated incorrect entity/capability selections. The context-advantage hypothesis **H3 was falsified** on the synthetic set (3/9 complete route-aware packets vs 2/9 lexical).
- The host harness prevented all **18 forged write attempts** in the local red-team and the positive control reached the write handler when fully authorised. That is a bounded property of this toy harness, not production safety assurance.
- **Two action requests were silently dropped before any approval step:** `S2.6` (page on-call) and `S6.4` (revoke rate limit). They were not executed; that does **not** make them successful holds. A host execution gate cannot authorize or reject an action that the router never proposes. Track `action_dropped` separately from `held`, `false_hold`, `silent_miss` and actual unauthorized execution.
- The explorer's *illustrative path assumptions* are simplified, gold-label-derived explanations **not executed counterfactual runs**. The seven strategy cells show actual offline replay outcomes and no model-generated answers.

This is **useful engineering evidence of mechanisms and failure modes**, not comparative product validation. Do not reframe the 46-case results as prospective evidence.

## Research question for a NEW, independently evaluated experiment

**Primary thesis (quality-constrained efficiency):** How much of an agent's reasoning cost can be eliminated while preserving **near-baseline end-to-end task success** relative to a **real, executed heavy-only tool-calling agent**?

The proposal does **not** predict higher accuracy. Equal or slightly worse accuracy may be worthwhile only if any loss falls within a **pre-registered, adequately powered non-inferiority margin**, there are no unacceptable critical failures, and measured cost and latency improve materially. The gains may come from (a) avoiding unnecessary heavy calls with deterministic actions / decision services / validated light-model argument extraction and (b) sending fewer context and tool-schema tokens to the heavy model when it is necessary. A heavy fallback should be preferred under uncertainty.

**Null hypothesis:** the heavy-only agent with modern provider-native tool search/context handling, or simple host rules plus heavy fallback, gives the best acceptable quality/efficiency trade-off; the extra joint planner is not worth maintenance, routing failures or latency.

The concrete [candidate v0.6 protocol](quality-constrained-efficiency-v06.md) is **not a pre-registration**. Quality margin, risk constraints and economic thresholds remain open decisions.

## Data and independence

- Recruit at least one **independent author/labeler** for new sessions. Aim for >=100 genuinely held-out, diverse **public or newly invented synthetic** turns, with multi-turn state, tool argument requirements, ambiguous references, partial context, actions, negation, and difficult near-neighbors. Record provenance, allowed tools, outcome evidence and review process. Do not edit the frozen v0.5 world/fixtures to improve old scores.
- Split tuning and evaluation **before** comparing policies; commit dataset and labeling protocol/hashes. Use case-family and session-level aggregation, not just a single micro-average. Report all negative cases and disagreements.
- Treat v0.5 as **development/exploratory evidence**; use new unseen tasks for headline claims. If a reviewer cannot label an outcome independently, report it as non-verifiable rather than assigning a convenient route label.
- Do not import employer/customer chat or logs into this public project. Real enterprise validation would require a separate, authorized and private data/model route.

## Comparators — accurate status

| Arm | Purpose | Status as of v0.5 |
| --- | --- | --- |
| Assumed capable tool-calling agent | Optimistic synthetic sanity reference; **not** the heavy-only benchmark | **Offline replay completed**, model never called |
| **Real heavy-only tool-calling agent** | **Primary quality baseline:** same task/tool permissions, strong heavy model handles reasoning/tool selection/arguments/synthesis | **Not run** |
| Heavy-only + native tool search / bounded context | Controls for provider-native context and schema optimization without a custom planner | **Not run** |
| Simple host policy + heavy fallback | Strong, low-complexity execution baseline | **Not run with model** |
| Decision-service routing / light arguments + heavy fallback | Tests distinct efficiency levers before combining them | **Not run** |
| Message-only simple rules and host preflight | Lower-complexity execution-path baseline | **Offline replay completed** |
| Joint route + state + route-aware context | Proposed mechanism | **Offline replay completed**, model-tier inference untested |
| Joint without state / lexical-only context | Ablations on context-state coupling | **Offline replay completed** |
| Tiny Naive Bayes path policy | Weak out-of-distribution illustration; not Jev | **Offline replay completed** |
| Oracle | Gold-aware upper bound, *not* a deployable policy | **Offline replay completed** |
| LiteLLM Auto Router / Jev | Contemporary model-router comparator | **Not run** |
| vLLM Semantic Router and provider-native tool search | Strong tool/model/context alternatives | **Not run** |
| Real model + tool-calling with answer checkers | End-to-end generation and recovery comparison | **Not run** |

Include a strong host-only/manual baseline in the next comparison. Never rely solely on the omniscient oracle or naive all-tools reference to claim a win.

## Proposed next experiment and ablations (not yet run)

1. Freeze independently authored tasks, prompts, policies, tool/schema catalogs, model and provider versions, model parameters and price schedule.
2. Use identical eligible evidence and tools across arms where supported. Preserve documented differences when native mechanisms cannot be normalized.
3. Execute the **same real heavy-only reference** first, alongside a heavy-only native-context/tool-search arm and a **simple host-rules + heavy fallback** arm. Then compare decision-model routing, validated light argument extraction, conservative heavy fallback and joint bounded context. Include context-only and no-state ablations to isolate contributions; where supported compare contemporary native routing.
4. Execute real permitted model handoffs in an **opt-in** environment; record generation quality, retries, timeouts, recovery, permission decisions and downstream outcomes. A "model had evidence" event is **not** a correct final answer.
5. Run several independent trials for stochastic models (target >=5 where affordable), report session-level uncertainty, and distinguish infrastructure failures from routing or generation failures.
6. Add **actual** forced-route replay only if it can be done without accessing gold labels at planning time; until then, keep the explorer's alternative-path descriptions explicitly illustrative.

## Metrics and gates

**Primary gate:** end-to-end **task success is non-inferior** to a measured heavy-only agent within a *pre-specified, justified margin*; report paired uncertainty, power and family/risk stratification. Absent enough evidence to establish the margin, the verdict is **inconclusive**, not PASS. No margin is approved yet.

**Primary efficiency measures (only meaningful after the quality/safety gate):** measured **total cost per attempted task** and end-to-end latency p50/p95. Report cost per successfully resolved task as a supporting metric, not as a way to hide a fall in success rate. Include classifier/decision-service/light/heavy model calls, tools, final heavy synthesis, retries, failures and abandoned attempts.

**Mechanistic measures:** actual heavy call counts and provider-reported **input tokens sent to heavy models per heavy invocation** (distinguish evidence/history, tool schemas, output tokens), plus total tokens and full price provenance. The v0.5 character counts and assumed model calls are not measured tokens or prices.

**Correctness:** task-specific answer checkers; tool/capability recall and argument/schema correctness; context Recall@budget; calibration only for genuine model probabilities; silent wrong answers; false holds; **dropped actions**; safe/appropriate refusal and escalation. An action's approval request is a separate outcome from whether any write occurred.

**Operations:** provider-reported tokens, measured p50/p95 end-to-end latency, actual model/router overhead, provider price schedule and error/retry rates. Count attempted, completed and *actually executed* model calls separately.

**Non-negotiable:** any unauthorized execution, confidential-data exposure or serious policy breach is a stop-and-review event, not a tolerable economic trade-off.

Previously discussed exploratory goals (>=20% fewer high-cost model calls and <=2 percentage points loss in task success) are **neither achieved results nor accepted gates**. They are not sufficient evidence of economically material savings or statistically defensible non-inferiority. At ~100 tasks a 2pp non-inferiority claim is generally underpowered: select a justified margin and power the held-out sample **before** the run, or keep the result inconclusive. Do not optimize escalation thresholds on the locked test set.

## Decision rules

- **GO to bounded private shadow testing** only if a real heavy-only quality baseline has been measured, the pre-registered non-inferiority and safety gates pass with adequate power, and measured cost/latency improvements beat strong simpler/native comparators by a material amount; an accountable operational owner must accept the extra complexity.
- **HOLD** if datasets are authored by the implementer, generation is assumed rather than executed, native comparators remain untested, or uncertainty is too wide.
- **SHRINK** if the only credible value is inspectable context provenance / deterministic execution controls.
- **STOP** if simpler/native options meet the same outcome quality and the joint layer costs more, or if state-driven silent errors outweigh invocation savings.

**Current decision: HOLD on product and enterprise claims; GO on a transparent public engineering exhibit and independent validation design.** Preserve the v0.5 results as frozen exploratory evidence.
