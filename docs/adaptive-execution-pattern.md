# Adaptive execution inside an agent loop (proposal v0.1)

**Status:** exploratory design, not a validated standard. **Scope:** a framework-agnostic behavioral specification, not a competing agent framework and not a dependency on any particular Decision API.

## Motivation
A conventional heavy-only agent uses a capable model to select tools, interpret results, and answer. Some steps may instead be resolved safely by host-verified facts or deterministic operations. An adaptive execution policy chooses *how to execute the next step*, not merely *which model to call*.

## Loop contract
At each step, given the current user intent, scoped session state, capabilities, permission context and prior observations, the policy returns one of:
- `DIRECT`: return a host-verified fact with provenance;
- `TOOL`: invoke a registered deterministic read or workflow with validated arguments;
- `LIGHT`: use a smaller model for bounded interpretation or argument construction;
- `HEAVY`: delegate uncertain, open-ended, ambiguous or high-risk reasoning to a capable model with native tool calling;
- `HOLD`: surface an approval/authorization requirement without executing the action;
- `DONE`: complete only after outcome verification.

After each observation, re-evaluate within the same turn. A Decision API, rules, or another policy implementation may select the route. No specific provider is mandatory.

## Required invariants
1. **Quality-first fallback:** ambiguous references, low confidence, missing evidence, failed verification and unfamiliar requests go to HEAVY or an explicit hold, never an ungrounded direct answer.
2. **Host owns safety:** policy output cannot grant permission, authorize writes, bypass approvals or forge tool metadata.
3. **Preserve action intent:** side-effect requests must reach authorized execution or explicit hold/refusal; silently dropping them is failure.
4. **Outcome verification:** tool completion is not evidence of answer correctness. Check required facts, references and action status.
5. **Scoped state:** carry only validated referents; never reuse previous entities merely because a follow-up is short.
6. **Measured context:** provide relevant evidence and tools to the model, but verify retrieval completeness; larger or smaller context is not automatically better.
7. **Observability:** log decisions, evidence, fallback causes, latency, token/cost usage and outcome, without exposing sensitive inputs.

## Non-goals
A new general-purpose agent SDK, external multi-agent orchestrator, mandatory proprietary decision service, or claim that routing improves quality.

## Integration surface
A framework adapter can implement `decide(state, capabilities, observation) -> route` and `verify(outcome, intent) -> result`, preserving the framework's existing tool registry, model invocation, state management, tracing and approval mechanisms. Deterministic operations must have explicit preconditions and typed inputs. Use bounded retries and termination safeguards.

## Evaluation gates
Compare against an **actually executed heavy-only native-tool-calling agent** on the same independently authored tasks, tools, permissions, model provider and environment. Report end-to-end task success, silent errors, missed actions, unauthorized actions, cost, p50/p95 latency, heavy calls and context tokens by task family, with uncertainty and an explicit quality non-inferiority margin chosen before evaluation. Include light-model and decision-service overhead, tool time, verification overhead and retries. Avoid optimizing on the frozen v0.5 fixtures.

The existing v0.5 study is **not** evidence of non-inferiority: it ran no models, and the joint router produced 38/46 potential successes with six silent wrong answers and two visible failures. See `docs/quality-constrained-efficiency-v06.md`.

## Adoption sequence
1. Publish a narrow spec and falsifiable acceptance criteria.
2. Run the executed baseline and hybrid experiments.
3. Build one small adapter in the most suitable existing framework.
4. Discuss results with its maintainers, refine the proposal, then approach other ecosystems. Do not post duplicate issues or claim endorsement.
