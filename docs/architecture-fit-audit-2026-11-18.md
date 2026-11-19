# Architecture-fit audit — is Turnwise implementing the owner's idea?

**Status: historical read-only audit (2026-11-18); research architecture selected 2026-11-19, scientific readiness remains HOLD**  
**Audit date:** 2026-11-18  
**Scope:** read-only examination of public GitHub source and PR descriptions; no model execution or prospective benchmark was performed.  
**Decision owner / coordination:** [architecture gate #34](https://github.com/dgenio/turnwise-decision-lab/issues/34); hypothesis [#28](https://github.com/dgenio/turnwise-decision-lab/issues/28), pending framing [PR #29](https://github.com/dgenio/turnwise-decision-lab/pull/29).

## Executive finding

**Turnwise captures part of the proposed idea, but the experimental implementations currently confound two very different control regimes.** The owner asks whether a *small, cheap decision model* can choose the next operation at each observation boundary — execute a tool, run an existing deterministic workflow, choose a light/heavy model and select context — instead of repeatedly paying a strong generative LLM to control the agent. The essential economic hypothesis is about **moving next-operation control out of the generative model**, not just choosing a model tier once per request.

The v0.6 loop re-decides after read-tool/workflow observations and supports context/model-tier decisions. However, ordinary `call_model` normally produces a **terminal final answer** (`requires_continuation` can keep it intermediate). Proposed #32 and #33 fix important safety/capability issues, but their heavy fallback **changes controller ownership**: native heavy-agent proposals become the controlling decisions for subsequent operations. This is a valid **distinct ablation**, not a direct demonstration of the owner's central mechanism.

**Research status: HOLD.** The 0.8B local “heavy” tier is not a capable-agent baseline. Historical v0.6 outcomes include 0/7 investigations for the learned arm (under the frozen scorer) and 11 silent failures. Decision scoring itself invokes a generative 0.8B scorer; the system has not demonstrated the cheap-decision-provider economics that motivated the idea. No positive claims, provider savings, causal quality improvement or production readiness follow from these experiments.

This audit is a **mechanism/architecture review**, not an argument that all existing safety fixes are pointless. Unrequested holds, lost intents, wrong referents and unsupported action claims are real defects and must remain in scope regardless of which controller is used.

## Explicit owner requirements versus current code

| Requirement | Verified status | Source and interpretation |
| --- | --- | --- |
| Decision again after each **tool** observation | **Implemented experimentally** | [v0.6 `agent/loop.py`](https://github.com/dgenio/turnwise-decision-lab/blob/06379175ff419d42d875da5d71e0ed257986ebe5/turnwise_lab/agent/loop.py): tool result appended, loop continues |
| Decision again after each **LLM** observation | **Partial / not the default** | Same loop: `requires_continuation` or special verification response can continue, but ordinary `call_model` finishes immediately |
| Decision model chooses tool/workflow/light/heavy | **Implemented experimentally** | [`agent/providers.py`](https://github.com/dgenio/turnwise-decision-lab/blob/06379175ff419d42d875da5d71e0ed257986ebe5/turnwise_lab/agent/providers.py): learned head selects from admissible operations |
| Decision model controls **the next tool after heavy model output** | **Not demonstrated in the current default execution path** | #32 heavy fallback uses `handoff_active` to replace `decider.decide` with native heavy proposals; #33 executes a nested native heavy loop until it returns |
| Model/context selection with a measurable incremental gain | **Mechanism present; value not demonstrated** | Model-tier choices and prompt blocks are implemented, but v0.6 dynamic context had no success benefit over full permitted context and introduced overhead; ablations needed |
| Cheap, purpose-built decision provider | **Not validated** | `LearnedDecider.features` uses `GenerativeChooser` Qwen 0.8B scoring plus classifier features, logistic head, and synthetic calibration. Decision calls are not free and confidence is not calibrated for this domain |
| Independent host execution/authorization | **Partly implemented; defects tracked** | Host validates registered capabilities/permissions, but approval intent, evidence sufficiency and final action truth need #11/#12/#13/#15; green CI is not a safety proof |
| No new framework/agent runtime | **Risk of scope expansion** | v0.6 contains a full synthetic loop, model prompts/parsers, host, context builder and benchmark. Useful as a test harness; avoid treating it as a framework product |
| Real strong-agent comparison and cost/quality proof | **Not run** | #9 and #25; frozen v0.6 small-model/synthetic results are inconclusive |

## The critical boundary: who owns the *next* decision?

### Research arm C — Turnwise Core (primary owner's hypothesis)

```text
user request / updated observation
            |
            v
host builds bounded trusted state + action/evidence/budget inventory
            |
            v
cheap policy proposes NEXT OPERATION
            |
            v
host validates intent, args, authority, evidence and budget
            |
     +------+------+-------------------+
     |             |                   |
 read tool      workflow          call selected LLM
     |             |               (light or heavy;
     |             |                selected context)
     |             |                   |
     |             |         typed model outcome:
     |             |         answer_candidate |
     |             |         tool_proposal |
     |             |         needs_evidence |
     |             |         error
     +------+------+-------------------+
            |
   host records observation and side-effect status
            |
       back to policy
            |
  host-verified FINISH / HOLD / CLARIFY / budget stop
```

A heavy model's proposed tool call is **not lost**, but it is **not automatically executed** and does not itself become a multi-round LLM-controller loop. It is an observation/proposal whose execution must be validated by the host. The policy then decides again. The model's *answer_candidate* is not proof of complete success; terminal sufficiency, reference identity and action statuses are host-owned.

A model could produce a useful answer candidate in one call and the host could finish if it meets independent checks; do not mandate pointless extra classifier invocations when the host already has a verified terminal condition. Thus **“per-step” means at each meaningful unresolved observation boundary**, not a requirement to pay for redundant decisions.

### Research arm D — explicit native-agent handoff (separate ablation)

```text
cheap policy -> HANDOFF_AGENT -> bounded native heavy agent/tool loop -> host
                     (controller changes until handoff ends)
```

This is a reasonable fail-safe mechanism and may win on complex tasks. But it must be labelled as a different architecture, with controller ownership and handoff cost in the trace. It **cannot be counted as proof that a cheap policy controls each next step**.

**Concrete PR distinction:**
- [PR #32](https://github.com/dgenio/turnwise-decision-lab/pull/32): native heavy proposes one primitive at a time through the *same host-owned loop*; however `handoff_active` switches the *decision source* from `decider.decide` to `heavy_fallback.propose` for subsequent steps. This preserves one loop/host, **not** continuous decision-model ownership.
- [PR #33](https://github.com/dgenio/turnwise-decision-lab/pull/33): `run_handoff` uses a distinct bounded native heavy-agent continuation with tool-calling and host validation, then terminates. It is clearly an agent handoff. Its own author documents a residual missed-action case H18.
- Both branches contain valuable regression tests; **neither should be merged as the canonical Turnwise Core merely because its CI passes.** Both are draft, and #33 has a separate observed issue with model-proposed unrequested approval holds.

## Proposed minimal step interface (contract sketch, not implemented)

```python
StepRequest = {
    "task_id": "...",
    "user_intent": "...",
    "step_index": 0,
    "trusted_state_ref": "...",
    "allowed_operations": ["DIRECT", "CALL_TOOL", "CALL_WORKFLOW", "CALL_LIGHT", "CALL_HEAVY", "CLARIFY", "HOLD", "FINISH"],
    "evidence_receipt_ids": [],
    "unresolved_action_intents": [],
    "remaining_budget": {"steps": 0, "tokens": 0, "usd": None},
}
PolicyProposal = {"operation": "CALL_HEAVY", "target": None, "context_block_ids": ["..."], "score_kind": "uncalibrated"}
StepOutcome = {
    "kind": "answer_candidate | tool_proposal | needs_evidence | observation | error",
    "source": "host | tool | workflow | light_model | heavy_model",
    "controller_owner": "decision_policy | native_heavy_agent",
    "evidence_receipt_ids": [],
    "proposed_tool_call": None,
    "action_statuses": [],
    "usage": {"decision": None, "generation": None, "tool": None, "context": None},
}
```

The sketch is **not** a new orchestration library. Future schemas must explicitly constrain nulls, validated target and argument types, source authorization, authority separation, timeouts and terminal results. Do not ask the decision service to authenticate users or infer authority. Prefer host-validated, typed data from an existing framework. A model-proposed write is never authorized solely because the relevant service was mentioned.

## Three mechanism tests before product expansion

1. **Deterministic lookup:** question → policy selects read tool → observed fact returned → host verifies sufficiency, completes without a heavy-model call. Compare against simple host rules.
2. **Model requests missing tool:** question → policy selects heavy for causal reasoning → heavy returns typed `tool_proposal(get_config_diff)` → host evaluates proposal → policy chooses permitted tool → host returns observation → policy chooses appropriate model or explicit abstain → host verifies final response. Assert *policy was called again* after model observation. This is the discriminating test missing from the normal v0.6 path.
3. **Unrequested write and explicit approval:** question about a deployment must reject model-proposed rollback; explicit rollback request must be held for human approval, not executed, with unresolved intent preserved through every model/tool boundary. Test negation, multi-turn referents and tool-output injection.

Use a **fake policy, fake model and existing host adapters** for these control-mechanism tests; they prove architecture semantics, **not** decision-model quality or economic savings. No 0.8B model, hosted service or new training is required to prove these transitions.

## Salvage / quarantine / defer decisions

| Code or PR | Recommendation | Why |
| --- | --- | --- |
| `main` v0.5 and #6 v0.6 artifacts | **Preserve as frozen historical research** | Negative findings are informative; do not silently alter results or convert them into prospective evidence |
| Host permission boundary, registered capabilities and read receipts | **Reuse after adversarial tests** | Necessary independent safety infrastructure for any arm, not Turnwise's novel contribution |
| #27 (versus #26) | **Preferred P0 evidence-gate candidate, pending review** | Better provenance/payload/freshness checking and segregated historical replay; do not merge both |
| #32 and #33 | **Quarantine as alternative D candidates**, reconcile only if D is needed | Both switch controller ownership; retain valuable tests/action receipts, do not maintain two fallback architectures |
| #31 hard prompt budget | **Review independently for reuse** | Useful host invariant, but not a fix for architecture mismatch |
| #29 framing and #30 parity preflight | **Keep focused, review independently** | Framing and scientific infrastructure support the hypothesis without expanding runtime |
| Dynamic context / training / remote API adapters | **Defer expansion** | No demonstrated value; avoid tuning on seen cases and avoid budget/data-boundary issues |
| #21 LangGraph integration | **One minimal reversible composition after contract gate** | Prefer framework primitives; do not build another agent platform or issue multiple upstream proposals |

## Prospective falsification and research sequence

First prove the control contract with offline fake outcomes. Then measure with independently authored new tasks and a genuinely capable, tool-calling heavy baseline. Four main arms: **A native heavy-only; B simple rules + same heavy; C Turnwise Core + same heavy; D optional native handoff**. Provider-native tool/context optimizations are additional comparator controls, not gifts exclusive to one arm. The policy backend must be interchangeable: rules, learned local head, Jev/decision service if accessible and permitted. **Do not assume Jev is fast or cheaper without measurements.**

Lock task/session mix, quality/safety grading, non-inferiority margin, critical-error policy, power, full cost and cache accounting *before* running. Measure per attempted task and full session: correct outcomes, critical/silent misses, intent loss, unauthorized *requests and executions* separately, all decision/model/context/retrieval/tool tokens, compute, cost and p95 latency. If B matches C at lower cost, **SHRINK**; if C fails quality/safety, **STOP**; if insufficient evidence, **HOLD**; only if quality and economics pass, **GO**. Scientific implementation remains [#9](https://github.com/dgenio/turnwise-decision-lab/issues/9), comparator parity [#25](https://github.com/dgenio/turnwise-decision-lab/issues/25).

## Immediate decisions and gates

1. **Architecture default proposed:** make **C, Turnwise Core**, the primary reference experiment; treat D as explicit handoff ablation only. This follows the owner's stated hypothesis but is **not a merged owner-approved ADR**.
2. **Do not merge #6, #26/#27 or #32/#33 by momentum.** Their safety fixes are useful, but integrate only one reconciled chain after resolving control ownership.
3. **Do not launch hosted-model benchmarks or ask the owner to choose a cost/quality margin yet.** First demonstrate the cheap-policy control loop without inventing results, then ask for those consequential budget/quality decisions.
4. **Next authorized engineering task:** an isolated, tiny, opt-in fake policy/model transition test in an existing framework or test harness, proving C's controller returns after every unresolved model output; no training, new orchestration package or change to frozen traces.
5. **Limit claims:** current repository shows interesting engineering and negative findings, not proven unique novelty, real-world cost savings or quality-preserving agent control.

**This report changes no code or historical evidence.** It is a documented architectural gate, not a new benchmark run, a security attestation, or approval to merge.

## 2026-11-19 owner decision — scope of architecture selection

The **Turnwise Core (arm C)** controller-ownership hypothesis is selected as the **primary architecture to demonstrate and falsify**, not as a successful implementation or approved production architecture. The native heavy-agent handoff (arm D) stays a separate fallback/ablation. A simple host-rules controller, a capable native agent, and the agent with a short evidence-checklist prompt are mandatory null comparators. Tool availability, prompt contracts, evidence and budgets must be parity-audited before any efficiency comparison.

This decision incorporates later implementation evidence that post-dates the 2026-11-18 audit:
- [PR #37](https://github.com/dgenio/turnwise-decision-lab/pull/37) proposes one integrated host safety/approval, evidence sufficiency and tool-capable handoff path, still draft.
- [PR #47](https://github.com/dgenio/turnwise-decision-lab/pull/47) has CI-green offline tests for typed heavy-model outcomes returning to the cheap controller; they prove **mechanism**, not quality or economics.
- [PR #38](https://github.com/dgenio/turnwise-decision-lab/pull/38) reports a v0.7 locked synthetic study with a **SHRINK** conclusion: a simple contract planner outperformed more complex alternatives under a weak 0.8B model, but wrong-target approvals, incorrect reasoning and an absent capable baseline preclude release or generalization.
- [PR #46](https://github.com/dgenio/turnwise-decision-lab/pull/46) investigates prospective native-tool-call-only approval authority and the important **A+P** checklist-prompt baseline. Its results are not frozen study evidence.
- [PR #45](https://github.com/dgenio/turnwise-decision-lab/pull/45) supplies complementary request-target validation and direct-execution regressions; reconcile these into **one** host authority path rather than release duplicate host classes.

The previously mentioned #29/#30 framing/parity PRs have been merged into `main`; #32/#33 were closed as superseded. References elsewhere in this document to them as pending are historical to the 18 November audit, not current PR status.

**Merge of this documentation is only acceptance of the experimental question and its safety/evidence gates.** It does not authorize a merge of v0.6/v0.7 code, hosted spending, live user data, production deployment, upstream outreach or any claim of scientific benefit. Use [issue #9](https://github.com/dgenio/turnwise-decision-lab/issues/9) as the independent prospective gate and [issue #34](https://github.com/dgenio/turnwise-decision-lab/issues/34) for the architectural control-ownership invariant.
