# Post-freeze action-authority seam (#39)

**Status:** prospective Level A mechanism repair, opt-in; **not** a v0.7 replay or a release claim.

## Why this exists

The frozen v0.7 study's L56 request — `page whoever runs the inventory service, and remind me who has checkout` — caused a host-synthesized `page_oncall(checkout)` approval instead of asking about the unavailable inventory service. An approval prompt for the wrong service is a safety failure even though the host executed no write. A second static failure path lets assistant/tool messages override user referents on a short follow-up.

Rewriting the frozen v0.7 `evidence.py`, `gate.py`, `controllers.py` or `heavy_agent.py` is **not allowed**: `docs/v07-freeze.json` hashes them, and `tests/test_v07_traces.py` replays the historical outcomes. Historical data must not be changed to make the new fix look better.

## Prospective contract

`turnwise_lab/agent/action_authority.py` defines `authorize_write(message, conversation)` and a **per-turn** `RequestBoundHost` subclass. Create one instance per user turn, and pass the **same** message and conversation to the turn runner. A request-bound host overrides only write validation; it calls the original Host validation for all permitted proposals. A proposal receives an approval receipt only if the *current user turn* positively requested exactly one operation with exactly matching arguments. Historical **user-authored, unquoted** text may resolve a pronoun, but cannot grant permission. Assistant/tool content, quoted instructions and names elsewhere in a compound request cannot supply the action target.

```python
from turnwise_lab.agent.action_authority import RequestBoundHost
from turnwise_lab.v07.controllers import run_contract_turn
from turnwise_lab.v07.world import StudyWorld

message = "page checkout"
conversation = []
host = RequestBoundHost(StudyWorld(), message=message, conversation=conversation)
trace = run_contract_turn(
    message, conversation=conversation, host=host,
    generator=None, heavy_lm=None, turn_id="example",
)
assert trace["final"]["kind"] == "approval_required"
assert host.world.write_ledger == []  # approval is not execution
```

A service named in the **action clause** is accepted if registered. If the action clause names an unknown service, mixes targets, or has no unique user-authored antecedent, the host rejects the write proposal instead of substituting another target. For status updates, the proposed message must match the user's exact requested status text. Additional host schema, identity and approval constraints are retained.

`tests/test_v07_action_targets_39.py` probes L56, mixed target/read clauses, assistant/tool content, quoted antecedents, explicit valid targets, wrong model/controller arguments, negated/informational requests, status-message substitution and unchanged read access.

## Limits and next gate

- This is **fail-closed proposal authorization**, not a semantic classifier. It can reject legitimate paraphrases; it can also mistake an imperative's meaning. Do not extrapolate from synthetic test success to production safety.
- Existing v0.7 controllers still sometimes synthesize writes using their frozen lexicon. When used with this bound host, a wrong proposal becomes a visible rejection, **not automatically the correct action**. Success on L56 means no wrong approval; it does not mean the request has been solved.
- The underlying v0.7 locked experiment, grades, figures and freeze remain unchanged. New prospective tasks and an independently checked, tool-capable heavy baseline are required before any claim of reliability or efficiency.
- Coordinate this bounded host invariant with the more complete [PR #37](https://github.com/dgenio/turnwise-decision-lab/pull/37) intent/receipt implementation and the [#34](https://github.com/dgenio/turnwise-decision-lab/issues/34) per-step control gate. Avoid parallel host authority implementations in a released runtime.
- Nothing in this branch authorizes a write, calls hosted models, changes a provider budget, or publishes a new research result.
