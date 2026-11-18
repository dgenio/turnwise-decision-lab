# Capability-preserving handoff (#12)

**Status:** opt-in mechanism with offline regression tests. **Not evidence** of better quality, cost or safety. Frozen v0.6 arms, traces, scores and reports are unchanged, and every recorded trace still replays exactly. The effect on new, independently written cases is **not run** (#9).

## The defect

When turnwise-dm's top probability fell below the 0.5 gate, `LearnedDecider` returned `call_model(tier=heavy)`. The loop treats that as a **text-only** generation call: the generator cannot call tools or raise an approval request. On held-out H18 and H19 this replaced the turn's action space with prose, so both requested actions were dropped (`reports/v06/audit.md` section 2). Lowering the threshold would not fix this. The fallback itself removed capability.

## The change

`LearnedDecider(..., fallback="handoff")` returns a distinct `handoff` operation instead. `execute_user_turn(..., handoff_lm=<native tool-calling model>)` then continues the turn with the **same heavy agent as the heavy-only baseline**: the same system prompt, native tool schemas, parser, `Host`, fact rendering and per-round token limit. `heavy_agent.py` is unchanged. The default stays `fallback="text_v06"`, the frozen v0.6 behaviour.

| | Built by | Contents |
|---|---|---|
| `Handoff` (in `Decision`) | decision provider | Hints only: reason, the controller's own top choice and its score, and a pending intent if that choice was a write |
| `HandoffContract` | **host** | Exact request and conversation, principal and permissions, all catalog tools, approval hold on, writes not executable, prior receipts, re-checked intents, ignored hints, services the user named, remaining rounds, tool-call and token caps |
| final `action_status` | **host** | One entry per action, from host receipts: `held_for_approval`, `needs_confirmation` or `not_attempted` (`executed` exists but this host cannot reach it) |

## Invariants (host-side; tested in `tests/test_handoff.py`)

1. **Capability.** The continuation always has every tool and the approval hold. It is never text-only. Without a configured agent, or with no budget left, the turn **abstains**; it does not degrade.
2. **Contract.** The host builds the contract. Controller hints are re-checked: a read capability, an unknown capability, an untyped hint or a target the user never named is dropped, and the drop is recorded.
3. **Authority.** Writes are never executed, including for a principal with write grants. A write proposal becomes an approval hold only when its `service` is one the user named in this session. Model output, tool output and assistant turns never count. A forged `approved` argument fails schema validation.
4. **No silent drop.** A pending action ends in one of three ways: held for approval; a host-written clarification that names it ("did you want page_oncall(service=search)? Nothing has been requested or executed"); or an abstention that lists it as not attempted. It never ends as an ordinary answer.
5. **Bounds.** Model rounds share the turn's `max_steps` with the controller's steps. Proposed tool calls are capped (`Limits.max_handoff_tool_calls`, default 8, counting rejected calls). Newly computed tokens can also be capped (`max_handoff_computed_tokens`). A call that already succeeded in the turn is rejected rather than repeated. A model exception or timeout abstains.
6. **Status.** When an action is involved, the final text is written by the host. The model's prose is kept in `final.model_text` for audit. Each round is a trace step with its own generation record, so the existing scorer counts heavy calls and tokens. Controller decisions, handoff rounds, tool calls and cached prompt tokens are reported separately (`totals.handoffs`, `handoff_rounds`, `generation_cached_prompt_tokens`; `steps[i].handoff`).

The mutation check behind these tests is described in the PR. Ten mutants each reintroduce one failure mode (silent drop, executed write, invented target, repeated read, unbounded rounds and so on). All ten fail the suite with numpy blocked, as in CI.

## What the regression tests on H18 and H19 show, and what they do not

* **H19.** The controller's uncertain top choice was `page_oncall` (0.49), so it is now carried as a pending intent. If the heavy agent proposes it, it is held. If the heavy agent replies with prose, as the recorded 0.8B model did, the host asks for confirmation instead of returning that prose.
* **H18.** The controller's top choice was a **read** (`get_error_metrics`, 0.48). No intent is carried, because the rule is only that the gate must never remove an action the controller itself would have proposed. The heavy agent now *can* raise the rollback approval. A heavy agent that ignores the request still drops it, which is the heavy-only baseline's failure mode. Whether a capable model recognises such requests is the question for #9.

These are mechanism tests with a scripted model on frozen development cases. They are not prospective validation.

## Declared differences from the heavy-only baseline (for #25)

The continuation differs from arm A in four places. First, a host note carrying earlier receipts and pending intents; it is omitted when there is nothing to carry, so the prompt is then identical to the baseline's. Second, the write-target grounding check. Third, the tool-call cap. Fourth, a round budget shared with the controller's earlier steps. Any comparison must report these differences.

## Limitations and open dependencies

* **#13:** prose is not checked for unsupported claims of completed actions in turns where no action was involved.
* **#13, #18:** the frozen v0.6 scorer counts a host confirmation on an approval-expected task as `dropped_action`. Separate metrics are needed for `needs_confirmation`, a dropped intent and an unrequested hold. Model-originated holds are attributable through `source: heavy_agent_proposal`.
* **#14:** control does not return to the cheap controller after a handoff; the handoff ends the turn.
* **#9:** no benchmark arm is wired, and nothing was run with a real model. That needs new independent cases and a capable model, under owner-approved budgets.
* The service lexicon is the existing English alias map. Approval state is per turn: earlier turns' holds are not tracked as receipts.
