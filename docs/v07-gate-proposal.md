# Proposal for the next review gate (after v0.6)

**Status: proposal, not a pre-registration. Nothing here has been run, and no spend is authorized.**

This turns the owner review of PR #6, issue #5 and the [quality-constrained efficiency protocol](quality-constrained-efficiency-v06.md) into a concrete next experiment. Every number marked *(owner)* is a decision for the project owner and must be fixed **before** any run.

## What v0.6 leaves open

These findings come from [`reports/v06/audit.md`](../reports/v06/audit.md), a post-hoc reading of the frozen traces.

1. **Investigations.** The decision-driven arm solved 0 of 7. The causes were:
   - two premature finishes with raw data;
   - three answers generated without a complementary piece of evidence (one of them after an escalation);
   - answers that failed the check although the evidence was complete. A blinded adjudication of those answers is reported in the audit.
2. **Escalation.**
   - Most failures were *confident* errors: the probability at the decisive step was at or above the gate, so the gate could not fire.
   - Where it did fire, on two action requests, it handed the turn to a text-only generator. That generator could not raise an approval, so both actions were dropped.
   - The verification protocol never fired.
3. **Accounting.** The pre-registered "96.5% fewer heavy tokens" does not hold as a compute saving:
   - Counting tokens the 0.8B model actually computed, the decision-driven arm processed about 45% *more* than the heavy-only agent.
   - What did fall was wall-clock compute per attempted task, by 47%, mostly decode time.
4. **Comparison.**
   - The "heavy" model is 0.8B.
   - The decision head was trained on 614 project-specific synthetic states while the heavy-only agent was not, so architecture and training are confounded.
   - No quality margin was fixed in advance.

## Proposed design

### Data
- **New tasks, written prospectively** by an author who has not seen v0.6's traces, failures or controller. A human is preferred. Multi-turn investigations must be well represented, alongside lookups, ambiguity, action requests and adversarial near-neighbours.
- **A separate development and calibration split**, used for any mechanism change or threshold. The test split is locked and hashed before any arm runs on it.
- v0.6's 30 held-out tasks are now *seen* and can only be used for development.

### Arms
All arms use the same host, tools, permissions, step and token budgets, and the same capable heavy model.

| Arm | Description |
|---|---|
| A' | Capable heavy-only agent with native tool calling (primary reference) |
| B' | A' with provider-native tool search or deferred schemas, where the provider supports it |
| C' | Deterministic host rules + the same capable heavy model as fallback |
| D' | Decision controller + the same heavy model as fallback. Escalation hands the turn to the **heavy agent with tools**, not to a text-only generator, so an action request can still become an approval request |
| E' | D' without the learned head (rules + controller features), to separate training from architecture |

### Mechanism changes, developed on the development split only
- **Evidence sufficiency as typed state.** For example: "a causal question has change evidence but no candidate-cause evidence yet". Computed by the host from observation types, never from gold labels.
- **Escalation that keeps capability.** The fallback can still call tools and raise approvals.
- **Controller cache reuse across steps,** so the controller's token count reflects the design rather than an implementation shortcut.

### Metrics, fixed in advance
- **Quality gate:** paired non-inferiority against A', with margin δ *(owner)*, one-sided α = 0.025, and the Newcombe paired interval used in v0.6.
- **Safety gate:**
  - 0 executed unauthorized writes;
  - dropped actions reported separately, with a ceiling *(owner)*;
  - unsupported causal claims of major or critical severity, with a ceiling *(owner)*. These are judged by a blinded adjudicator using [`v06-adjudication-rubric.md`](v06-adjudication-rubric.md), ideally a human.
- **Efficiency, only if both gates pass:**
  - total cost per *attempted* task: every decision, context, argument, generation and tool call, with cache hits reported separately;
  - p50 and p95 latency;
  - tokens actually computed;
  - provider-reported usage and price provenance for any hosted call.

### Sample size
Approximate size for a paired non-inferiority test with a true difference of 0, one-sided α = 0.025 and 80% power: n ≈ 7.84 · q / δ², where q is the share of tasks on which the two arms disagree.

| q (discordance) | δ = 15 pp | δ = 10 pp | δ = 5 pp |
|---:|---:|---:|---:|
| 0.57 (v0.6, D vs A) | ~200 | ~450 | ~1,800 |
| 0.30 | ~105 | ~235 | ~940 |

With 30 tasks, every arm's interval still allowed a loss of 12–25 pp, so no tighter margin could be supported. This is the main reason v0.6 is inconclusive.

### What needs owner approval
- The margin δ, the safety ceilings and the sample size.
- The capable heavy model. There are two options:
  - **a larger local model:** a 7–8B quantized model is about 5 GB, above the current ~4 GB download budget, and slow on CPU;
  - **a hosted model,** with explicit approval and a spending cap. Token use per task can be estimated from v0.6's traces; any price must be quoted from the provider at the time.
- Whether to run the OpenAI Decisions or System One adapters, which needs credentials and a cap.

## Decision rules
These follow the protocol:
- **GO** only if both gates pass at the agreed margin and the efficiency gain is material against A' *and* C'.
- **HOLD** if power, independence or cost receipts are missing.
- **SHRINK** to the parts that show credible value, for example host rules plus capable fallback.
- **STOP** if a simpler arm matches it.
