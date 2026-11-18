# Adaptive Agent Execution (AAE) — candidate pattern, v0.1

**Status:** research proposal, not an established standard or proven optimization. **Scope:** an execution policy *inside* an existing agent's step loop, not a new agent framework, external multi-agent orchestrator, or a requirement to use any particular Decision API.

## Problem and hypothesis
A conventional ReAct/native-tool-calling agent delegates repeated next-action choices to a capable LLM. Some steps are deterministic, some need lightweight inference, and some require heavy reasoning. Hypothesis: an evidence-aware, quality-constrained policy can select among these without degrading end-to-end outcomes beyond a preregistered acceptable margin, while reducing total latency/cost. Neither non-inferiority nor net savings has yet been shown.

## Contract
Input to the policy: user turn, bounded conversation/task state, permitted capabilities and tool schemas, tool observations, evidence inventory/provenance, host permissions, budgets and uncertainty signals. **Never** gold labels or hidden evaluation targets.

Policy returns one typed action:
- `CALL_TOOL(tool_id, validated_args)`: host checks registered tool, identity, authorization, argument schema and effects. Deterministic calls are permitted only when arguments and intent are unambiguous.
- `CALL_LIGHT(context_spec)`: a lower-cost model may decide or synthesize when its reliability is supported.
- `CALL_HEAVY(context_spec, reason)`: capable model with native tool calling or reasoning; default on ambiguity, unresolved references, incomplete evidence, causal questions, or policy uncertainty.
- `FINISH(answer, evidence_receipts)`: only when outcome and evidence sufficiency are verified.
- `HOLD(reason, approval_request)`: explicit authorization or clarification required; no dropped action intents.

After each observation, update bounded state and decide again **within the same user turn**. The controller may call heavy immediately, not merely as a final fallback. A final LLM call alone is *not* evidence that prior errors were caught.

## Invariants
1. Host enforces AuthN/AuthZ and side-effect approvals; a model/decision score never grants permission.
2. Preserve unresolved intents, including side-effect requests; report hold or refusal explicitly.
3. Avoid stale state propagation: uncertain references escalate; no implicit 'reuse last tool' shortcut.
4. Evidence sufficiency is checked before deterministic finish or confident causal claims.
5. Track end-to-end task success and silent errors, not just completed tool receipts.
6. Decision policy and context builder are replaceable adapters: deterministic rules, decision models/APIs, small LLMs or heavy LLMs.
7. Bound loops, retries and budgets; fail safely with an observable reason.
8. Preserve full trace: decisions, confidence/calibration where meaningful, tools, context hashes, token usage, latency and outcome checks.

## Minimal integration seam
```text
existing agent step loop
  -> collect state, permitted tools, observations, evidence
  -> policy.decide(snapshot) -> typed action
  -> host validates and executes (or invokes selected model)
  -> record observation and update state
  -> repeat until FINISH/HOLD/budget stop
```
The pattern does not replace a framework's tools, memory, tracing, approval system or model adapters. Integrations should be opt-in and reversible; the unmodified heavy-only agent remains a first-class baseline.

## Falsifiable evaluation gates
- **Quality first:** actually execute a capable heavy-only agent with native tool calling and the *same* capable model used for hybrid fallback/final generation, same tool permissions and equivalent budgets. Preregister an acceptable loss margin and confidence interval method.
- Measure per-family task success, severity-weighted silent misses, dropped intents, unauthorized side effects, approval handling, evidence sufficiency, retries and independent human/judge review.
- **Economics second:** measure all model work, including decision-model inference, token/context construction, tool costs, p50/p95 end-to-end latency and cost per successful task. Do not equate fewer heavy-generation tokens with lower total cost.
- Compare ablations: heavy-only, simple deterministic rules + heavy, decision policy + heavy, light + heavy, dynamic vs full context, state/no state, and optional Decision API.
- Separate calibration/development and prospectively authored held-out cases; never tune on held-out examples and then claim independent validation.
- Report negative results and failure traces, including investigations, follow-ups, authorization and adversarial references.

## Evidence and limitations (2026-11-18)
Existing v0.5 is an offline synthetic harness without executed model calls; its joint router scored 38/46 with six silent misses, versus an assumed 46/46 heavy-only upper bound. v0.6 recorded experiments exist but issue #5 reports 16/30 for the decision-driven arm, 11 silent failures, 0/7 investigations and no successful verification recoveries. Its 0.8B 'heavy' baseline is not a capable heavy-only comparison. These results motivate safeguards; **they do not validate the pattern**. See README, docs/quality-constrained-efficiency-v06.md and issue #5.

## Non-goals
New framework/runtime; replacing ReAct universally; external agent coordination; provider-specific lock-in; marketing claims of novelty, production readiness or measured cost savings.

## Adoption
First publish this contract and reproducible evaluation. Implement one small adapter against an existing framework and validate independently. Only then propose a tailored discussion upstream; do not mass-post identical issues. See framework-integration-roadmap.md.
