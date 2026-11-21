# The research object: per-step decision-controlled agent execution

**Status:** architectural hypothesis and experimental design, not a validated optimization, novel algorithm, production agent or performance claim. **Scope:** a policy *inside* an existing agent's execution loop. First articulated as the core research question in [#28](https://github.com/dgenio/turnwise-decision-lab/issues/28); measurement gates live in [#9](https://github.com/dgenio/turnwise-decision-lab/issues/9).

> **2026-11-19 note.** An offline implementation of this contract now exists on `main` in [`examples/architecture/`](../examples/architecture/README.md) (OpenAI Agents SDK and LlamaIndex, simulated model). It differs from the pseudocode below in two documented ways: it has no `ABSTAIN` operation (budget exhaustion and `HOLD`/`CLARIFY` stop visibly instead), and its `CALL_HEAVY` is a single tool-less model call returning a typed outcome, with tool-capable native continuation available only as the separate `HANDOFF_AGENT` contrast. The evidence boundaries below are dated and unchanged.

> **2026-11-21 note.** The burden of proof is inverted from this date: the shielded native agent (arm S) is the primary candidate and per-step control is the challenger. See [the dated section below](#2026-11-21-the-burden-of-proof-is-inverted). Everything else on this page is unchanged.

## The question

A model router usually answers: **which generative model should handle this request?**

Turnwise asks a different question at **each observation boundary**: **what operation must happen next, if any?**

A small typed decision model could propose one of:

- **DIRECT**: return a *host-verified*, complete and fresh answer; otherwise prohibited.
- **CALL_TOOL**: read a narrowly scoped observation using an existing registered tool.
- **CALL_WORKFLOW**: run an existing deterministic multi-step workflow.
- **CALL_LIGHT / CALL_HEAVY**: execute a generation or reasoning step with a selected model *and* a host-validated context packet. Heavy fallback must retain its native tool-calling and approval capabilities.
- **CLARIFY / HOLD / ABSTAIN**: ask for missing referents, preserve pending approval intents, or stop visibly when evidence or permissions are insufficient.

The policy runs again after each tool/workflow/model observation, **not just once at the beginning of the user message**. Calling a strong LLM is an operation of the system, not the default controller of every operation. The host—not the policy/model—owns identity, permissions, argument validation, side effects, evidence sufficiency, execution and final action status.

A candidate provider can be Jev/System One, an inexpensive learned head, a small LLM, or simple deterministic rules. **Jev is an implementation candidate, not a dependency, unique invention, or benchmark result.** The reason to experiment is the marginal value of a cheap *policy* relative to available alternatives.

## Execution contract, expressed as pseudocode

```text
state = host.initialize(request, conversation, permissions, budgets)
while host.has_budget(state):
    proposal = policy.propose_next(state.compact_trusted_snapshot())
    decision = host.validate(proposal, state)  # not a policy self-check
    if decision is invalid:
        state = host.record_rejection(state, decision)
        continue_or_abstain_with_bound()

    if decision is DIRECT or FINISH:
        return host.finish_only_if_answer_and_evidence_are_sufficient(state)
    if decision is CLARIFY, HOLD or ABSTAIN:
        return host.finish_with_explicit_state_and_pending_intents(state)
    if decision is CALL_TOOL or CALL_WORKFLOW:
        observation = host.execute_registered_read_or_hold_write(decision)
    if decision is CALL_LIGHT or CALL_HEAVY:
        context = host.assemble_required_and_permitted_context(decision, state)
        observation = execute_generation_or_capability_preserving_agent(context)
    state = host.record_typed_observation_and_cost(state, observation)

return host.abstain_with_reason_and_pending_intents()
```

This is the **candidate contract**, not a description of a shipped adapter. The v0.6 experimental branch does not yet meet all its invariants; see [#11](https://github.com/dgenio/turnwise-decision-lab/issues/11), [#12](https://github.com/dgenio/turnwise-decision-lab/issues/12), [#13](https://github.com/dgenio/turnwise-decision-lab/issues/13) and [#20](https://github.com/dgenio/turnwise-decision-lab/issues/20). A policy may express uncertainty, but a high confidence score cannot prove that a task has been completed.

## Illustrative single-turn investigation (not a benchmark trace)

**Request:** “Could the latest checkout deployment explain the increase in errors?”

1. A decision policy proposes **CALL_TOOL: get_error_metrics(checkout)**. The host validates the principal, scope and arguments and returns a typed error-rate observation.
2. The new observation is insufficient to conclude causality. The policy proposes **CALL_TOOL: get_deployment_history(checkout)**.
3. The host reports a nearby deployment. The policy may request **CALL_TOOL: get_config_diff(checkout)** or a reviewed deterministic diagnostic workflow. A plausible timestamp is **not** causal proof.
4. The policy now proposes **CALL_HEAVY** with a **tool-capable** agent and the *minimal sufficient, permitted, provenance-tracked* evidence. The heavy model investigates remaining hypotheses and explains uncertainty. If it needs further tools, its ability to call them must remain intact.
5. The host checks action receipts, pending intents, and final-answer status; it cannot present an unexecuted rollback or incomplete investigation as completed.

No timing, quality, invocation count, cost saving or success is claimed by this illustrative sequence. The experiment must measure what actually runs.

## Distinguish the competing mechanisms

| Mechanism | Where the next decision comes from | What the experiment must isolate |
| --- | --- | --- |
| **Entry-point model routing** | Router chooses a model before a turn or request | Tier-selection benefit alone; it need not replace the agent's inner controller |
| **ReAct / native tool-calling** | A capable generative LLM repeatedly decides whether and which tools to call | End-to-end quality and true cost of generative control at every step |
| **Host rules / native graph conditions** | Prewritten deterministic checks and framework graph edges | Whether a learned/decision-service policy adds any value beyond low-cost explicit rules |
| **Tool search / context and schema pruning** | Tool selection, deferred schema loading, retrieval or prompt selection | Evidence availability and context tokens, independently of execution-path decisions |
| **Turnwise hypothesis** | A typed (possibly learned) policy proposes the **next operation** after every observation | Quality-constrained marginal value of replacing repeated generative control, including all policy overhead |

These mechanisms can coexist. Native frameworks already provide routing, loops, middleware, tool approvals and, in many cases, selective context/tool exposure. **The existence of a loop or a conditional edge is not a novelty claim.** See [comparators](comparators.md), [AAE candidate pattern](adaptive-agent-execution-pattern.md) and [framework integration](framework-integration-roadmap.md).

## Scientific null, ablations and kill criteria

**Null hypothesis:** deterministic host policy plus the same *capable tool-calling heavy agent*, or a provider/native optimized agent, matches or beats the proposed decision-controlled policy at equal task quality and safety, once **all** decision, retrieval, tool, generation, caching, latency and maintenance overhead is included.

Run the same independently authored tasks and multi-turn sessions with:

1. **Heavy-only**: capable native tool-calling agent, actual calls, same host privileges and evidence sources.
2. **Native-optimized heavy**: same model with provider-native tool/context-search optimizations.
3. **Simple hybrid**: host rules + the same capable heavy tool-calling fallback.
4. **Decision-controlled**: per-step learned/decision-service policy + the **same** capable heavy fallback; separate ablations for model-tier choice, deterministic arguments, context choice and tool schema pruning.

**Primary unit of correctness:** completed task and multi-turn session, independently assessed against evidence and requested action intent—not route-label match or mere presence of relevant facts in a prompt. Instrument *each step* to explain causes of quality, safety, cost and latency differences. Report critical/silent errors separately from visible abstentions and approval holds.

Predefine an acceptable paired non-inferiority margin, severity thresholds, study power, minimum *net* savings and p95 guardrail **before** an independent prospective run. Count policy scoring, repeated decisions, context selection, tool calls, retrieval, retries, cache warmup and all model inference. Allow **SHRINK** (rules suffice), **STOP** (unsafe/uncompetitive), **HOLD** (inconclusive) and **GO** (quality and economics pass). Scientific comparison ownership is [#9](https://github.com/dgenio/turnwise-decision-lab/issues/9); fairness is [#25](https://github.com/dgenio/turnwise-decision-lab/issues/25).

The result can falsify the idea. **If the controller is not incrementally better than simple host rules or native framework functionality, do not keep adding features.**

## 2026-11-21: the burden of proof is inverted

Recorded under [#88](https://github.com/dgenio/turnwise-decision-lab/issues/88). This section adds to the page; it rewrites nothing above. The 2026-11-19 selection of Turnwise Core as the architecture to demonstrate and falsify stands as a record of what was decided then.

**What changes.** The "simple hybrid" of the list above (host rules + the same capable heavy tool-calling agent) is now executable on `main` as **arm S, the shielded native agent**: host rules before the agent, the unmodified agent loop, `IncidentHost.execute` on every call, and a host gate on the finished answer ([what it is](../examples/architecture/README.md#arm-s-the-shielded-native-agent-a-null-not-turnwise-core)). From this date **arm S is the primary candidate, and per-step control (Turnwise Core) is the challenger that has to beat it.** Turnwise Core's definition and invariants do not change.

**Why.** Each reason is a pointer, not a new claim:

- The 2026-11-19 selection was a decision about fidelity to the idea, not about evidence.
- In v0.5 the session-state router silently dropped two action requests before any approval step ([evaluation plan](evaluation-plan.md), [arena report](../reports/arena.md)). That failure exists only when the simple component chooses the operations.
- Offline, with the simulated model, arm S reproduces Turnwise Core's answer, model calls and reads on the showcase; the difference from the conventional agent comes from the host reading what its own contract already requires.
- A count of model calls cannot carry a cost claim, and on the showcase Turnwise Core is not cheaper than a batched native agent or than arm S under any billing assumption tried ([cache-aware accounting](cost-accounting-2026-11-21.md); simulated, structural).
- On recorded trajectories, host rules keyed on the previous observation removed 0.0% of estimated cost in every domain except τ-bench retail (0.3%): τ-bench, τ²-bench and a coding set ([Stage 0](../research/stage0_headroom/RESULTS.md), [amendment 1](../research/stage0_headroom/RESULTS-AMENDMENT-1.md); hindsight ceilings on estimated tokens).
- The external sources (Simplex, shielding, supervisory control, SABER, AI Control and the counter-evidence) are in [#88](https://github.com/dgenio/turnwise-decision-lab/issues/88) and the [research audit](research-audit-2026-11-21/README.md).

**Where per-step control could still win.** Written down now, so it cannot be rescued after the fact:

1. **Policy-adherence dialogue tasks**, where a native agent must follow a domain policy over many turns.
2. **Clarification timing**, where asking early matters and a controller that sees the step index could ask inside the useful window.
3. **Tasks answerable with no model call.** Stage 0 found almost no such headroom for position-keyed rules on τ-bench, τ²-bench or its coding set, so this family starts with evidence against it on those benchmarks.

**Kill rule**, for the comparison run under [#9](https://github.com/dgenio/turnwise-decision-lab/issues/9) with the same model, tools, host and budgets. The margins are the ones #9 fixes before the run.

| Outcome | Condition |
|---|---|
| **Retire per-step control as the canonical architecture** and keep it as a documented negative result | S is non-inferior to Core on task success and on critical failures, and S's billed cost is not higher |
| **Keep Core for a named family only** | Core beats S there by the pre-declared margin and loses or ties elsewhere |
| **Keep Core as primary** | Core is non-inferior to S on success and safety and at least 15% cheaper in billed cost, or strictly safer at equal cost |
| **Inconclusive** | The run is underpowered. No architecture claim either way |

**What this note does not say.** No comparison has been run. Arm S is **demonstrated with simulated inference** only; that it matches Turnwise Core with a real model is **not tested**. What arm S gives up is a per-step choice of light or heavy model and control over what the model sees at each step. Arm S appears next to A and Core in every comparison table from here on.

## Evidence boundaries as of 18 November 2026

- **v0.5, on `main`:** 46 *authored synthetic* turns. Deterministic handlers executed; no LLM or decision service inference. A no-model upper bound exists, but route-aware context failed and state reuse caused silent wrong answers. This is not a strong-agent comparison.
- **v0.6, open [PR #6](https://github.com/dgenio/turnwise-decision-lab/pull/6):** real local decision inference, but a 0.8B “heavy” reference, 30 synthetic held-out tasks, 0/7 investigation outcomes for decision-driven control under the frozen scorer, confident silent misses, capability-dropping fallback and incomplete cost/accounting isolation. It is **exploratory, scientifically HOLD, not a validated optimization**. Keep original scores and failures immutable.
- **No demonstrated Jev-vs-strong-agent result, scientific non-inferiority, production readiness, vendor-neutral integration advantage or total provider-cost saving.** An isolated tool/classification score cannot establish end-to-end task quality.

## Integration stance

Prefer one small *opt-in* policy seam within an existing agent framework (first candidate: LangGraph), preserving the framework's native tools, handoffs, approvals and observability. Do not build a new orchestrator, assume a missing framework extension point, or raise issues across multiple upstream communities without actual, maintainer-relevant evidence. See [#21](https://github.com/dgenio/turnwise-decision-lab/issues/21).
