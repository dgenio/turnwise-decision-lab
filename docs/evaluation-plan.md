# Pre-registered decision test plan — proposed, not yet executed

Status: **blocked on independent labeled data and approved access to contemporary comparator implementations**. The small fixture replay in `reports/` is only a contract/smoke test. No statistical or economic claims can be made from it.

## Decision question

Does a bounded per-turn planner that jointly chooses no-generation / verified flow / tool / reasoning tier *and* an appropriate context set produce consequential improvement against the strongest simpler alternative?

Primary null: a simple host policy + provider-native tool discovery + existing model auto router is already adequate, so additional classification/context compilation complexity is unjustified.

## Experiment design

- At least 100 diverse **held-out** public or independently authored synthetic tasks. Record authorship, ground-truth policy, tasks, tool/source catalog IDs and version, difficulty, and domain; keep a separate tuning split. Do not tune on held-out cases.
- Start with isolated pre-routing choices and context-plan recall; then repeat the same cases end-to-end against actual running models/tools if budget and host policy permit.
- For enterprise adoption, use only approved local or vendor-cleared model/data routes. Never ingest actual corporate conversations into this public lab.
- Freeze model IDs, inference parameters, vendor API versions, classifier identity, prompt template, tool catalog and policy revision for every run. Repeat stochastic trials (target >=5 where affordable) and report uncertainty.
- Compare exactly matched tools/tasks/contexts across arms wherever possible; where provider-native systems work differently, note coverage gaps rather than removing them.

## Required comparator arms

| Arm | Question it answers | Status |
|---|---|---|
| Always capable model | Sanity floor only; never sufficient to claim advantage | Offline route-plan placeholder |
| Simple host policy | Can verified answer / known flow / lexical tool shortlist remove calls without classifier? | Implemented deterministic replay |
| LiteLLM Auto Router + Jev | Does model-tier classification alone produce the same benefit? | **Not run**, requires real service and config |
| vLLM Semantic Router / provider native | Is the whole decision/context behavior already natively available? | **Not run**, requires reproducible deployment |
| Proposed joint planner | Does path + tier + context selection add measurable benefit? | Offline contract fixture only; real Jev **not run** |

## Ablations (use the same tasks)

1. Host rules only, no classifier.
2. Classifier tier only, no per-turn context selection.
3. Classifier path + tier, but naive full permitted context.
4. Classifier path + tier + bounded context selector.
5. Same as (4) but with all irrelevant prior-turn text added to bounded summary, to quantify routing instability.
6. No host verified direct-answer bypass vs bypass (cost of decision call when no model is needed).

## Failure-cost model, selected before thresholds

- Data exposure and unauthorized side effects: **zero permitted**; any verified violation is stop and review, never balanced against cost savings.
- False exclusion of a required tool/context: measure and treat as error, with separate severity for consequential tasks.
- False positive escalation: extra classifier/model calls, tokens, and latency.
- Incorrect low-tier routing: wrong final answer or costly retry, not merely model-label disagreement.
- Context truncation: omission of citations, provenance, contraindications or caveats required for a correct answer.

## Primary and secondary gates

The exploratory thresholds of >=20% reduction in frontier-model invocations and <=2 percentage points absolute loss in end-to-end task success are **proposals**, not endorsed operating limits. Compare them against the *best real* model-only/native route, not the always-deep sanity floor. Require no verified authorization/privacy regressions. Statistical uncertainty matters: with n~100, a 2pp difference is generally too small to establish noninferiority confidently; expand n appropriately or report inconclusive.

Report per-task correctness, capability Recall@k, arguments/schema validation, context Recall@budget, answer evidence, abstention/approval behavior, classifier calibration (ECE/Brier on genuinely predicted probabilities), provider-usage tokens, *measured* end-to-end p50/p95 and actual price schedule/costs. Keep infrastructure errors and retries visible. Provider-side token/latency measurement must include the new classifier call.

## Interpretations

- **GO to a bounded, private shadow pilot:** credible incremental wins with no security or quality regression and an operational owner.
- **HOLD:** limited data, calibration instability, untested native baseline, or confidence intervals too wide.
- **SHRINK:** value limited to context provenance/pack reproducibility; feed results to future ContextWeaver D2 review only after D1 gate.
- **STOP:** host rules and native routing match or beat the joint planner after fair evaluation, or maintenance/latency overwhelms gains.

**Current decision: HOLD.** Eight trivial authored contract fixtures cannot distinguish the proposed planner from the simple host baseline; both match all authored route labels and the planner adds seven fixture classifier calls. This is useful *negative evidence about the test design* — not measured production failure.
