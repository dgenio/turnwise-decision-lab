# P0 host contract: finish, escalation, approval holds and action status

Status: **experimental, unmerged, local and synthetic**. This document describes
the integrated fix for #11, #12 and the action-status part of #13, stacked on
v0.6 (PR #6). It is not evidence of better quality, cost or safety on real
models. That needs the prospective study in #9.

Turnwise studies **per-step decision-controlled execution**: a controller picks
each next operation and a host owns everything that executes. The host is the
trust boundary, so every invariant below is enforced there. No controller,
model, tool output or conversation turn can grant itself an exception.

## The four guarantees

| # | Guarantee | Where | What enforces it |
|---|---|---|---|
| 1 | The controller **cannot finish prematurely** | `evidence.py`, `Host.validate(finish)` | Deterministic FINISH needs host-verified, task-specific evidence: the right source, referent, minimum payload, no conflicting observations and an optional freshness clock. A causal question needs health, errors, deploys and config. The finish renders only approved facts, labelled "no causal inference established". From PR #27. |
| 2 | Escalation **keeps tool capability** | `fallback.py`, `loop.py` | Opt-in `LearnedDecider(tool_capable_fallback=True)` emits `handoff_heavy` instead of a text-only `call_model(heavy)`. The same loop continues with the native heavy model proposing one host-validated operation per step. It keeps the same Host, request, observations, permissions and remaining limits. Without a backend the turn abstains; it never degrades to text-only. From PR #32. |
| 3 | No **approval hold for an action the user did not request** | `intent.py`, `Host.validate_write` | A write becomes an approval request only when the user's own words in this turn positively requested that action on that target. Earlier user turns may resolve a pronoun only. A literal status-page text must be posted verbatim. This applies to **every proposer**: controller, handoff and heavy-only baseline. New in this integration. |
| 4 | No **invented action completion** | `Host.compose_final`, `Host.review_generated_answer` | Final action statuses come from host receipts only. Model prose cannot answer for a pending action. A generated reply claiming that a write happened is withheld, because this host has no path that executes a write. The envelope's statuses are ported from PR #33. |

## Write intent (`intent.py`)

The host reads the current user message once per turn and assigns each action
phrase one of these statuses:

| Status | Example | What the host does with a matching write proposal |
|---|---|---|
| `requested` | "Please roll back checkout", "Page the search on-call", `post to the status page: "..."` | Holds it for approval. It is never executed. |
| `needs_clarification` | "roll it back" (no or ambiguous referent), "If not, roll it back", "Can we roll back checkout?", "roll back everything except payments" | Rejects the proposal; the host asks the user. |
| `declined_by_user` | "Do not roll back checkout", "Under no circumstances…", "Roll back checkout. Actually no, don't." | Rejects it; it is recorded and never offered back. |
| not an intent (mention) | "Is checkout healthy?", "Should we roll back?", "What would happen if…", "Draft a status update", "Rollback is not an option", quoted text | Rejects it as `not_requested`. |

Rejected write proposals go to `final["denied_write_proposals"]` with the
proposer and a reason code. They are never laundered into user intents.

The reason codes are `requested`, `not_requested`, `declined_by_user`,
`referent_mismatch`, `message_mismatch`, `unverified_request` and
`duplicate_hold`.

## Final envelope (`Host.compose_final`)

Every new-run final carries these fields:

- `action_status`: one entry per user intent, with its terminal status:
  - `held_for_approval`
  - `needs_confirmation` (named in a host question that says nothing was requested or executed)
  - `not_attempted` (abstain or limits)
  - `declined_by_user`

  A model-drafted status text is flagged `message_source: drafted_by_proposer`.
- `denied_write_proposals`: the audit list described above.
- `writes_executed`: always 0 in this host.

## Frozen evidence

`FrozenV06ReplayHost` keeps v0.6 behaviour exactly for historical replay:
- any FINISH after one read;
- a hold for any write, including duplicates;
- prose passed through unchecked.

No v0.5 or v0.6 data, trace, label, score or report changed. Every committed
report regenerates byte-identically.

## Status

### Implemented and verified (offline, scripted models)

- **Behaviour regressions.** Of seven tests, four fail on the PR #32 head
  (15 subtest failures) and all pass here. They cover:
  - informational questions;
  - tool-injected writes;
  - unrequested status posts;
  - negation, retraction, advice and hypotheticals;
  - earlier unrelated or ambiguous referents;
  - controller-path and baseline-path proposals;
  - legitimate requests that must still be held.
- **Independent probe.** 22 adversarial cases: 17 unsafe outcomes on PR #33,
  5 on PR #32, 2 on the v0.6 controller path, and 0 here.
- **FINISH probe.** 18 cases: 1 wrong on #27 (a fail-closed "owns", now fixed),
  3 on #26 (including an accepted schema-empty payload), 14 on v0.6, and 0 here.
- **Mutation check.** 16/16 single-fault mutants of the P0 path are caught.
- **Read-only counterfactual over every recorded v0.6 hold.** 19 holds of the
  requested action are kept. 14 unrequested or unresolved holds are rejected:
  gen_chooser H06/H24 and heavy-only H02/H12/H24/H30. Status posts are excluded
  because the recorded controller used the whole instruction as the post text;
  argument builders now pass the literal text.
- **Invented completions.** A read-only audit finds invented completion in
  recorded finals beyond H10:
  - heavy-only D-rollback, H02, H17 and H24;
  - dm_nogate H18.

  The frozen scorer never reported these. `bench.action_outcomes()` now reports
  them separately from holds and dropped intents.
- **CI parity.** Python 3.10 and 3.12, with numpy blocked as in CI. Trace replay
  is exact.
- **Compatibility with PR #31.** A trial merge has 3 additive conflicts in
  `host.py` and `loop.py`. The combined suite passes (228 tests on Python 3.10
  and 3.12) and the reports stay byte-identical.

### Partially implemented

- **#13.** Only claims about the three write actions are checked. General
  answer grounding (causal prose, H07/H08/H13) remains #18.
- **#12.**
  - One hold per turn: the loop ends at the first hold and names the rest as
    `needs_confirmation`.
  - Approval state does not persist across turns.
  - Control does not return to the cheap controller after a handoff (#14).
- **#16 / #31.** The native handoff prompt has its own prospective token
  allowance (`HandoffLimits`) but not #31's per-tier template budget.
- **#20.** The operation is still the v0.6 name `handoff_heavy`. There is no
  versioned AAE schema yet.

### Known remaining safety gaps

1. **Lexical intent, limited recall.** If a request is phrased in a way the cue
   lists do not recognise, the model's matching proposal is rejected. It is
   recorded in `denied_write_proposals`, but the user is not asked. This fails
   safe (no hold) but can drop a request from the user's point of view. The
   indirect cues were written after reading H18/H19, so those are contaminated.
2. **Lexical claim detector.** Paraphrased completion claims can pass, for
   example "checkout is back on d-141 now".
3. **Model-drafted status text.** When the user gives no literal text, the
   proposer drafts it and the hold is flagged. Its content can still be steered
   by injected tool output; the approver must read it.
4. **English and the synthetic world only.** Coverage is three write
   capabilities and the existing service alias map.
5. **Over-conservative cases.** Some fail closed rather than proceed:
   - "it's not working, roll back checkout" asks for confirmation;
   - "Roll back checkout. Don't wait for approval." is read as a retraction.
6. **No active cancellation or spend cap.** There is no timeout cancellation of
   a hung local backend and no USD cap.

### Scientific validation not run

- Precision and recall of the intent gate and claim detector on new,
  independently written requests (#9).
- Real-model behaviour of the handoff against a capable heavy-only baseline
  with native tools. The baseline now shares the host gate, which is a
  declared #25 parity change.
- Cost, latency and quality effects of any of this. Treat all of it as
  `not_run`. The v0.6 quality HOLD (#5) stands.
