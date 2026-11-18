# Local tool-capable heavy handoff (experimental)

An uncertain controller used to select `call_model(heavy)`, which generated text
without a tool loop. A request to roll back or page someone could disappear at
that boundary. Issue #12 tracks the repair; #13 owns the wider final-answer
action-status contract.

This opt-in path introduces `handoff_heavy`. It changes the next-step proposal
source **inside the existing loop**. It keeps the same Host, user request,
conversation, observations, permissions, retry/rejection limits and remaining
steps. There is no second runtime and no fresh step budget.

The implementation is stacked on the evidence-sufficiency proposal in PR #27.
Neither that dependency nor v0.6 PR #6 is approved for merge by this change.

## Execution contract

- `LearnedDecider(..., tool_capable_fallback=True)` emits `handoff_heavy` when
  its score is below its existing threshold, including an uncertain heavy-model
  choice. The default retains the historical behavior. Confidence calibration
  remains unproven.
- `execute_user_turn(..., heavy_fallback=NativeHeavyFallback(the_same_local_heavy_lm))`
  enables continuation. A handoff without a backend visibly abstains.
- The adapter reuses the heavy comparator's native tool schemas, prompt template
  and call parser. Each generation can propose one tool/workflow. Multiple native
  calls in one response are rejected; tools still pass through Host validation
  and LocalHarness. Earlier successful calls cannot execute again.
- The host derives rollback/page/status-post intents from the user's own words
  (`intent.py`, see [p0-host-contract.md](p0-host-contract.md)) and applies the
  same check to every proposer, not only to this path. Unresolved or conditional
  requests clarify; negated, advisory, hypothetical and merely mentioned actions
  are never held; tool/model text cannot create or resolve an intent. The first
  valid write produces a host-rendered approval hold and ends the turn. Other
  actions remain explicit in `final["action_status"]` and in the text.
- Free-form heavy text never becomes the final answer on this path. With pending
  actions it clarifies. Otherwise it proposes FINISH, which must pass the host's
  evidence gate. The final reply contains verified source data, with no causal
  conclusion certified by this mechanism.
- Incident context requires both `read_incident` and the permitted
  `incident_record` block. Conversation and tool-result content follow the host's
  permitted blocks. Full receipts stay in host state; withheld content is marked
  in the prompt. Native role delimiters in nested data are escaped.

## Limits and accounting

`HandoffLimits(max_input_tokens=16000, max_output_tokens=512)` sets a local
continuation allowance. Reported prompt/completion tokens from all earlier
generation tiers are deducted. The native prompt is tokenized before inference;
output is capped by both the remaining allowance and the host's per-call limit.
Unknown usage stops continuation. No context is silently truncated to fit.

This is **not** a retroactive cap on earlier generations, a controller-compute
cap, a wall-clock timeout, or a cumulative USD spending guarantee. No remote
provider is wired into this adapter. A local backend exception/TimeoutError
stops visibly; cancellation of a hung native backend is not implemented here.

Every native prompt, output and measured token/time receipt is traced. Controller
questions and native generation are counted separately. Failed calls retain an
attempt record; unavailable aggregate usage is `null`, with
`totals.handoff.usage_complete=false`. Provider cost remains `null`.

The native path currently uses **cold full prompts** (`cached_prompt_tokens=0`),
while the frozen comparator reuses a prefix cache. A prospective comparison must
declare/control that treatment difference under #25; no efficiency result is
claimed from this implementation.

## Local wiring

For an already-loaded local heavy LM and controller:

```python
from turnwise_lab.agent.fallback import HandoffLimits, NativeHeavyFallback
from turnwise_lab.agent.loop import execute_user_turn

# Construct LearnedDecider with tool_capable_fallback=True. Reuse the exact
# heavy LM used by the comparator; do not substitute a stronger fallback arm.
trace = execute_user_turn(
    message, host=host, decider=controller, context=context, generator=generator,
    turn_id="new-development-turn", conversation=conversation,
    heavy_fallback=NativeHeavyFallback(
        heavy_lm, limits=HandoffLimits(max_input_tokens=16000, max_output_tokens=512)
    ),
)
```

No weights are downloaded and no inference is triggered merely by importing the
adapter. The default benchmark does not opt in or regenerate historical runs.

## Validation and remaining work

```sh
python -m unittest discover -s tests -p test_heavy_fallback.py -v
python -m unittest discover -s tests -v
```

These are developer-authored mechanical regressions: they exercise the action
loss mechanism of frozen H18/H19, plus forged approvals, wrong-service proposals,
malicious tool content, prior successful calls, batch rejection, token limits,
backend failures and complete accounting. They are **not independent held-out
evidence**, and do not revise any v0.5/v0.6 result.

The host intent policy is deliberately lexical and scoped to three synthetic
capabilities (gaps listed in [p0-host-contract.md](p0-host-contract.md)). It can miss paraphrases or reject valid requests. Approval execution
and persistence/resumption across separate turns remain the caller's job; this
lab never executes a write. A capable real-model baseline, unseen task quality,
general final-answer semantics, provider economics and framework integration
remain #9/#13/#20/#21. Keep the quality HOLD until those gates pass.
