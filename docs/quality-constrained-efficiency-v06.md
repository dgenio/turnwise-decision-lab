# v0.6 candidate protocol — quality-constrained agent efficiency

**Status: DRAFT DESIGN, NOT PREREGISTERED, NOT EXECUTED (2026-11-18).**
This proposes the next experiment; it does not amend the frozen [v0.5 preregistration](preregistration-v0.5.md), fixtures, routers, or [observed offline results](../reports/arena.md). The decision on a non-inferiority margin, required cost/latency improvements, and statistical power is **open**. The independent-data gate in [issue #3](https://github.com/dgenio/turnwise-decision-lab/issues/3) comes first.

## Research thesis

**How much of an agent's reasoning cost can be eliminated while preserving near-baseline end-to-end task success?**

The aim is **not** to outperform a strong conventional heavy-model agent in accuracy. We expect the proposed architecture may be equal or slightly worse in quality; it is worth adopting **only if** any quality loss is predeclared, sufficiently small for the task/risk mix, and compensated by material improvements in cost and/or latency.

Think of this as a *constrained efficiency* problem, not "maximize router accuracy":

- **Primary quality gate:** on paired, unseen tasks, success of candidate minus success of a real **heavy-only tool-calling agent** must remain above a pre-registered non-inferiority margin `-delta`, with an uncertainty method and a sample size justified *before* the locked evaluation run.
- **Safety gate:** no unauthorized side effects, confidential disclosure or other predefined critical events. Handle **dropped action intents** separately from an explicitly held action. A low aggregate error rate never excuses a critical event.
- **Efficiency objective, conditional on both gates:** reduce **measured total cost per attempted task** and end-to-end latency (including p95), and show the Pareto frontier of quality versus cost/latency. Report cost per successfully completed task as a secondary ratio, not a substitute for the quality gate.
- **Mechanistic goals:** fewer heavy-model calls, fewer input/context/tool-schema tokens *per unavoidable heavy call*, and lower total tokens/cost including decision service, light-model, retries, tools and terminal generation.

Neither `delta` nor an economic threshold has been approved. A hypothetical 2 percentage-point margin on around 100 tasks is generally not statistically resolvable; power the study or report inconclusive results instead of claiming non-inferiority.

## Distinct mechanisms to test

1. **No model when not needed.** Host-verified answer or registered deterministic read/flow; no additional classification when a safe deterministic rule already settles the operation and its arguments.
2. **Decision service for bounded choices.** A fast, typed decision model can select a route/capability or flag uncertainty. Its calibration, latency, cost, and misrouting rate must be *measured*, not presumed.
3. **Light LLM when language-derived arguments are needed.** Only after a deterministic argument builder is insufficient; require structured output, schema validation, provenance and strict error handling. Test actual model quality; small/open-weight is not assumed adequate.
4. **Conservative heavy fallback.** Ambiguous references, low confidence, conflicting or stale state, missing evidence, invalid parameters, potentially consequential outcomes and unsupported routes go to the heavy agent rather than speculative deterministic execution. Confidence is not meaningful unless empirically calibrated.
5. **Bounded heavy context.** When heavy is necessary, provide relevant verified evidence, tool schemas, instructions and state rather than defaulting to an unfiltered full catalog/history. Measure evidence recall *and* lost qualifications; incomplete packets must expand or fall back. Context minimization alone may hurt correctness.
6. **Optional final synthesis/recovery.** Some workflows need a heavy model to formulate the final answer regardless of the route. Count that common final stage in **every** applicable arm. Test, rather than assume, that it detects earlier mistakes; a polished answer can also conceal a silent routing error.

Permissions and approval remain in the host/tool execution boundary, not in the decision model, the light LLM, or the final heavy synthesis.

## Comparator ladder (all status: NOT RUN with actual models)

| Arm | Model/route policy | What it isolates |
| --- | --- | --- |
| **A. Heavy-only reference** | One strong heavy agent owns tool selection, argument generation, multi-step reasoning and synthesis; eligible tools/context available, standard permission gates | Primary **real** quality comparator; replace v0.5's assumed-perfect model agent |
| **B. Heavy-only, optimized context** | Same heavy model, with supported native tool search/deferral and bounded context, no custom execution planner | Tests whether most savings come from context/schema handling alone |
| **C. Simple host + heavy fallback** | Deterministic, registered host rules for safe known operations; heavy for everything else | Necessary strongest low-complexity baseline |
| **D. Decision service + heavy fallback** | Bounded typed router for remaining choices; conservative fallback; same evidence and policies | Incremental value/cost of a decision model |
| **E. Light argument model + heavy fallback** | As C, but use light model for validated non-deterministic parameters | Whether lighter argument extraction helps without quality loss |
| **F. Joint bounded architecture** | Safe deterministic routes + decision service + optional light arguments + bounded context + heavy fallback/final stage | Combined hypothesis; separate component ablations if beneficial |

Additional current provider-native/router alternatives (e.g., LiteLLM/Jev, native tool search, semantic router) may be run where they support equivalent tasks. Record incompatibilities, and mark unexecuted arms `not_run`; never compare an assumed-perfect offline reference to live-model quality as if both were observed.

Do **not** assume D/E/F are superior. In the v0.5 authored synthetic world, the state-aware joint router saved simulated model calls but lost **8/46** task outcomes (six silent misses and two dropped action intents) relative to a **perfect-by-assumption** 46/46 baseline. Route-aware retrieval itself failed its pre-registered advantage test. These are design warnings, not measured inference outcomes. Preserving those failures is essential.

## Evaluation design and quality controls

1. **Independent cases first.** Acquire unseen, independently authored/labelled multi-turn synthetic or public-data tasks, spanning simple known-argument reads, variable-argument reads, follow-ups, compound requests, synthesis, missing context, adversarial near-neighbors, negated/polite writes, actions, and error-recovery cases. Distinguish task and session clusters. Never tune against the 46 seen v0.5 turns and report them as held-out.
2. **Freeze before execution.** Register task labels/checkers, corpus/provenance hashes, arm source revisions, exact model/decision-service IDs and configurations, prompts, tool catalog, budget, cache policy, prices, fallback thresholds, non-inferiority margin, serious-event definitions, analysis plan and sampling/power calculation.
3. **Paired execution.** Give all eligible arms the same starting evidence, tools, permission boundaries, and user requests; randomize trial order and repeat stochastic runs when affordable. Count total wall time across every sequential step. Keep provider-native features as documented rather than imitating them inaccurately.
4. **Score final outcomes.** Use independently checked task success, argument validity, retrieved fact fidelity, action requested/held/executed, recoveries and silent wrong answers. A model merely receiving relevant evidence is **not** a successful answer. Include correct refusals and appropriate escalation.
5. **Observe exact resource usage.** Per task and step: decision-service calls, light/heavy calls, actual input/output tokens, context/tool-schema tokens to heavy, tool invocations, retries/timeouts, provider measured/billed usage, price table, p50/p95 end-to-end latency and provider/local overhead. Mark absent measurements `unknown`, not zero or estimated results.
6. **Present the frontier.** Plot task-success difference (with paired uncertainty) against total measured cost and latency. Report family- and risk-stratified deltas, tail latency, heavy call/context savings, failures and regressions. Vary conservative escalation thresholds on development data only; validate any selected threshold on *new* held-out cases.

### Minimum task-level record (proposed)

`{task_id, session_id, family, risk_tier, arm_id, run_id, version_ids, task_success, checker_provenance, silent_wrong, action_dropped, false_hold, unauthorized_execution, escalated_to_heavy, fallback_reason, decision_calls, light_calls, heavy_calls, input_tokens_total, output_tokens_total, heavy_input_tokens, heavy_context_tokens, heavy_tool_schema_tokens, cost_total, price_provenance, latency_e2e_ms, error_or_timeout, provider_receipt_ids}`

Separate `unknown` from `0`; never log sensitive prompts or secrets to a public artifact.

## Exit criteria

- **GO to a bounded next validation stage:** both quality and safety gates pass with adequate evidence; measured economic/latency gains are material *against A and the strongest applicable B/C*, after accounting for fallback and maintenance complexity.
- **HOLD:** insufficient sample/power, missing cost receipts, assumptions standing in for live execution, or native comparators not tested.
- **SHRINK:** only host rules, provenance, safe tool execution or context optimization provide the credible gain; drop unsupported complex routing.
- **STOP:** quality below the margin, unacceptable silent misses/action drops or policy failures, or no material efficiency gain versus a simpler approach.

**Next action:** revise [issue #3](https://github.com/dgenio/turnwise-decision-lab/issues/3) implementation sequence around the independent dataset and an actual heavy-only baseline first. Finalize `delta`, acceptable serious-event risk, economic thresholds and study power with the project owner before labeling anything a pre-registration. No external API or model expense is authorized by this document.
