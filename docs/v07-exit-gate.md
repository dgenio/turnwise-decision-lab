# The exit gate and evidence contracts (v0.7)

**Gate the exit, not every step.** A controller, whatever it is, drives the turn. The host checks the turn where it ends.

This document describes the mechanism. Why it was chosen is in [`v07-research-assessment.md`](v07-research-assessment.md); what was measured is in [`reports/v07/summary.md`](../reports/v07/summary.md).

## The three parts

```text
request + conversation ──► claim typing (lexicon, no model) ──► evidence contract
                                                                     │
 any controller ──► tool calls ──► receipts ──┐                      ▼
 (rules, learned head, LLM agent)             ├──► EXIT GATE: sufficiency · action latch · grounding
          ▲        proposes to end the turn ──┘        │
          └──── missing receipts, run by the host ◄────┤ acquire
                                                       ├─► approval request (hold)
                                                       ├─► clarifying question
                                                       └─► reply sent, or withheld and replaced by host findings
```

### 1. Evidence contract ([`v07/evidence.py`](../turnwise_lab/v07/evidence.py))

- **Tool metadata.** Each read capability declares the evidence it produces and its *role*: `symptom` (health, error metrics), `change` (deployment history, config diff), `ownership`, `reference` (runbooks), `composite` (smoke checks). This is the only world-specific input, and it is the kind of annotation a framework already attaches to a tool.
- **Claim typing.** A small lexicon types the request: `lookup`, `record`, `causal`, `verification`, `action`, `smalltalk`, `ambiguous`, or `untyped`. It reads the user's text and the conversation, nothing else. It is deliberately conservative: a long message with no causal or action cue is `untyped`, not guessed.
- **The two-sided rule.** A reply that attributes a cause needs a `symptom` receipt *and* a `change` receipt for the same entity. If the request names no change, both change records are required. This rule does not depend on the incident world.
- **Revision by observation.** The contract is re-read after every receipt:
  - errors did not rise → the cause side is dropped (there is nothing to explain);
  - no deployment on record → the configuration diff becomes required;
  - configuration matches baseline → there is no drift to look up a documented reason for.
- **Host-derived facts.** Orderings and differences are computed by the host from receipts: "d-142 landed 3 min before the rise", "15 min after, so it cannot have caused it", "no deployment in 24h". Each derived fact names the receipts it uses. A one-sentence verdict is rendered from them and is never stronger than the evidence ("consistent with … not proof").

### 2. Exit gate ([`v07/gate.py`](../turnwise_lab/v07/gate.py))

`ExitGate.review(message, conversation, observations, terminal, text)` returns one of:

| Verdict | When | What the host does |
|---|---|---|
| `allow` | contract met, or no contract applies | the exit happens |
| `acquire` | a finish or an answer is proposed while a requirement has no receipt | runs the named calls itself, one at a time, re-reading the contract after each; the controller is not asked while this lasts |
| `hold` | the user asked for a side effect and no approval request exists yet | raises the approval request; this also applies at a step limit or a malformed call |
| `clarify` | an action or an evidence-free reply about something the host cannot resolve | asks which service is meant; it never guesses a target |

After generation, `ExitGate.ground` checks the reply against the receipts: values (deploy ids, times, percentages, durations, role ids) that appear in no receipt, and claims that a side effect was performed. A reply that fails is withheld; the host's findings are sent instead, with a notice that says why.

For a request the lexicon could not type, the gate derives a contract from the **reply itself**: causal language on one-sided evidence triggers the two-sided rule.

The gate is bounded (`max_interventions`, default 3; one retry per failed call), authorises nothing, and has no access to gold labels. Evidence that could not be retrieved is disclosed in the reply, never hidden.

### 3. Contract planner ([`v07/controllers.py`](../turnwise_lab/v07/controllers.py))

If the contract determines every next call, nobody needs to choose. `run_contract_turn`:

- **typed request** → runs the contract's calls in order, then returns the host's findings and verdict. No model is called for control, and by default none for the reply;
- **untyped request** → hands the turn to the **tool-capable** heavy agent behind the same gate. Uncertainty never goes to a text-only generator, so an action request can still become an approval request.

The `contract_narrated` ablation gives the findings to the heavy model to phrase, then grounds the result.

## Using the gate around an existing agent

The gate is a function of trusted state. It needs four things from a host loop: the user message, the conversation, the tool results so far, and a hook where a final answer can be refused.

| Framework | Hook (checked against documentation on 2026-11-18) | Shape |
|---|---|---|
| LangChain v1 agents | `after_model` middleware with `can_jump_to=["model"]` | on a no-tool-call message, call `review`; on `acquire`, append the tool results and jump back to the model |
| OpenAI Agents SDK | output guardrail tripwire, caught by a host loop that re-runs | on `acquire`, run the tools, add the results to the input, run again |
| LlamaIndex Workflows | a step before `StopEvent` | branch on the verdict |
| Any loop you own | where you would return the answer | see `agent/heavy_agent.py` (`gate=`) and `v07/hosted.py` |

These are integration notes, not shipped adapters. Nothing here has been proposed to those projects.

## What the gate does not do

- **It does not check reasoning.** A reply can cite only grounded values and still relate them wrongly ("the rise at 11:05 was three minutes *before* the deploy at 11:02"). The `contract_narrated` arm shows this; see the adjudication.
- **Its claim typing is a lexicon.** New phrasing is missed. A miss sends the turn to the agent, which costs more; a *wrong* type produces a confident host-written reply to the wrong question. The report counts both.
- **Its contract is as good as the tool metadata.** In a world where the cause lives outside the catalogued change records, the contract will be met and the conclusion will still be incomplete. The verdict wording says "the evidence above", not "the cause".
- **It trusts receipts.** It checks that a value appears in a receipt, not that the receipt is true. `LocalHarness` is an educational stand-in, not a security boundary.
