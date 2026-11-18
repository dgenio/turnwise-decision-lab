# Capability-preserving handoff (#12)

**Status:** opt-in mechanism with offline regression tests. Contract `turnwise.handoff/0.2`. **Not evidence** of better quality, cost or safety. Frozen v0.6 arms, traces, scores and reports are unchanged, and every recorded trace still replays exactly. The effect on new, independently written cases is **not run** (#9).

## The defect

When turnwise-dm's top probability fell below the 0.5 gate, `LearnedDecider` returned `call_model(tier=heavy)`. The loop treats that as **text-only** generation, which cannot call tools or raise an approval request. On held-out H18 and H19 this replaced the turn's action space with prose, and both requested actions were dropped (`reports/v06/audit.md` section 2). The fallback itself removed capability; the threshold value was not the cause.

## The change

`LearnedDecider(..., fallback="handoff")` returns a distinct `handoff` operation. `execute_user_turn(..., handoff_lm=<native tool-calling model>)` then continues the turn with the **same heavy agent as the heavy-only baseline**: the same system prompt, native tool schemas, parser, `Host`, fact rendering and per-round token limit. The default stays `fallback="text_v06"`, the frozen v0.6 behaviour, and the heavy-only baseline is unchanged. `system_block` gained one keyword whose default keeps the baseline's output identical.

| | Built by | Contents |
|---|---|---|
| `Handoff` (in `Decision`) | decision provider | Hints only: reason, the controller's own top choice and its score, and a write hint if that choice was a write |
| `HandoffContract` | **host** | Exact request and conversation; principal and permissions; whether the incident record is visible (it needs `read_incident`); all catalog tools; approval hold on; writes not executable; prior receipts; **the user's actions as resolved by the host**; controller suspicions that can only lead to a question; ignored hints; remaining rounds; tool-call and token caps |
| final `action_status` | **host** | One entry per action. Sources: `user_request`, `controller_candidate`, `heavy_agent_proposal`. Statuses: `requested`, `unverified`, `not_requested`, `held_for_approval`, `needs_confirmation`, `not_attempted` and `rejected`. `executed` exists in the vocabulary but this host cannot reach it |

## The host's intent gate (`turnwise_lab/agent/intent.py`)

An approval request asks a human to act on the user's behalf, so it needs positive evidence that the user asked for that action. The resolver reads **only user-authored text**: the current message, then earlier user turns. It never reads model output, tool data or benchmark gold. It is conservative and lexical: English, and this world's three write capabilities.

| User wording | Status | What the handoff does |
|---|---|---|
| Explicit request, target named in this message ("roll back checkout", "page search and checkout", a status post with a literal body) | `requested` | Holds **only** a proposal that matches it: same capability, same target, and the same literal post text. Never executes it |
| Action wording whose target is ambiguous, missing, or only in an earlier turn ("roll it back") | `unverified` | Never holds. The host asks the user to confirm |
| Negated, advice-seeking, hypothetical, drafting or reporting ("do not…", "should we…", "if…", "draft…", "who rolled back…") | `not_requested` | Never holds, never asks; a proposal for it is rejected |
| No action wording ("is checkout healthy?") | none | Any write proposal is rejected |

The controller's uncertain write choice (H19: `page_oncall`, 0.49) is used only when it was formed from the user's words alone, before any tool output. Even then it can only produce a confirmation question. A write the heavy agent proposes without a matching `requested` action is **rejected and kept in the audit trail only**. It never becomes a user intent and never prompts the user, because tool output can steer what the model proposes. When such a rejection happens in a turn that ends as an ordinary answer, the host appends "[host] No action was requested or executed in this turn."

## Invariants (host-side; tested in `tests/test_handoff.py`)

1. **Capability.** The continuation always has every tool and the approval hold. It is never text-only. Without a configured agent, or with no budget left, the turn **abstains**.
2. **Contract.** The host builds the contract. Controller hints are re-checked. A hint naming a read, an unknown capability or an untyped object is dropped, and so is one the user's wording already covers or one formed after tool output. Every drop is recorded.
3. **Authority.** Writes are never executed, including for a principal with write grants. A hold requires a host-resolved `requested` action that the proposal matches.
4. **No silent drop.** A `requested` or `unverified` user action ends in one of three ways: held; a host-written confirmation that names it; or an abstention that lists it as not attempted.
5. **Bounds.**
   - Model rounds share the turn's `max_steps`.
   - Proposed tool calls are capped (`Limits.max_handoff_tool_calls`, default 8, counting rejected calls).
   - A call that already succeeded in the turn is rejected rather than repeated.
   - A model exception or timeout abstains.
   - **Token cap.** `max_handoff_computed_tokens` is checked *before* each computation with the model's own tokenizer. The system-prefix fill (on a cache miss) and each round's new prompt count against it, and each round's completion is limited to what is left. With a cap set, a model that cannot count tokens is not run. If the model then reports more tokens than were counted, the handoff stops. The cap covers newly computed handoff tokens only. It does not cover earlier controller or generation work in the turn, wall-clock time, or US dollars.
6. **Status.** When an action is involved, the final text is written by the host. The model's prose is kept in `final.model_text`. Each round is a trace step with its own generation record, so the existing scorer counts heavy calls and tokens. The trace reports controller decisions, handoff rounds, tool calls, prefix fill and cached prompt tokens separately.

The mutation check (described in the PR) has 18 mutants, each reintroducing one failure mode. All 18 fail the suite with numpy blocked, as in CI.

## What H18 and H19 show, and what they do not

* **H19** ("get someone from the search team on the line"). There is no action verb, so the wording is not a verifiable request. The controller's uncertain `page_oncall` choice is carried as a suspicion. Whether the heavy agent answers in prose or proposes `page_oncall(search)`, the turn ends in a **host confirmation question**, not an approval. A silent drop becomes an explicit question. The frozen scorer still counts it as `dropped_action`.
* **H18** ("put checkout back to how it was"). The controller's top choice was a read, and the wording has no action verb. A heavy-agent rollback proposal is rejected and visible in the trace; the turn answers without acting.

This is the conservative gate's deliberate trade: it prefers false confirmations and visible rejections to unrequested approval requests. The recall of indirect requests, and the cost of extra confirmations, are measurements for #9 on new cases. They are not to be tuned on frozen held-out wording.

## Declared differences from the heavy-only baseline (for #25)

The handoff differs from arm A in these respects:
- a host note with earlier receipts and the user's actions, omitted when there is nothing to carry;
- the intent gate on writes;
- the tool-call and optional token caps;
- a round budget shared with the controller's earlier steps;
- the incident record shown only to principals with `read_incident`. The baseline always shows it, which matches its own `demo-reader` principal.

## Relation to PR #32

PR #32 implements the same issue with a different design: a host intent ledger, plus in-loop continuation in which the heavy model proposes one operation per step and its prose is never a final answer. The review on PR #33 asks for a single implementation and contract (#20). The comparison and recommendation are in the PR #33 discussion.

## Limitations and open dependencies

* **Intent resolver:** lexical and English-only, covering three write capabilities. Indirect phrasings without an action verb are not detected. Clause splitting does not split on commas, so "don't roll back checkout, roll back search instead" is treated as negated as a whole. That is safe but misses the second request.
* **#13:** claims in prose when no write was proposed are not checked (the H10 mechanism).
* **#13, #18:** the frozen v0.6 scorer cannot distinguish `needs_confirmation` from a dropped action, or a rejected unrequested proposal from a clean turn.
* **#14:** control does not return to the cheap controller after a handoff.
* **#9:** no benchmark arm is wired and no real model was run.
* Approval state is per turn.
