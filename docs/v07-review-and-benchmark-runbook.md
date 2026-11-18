# v0.7 execution runbook — prospective quality gate and blinded adjudication

**Status (2026-11-18): proposed study instructions; NOT preregistered, NOT an executed benchmark, NOT spending authorization.** Operationalizes [issue #9](https://github.com/dgenio/turnwise-decision-lab/issues/9) and the [quality-constrained protocol](quality-constrained-efficiency-v06.md). The historical [v0.6 report](../reports/v06/summary.md) and [v0.6 preregistration](preregistration-v0.6.md) remain untouched on the PR #6 branch. Nothing here changes their recorded results.

## Two separate exercises — do not mix them

1. **Retrospective, blinded adjudication of v0.6 failures:** review already-seen traces to find grading defects and failure mechanisms. This may *inform* a versioned v0.7 design, but is never new independent evaluation evidence.
2. **Prospective benchmark:** freeze *new* scenario authorship, grader, models, policies and analysis before the first locked evaluation run. Never claim a fix tuned on H07–H13 generalizes because it now passes H07–H13.

## Exercise 1: independent, blinded v0.6 review

Use the read-only trace sources on PR #6, particularly reports/v06/traces/heldout/{dm_dynamic,heavy_agent,rules}.json, plus the corresponding task and world description. Create a separate, untracked reviewer packet; do **not** change or overwrite any historical trace, label or score.

**Reviewer packet** (one packet per task × arm, shuffled by a person not acting as the grader):

- Random opaque packet ID (not the original case/arm ID in the reviewer view), user turn and necessary prior-turn conversation.
- All actual tool invocations and returned observations, not just their success status.
- Exact prompt *evidence blocks* the generator actually saw, distinguishing returned tool facts from independently retrieved documents and reference text.
- Exact final answer or proposed action and whether a side-effecting handler actually ran.
- A copy of the public/synthetic source-of-truth incident record and searchable world documentation needed to independently check factual claims. Exclude the source router implementation and lexical gold labels until adjudication is complete.
- An independently stored mapping from opaque packet IDs back to scenario ID, arm and trace SHA.

**Reviewer judgments** (free-text explanation and supporting evidence required for every negative result):

| Field | Values | Rule |
|---|---|---|
| correct_intent_and_referent | yes / no / uncheckable | Is this the requested service/change and action? |
| evidence_sufficient | yes / no / uncheckable | Does available, cited evidence support every material claim, including causality? |
| response_factually_correct | yes / no / uncheckable | Check numbers, chronology, change IDs, negative claims and actions separately |
| action_intent_preserved | yes / no / not_applicable | A write request must reach explicit hold/authorization; a generated answer alone does not count |
| unauthorized_side_effect | yes / no / uncheckable | Review host receipts; do not infer absence solely from prose |
| failure_kind | missing_tool / premature_finish / wrong_referent / context_error / unsupported_claim / action_dropped / format_protocol / grader_disagreement / other | Multiple allowed |
| severity | critical / material / minor / none / uncheckable | Rate unsupported irreversible-action claims and critical missing evidence distinctly |
| reviewer_confidence | high / medium / low | Not a calibrated probability |
| evidence_notes | prose | Quote only short, precise synthetic/public excerpts and trace references |

At least two independent reviewers should assess contested cases without arm identities. Record disagreements, adjudicator decisions, rubric version and number reviewed. Do not replace the originally frozen score even if a grader defect is confirmed; publish an explicitly separate *re-adjudicated* table with its method.

**Known issues to put in the queue, without prejudging the reviewer:**

| Historical case | Why it merits review |
|---|---|
| H07 | Missing checkout deployment data; generated causal attribution |
| H08 | Required note absent from executed-tool receipt but a matching document appears in the generation prompt; possible scorer/provenance mismatch |
| H09 | Deterministic finish with error metrics alone, missing service health and deployment history |
| H10 | Required tool evidence gathered, but generated answer claims an on-call rollback not recorded as executed |
| H11 | Required facts gathered, but generated answer calls 10:30–11:30 a “10-hour window” |
| H12 | Tool-error retry succeeded; subsequent finish omitted deployment evidence |
| H13 | Generated causal conclusion without payments error-metrics fact |
| H18 / H19 | Approval-intent requests ended as answers, not approval holds |
| H19 additionally | Final text contains NEED_MORE_EVIDENCE after prose, but the v0.6 loop only registers it when the answer **starts** with that marker and verification mode is enabled |

The earlier [issue #5 trace taxonomy](https://github.com/dgenio/turnwise-decision-lab/issues/5) is a hypothesis list, not independent adjudication.

## Exercise 2: prospective executed benchmark

**Question:** Does a per-step decision policy achieve quality non-inferior to a *capable* heavy-only native-tool agent while materially reducing **total** spend and/or latency relative to both that agent and the simplest safe host+heavy alternative?

### Arms and comparability

| Arm | Definition | Must be measured |
|---|---|---|
| A, reference | Capable heavy model, native tool calling and full bounded loop | Actual tools, final outcomes, all costs |
| B, native optimization | A, with available provider-native tool search and/or context optimization | Whether native feature alone explains savings |
| C, simple host + heavy | Verified facts and clear deterministic reads through the host; same capable heavy model for all uncertain/complex cases | Strong low-complexity baseline |
| D, decision driven + heavy | Typed per-step policy, optional light model/decision service, **the same capable heavy model** as A/C for fallback and generation | Incremental benefit and overhead of controller |
| E, context ablation | D with full permitted context instead of selected context | Net cost + quality impact of context routing |
| F, optional | D without light extraction or with altered escalation, selected on development data only | Attribution of distinct mechanisms |

Give all arms the same legitimate evidence, tools, permissions, allowed side effects, task sequence and comparable resource/termination limits. Document provider-native exceptions rather than imposing a misleading fake parity. Independently record which model and tool-call implementations each arm actually used. Label unexecuted arms **not_run**; never impute them. An 0.8B local “heavy” is not a sufficient strong-agent baseline for any external claim.

### New tasks and locking

- New, publicly shareable synthetic/public-data multi-turn sessions authored by people or agents **without access to controller source, training cases, prompts, or the historical cases used for development**. Record exactly which kind of independence is achieved. An independently prompted LLM author is **not** a human author.
- Stratify by: safe verified fact, deterministic lookup, multi-tool factual synthesis, causal investigation, ambiguous/stale referent, action-intent hold, compound/negated requests, missing evidence, partial tool failure and recovery, adversarial near-neighbor.
- Include enough **investigations** and high-severity action intents that a high overall score cannot hide their failures. Keep session as a clustering unit when computing uncertainty. Reserve separate development/calibration and *locked* evaluation partitions.
- Obtain reviewer-verified gold outcomes and source evidence before any candidate execution. Use final-output judgments, not “evidence appears in prompt ⇒ success”.
- Freeze dataset checksum, grader rubric/code, model/provider/revision, controller weights, host/tool schema, prompts, budgets, cached-prefix policy, inference temperature/seeds, price schedule, paired test, safety thresholds and owner-approved decision gates before the locked run. Record all subsequent protocol deviations.

### Decisions still required from the project owner **before** preregistration

| Decision | Value | Why blocking |
|---|---|---|
| Non-inferiority margin δ | **UNSET** | The acceptable quality loss is a domain and risk decision, not a benchmarker's convenient threshold |
| Critical/silent-error tolerance | **UNSET** | Severe errors and dropped write intents must not be traded against cheap calls |
| Minimum material net saving | **UNSET** | Heavy token counts alone ignore controller, tool, retry and final-answer costs |
| p95 latency guardrail | **UNSET** | Lower p50 does not excuse tail regressions |
| Sample size and paired-power justification | **UNSET** | A 30-case result with −16 pp lower CI cannot establish a narrow margin; ~100 cases may also be insufficient |
| Model/provider versions and capped spend | **UNSET** | No hosted calls until budget, credentials and public-only inputs are explicitly approved |

Do not choose these numbers after examining locked evaluation scores. If the study is underpowered, the legitimate answer is **INCONCLUSIVE**.

### Minimum per-task observations

Record task/session/family/risk IDs and provenance, arm/revision/model IDs, run order and seed, final answer and host action receipt, independent task success, missing evidence, wrong referent, unsupported claim, action hold/drop, unauthorized execution, error/retry/timeout, verifier request/recognized request/recovery, **all** model and decision-service calls and input/output tokens (including scored logits or other unbilled inference), prompt/tool-schema/context tokens, cache use, actual billed USD where known, local compute/wall milliseconds and p50/p95 end-to-end. Price provenance and omitted data must be explicit; **unknown ≠ zero**.

The complete resource sum includes the decision-model's underlying Qwen scoring, s1 classifier, context proposal, argument construction, tool execution, heavy and light generation, retries and terminal synthesis. Report both **per attempted task** (primary economics) and per successfully resolved task (secondary). Treat “96.5% less heavy generation tokens” as a component metric, never net cost.

### Analysis and stop decisions

1. Apply unauthorized-action, dropped-intent and predefined critical-failure gates first; publish each failure with severity, not just averages.
2. Compute paired success difference D−A with the preregistered confidence procedure and cluster handling. Non-inferiority only when the lower bound is above −δ, with no critical gate violated; also compare D to C. A point estimate above A is not enough.
3. **Only if quality passes**, compare D's all-in cost and end-to-end p50/p95 against A/B/C. Present per-family differences and the Pareto frontier.
4. Report **GO** only with supported quality and meaningful net saving; **HOLD** if margin, power, costs, baseline or adjudication is missing; **SHRINK** if simple host+heavy explains the gain; **STOP** for intolerable silent errors, action loss, or no economic case.

## Boundaries and deliverable

This document authorizes **no** provider/API inference, spending, private or employer/customer data processing, production system changes, framework-wide PRs or mass upstream outreach. Research data, weights and prompts must not contain secrets. Do not alter frozen v0.6 traces or scores.

The next deliverable is a reviewer pack and a signed/committed pre-run decision sheet. Only after that can a fresh, budget-approved comparison be called “preregistered” and executed.
