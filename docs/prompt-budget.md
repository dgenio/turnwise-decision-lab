# Hard generation-prompt budget

Implementation for #16; prospective research and cross-arm parity remain #9
and #25. This is an offline-tested runtime invariant, not a quality or savings
result. The v0.6 scientific release gate remains **HOLD** (#5 / #24).

## Contract

`execute_user_turn` obtains the host-owned input-token limit from
`Limits.max_prompt_tokens` (light: 700, heavy: 2200). Output limits remain
separate in `Limits.max_generation_tokens`. Zero is a valid input budget;
negative, boolean and non-integer budgets are configuration errors.

Assembly keeps the full user question and every eligible mandatory host block.
It redacts before counting, uses the selected model's tokenizer on the **same
complete chat template** that generation uses, and removes whole optional blocks
in priority order until the prompt fits. Counts are recomputed after each
removal because tokenization across block boundaries is not additive. No part
of the question or a retained evidence block is silently truncated to fit.

Optional dependencies are transitive. A block with an unavailable dependency is
excluded; permission checks apply to dependencies too. Removing a dependency
also removes its dependents. Every exclusion has a reason. `omitted_evidence`
lists tool/reference blocks omitted by permission, eligibility, selection or
budget. This inventory **does not establish answer sufficiency**; #11/#15 own
that contract.

| `budget_status` | Meaning | Model call |
|---|---|---|
| `within_budget` | The complete redacted, serialized prompt was measured and fits. | Allowed, subject to the backend's last preflight. |
| `mandatory_overflow` | Optional blocks have been removed; the measured mandatory content and question still exceed the limit. | Blocked; host abstains visibly. |
| `unknown_token_count` | No full-template counter is available, or it failed/returned an invalid count. | Blocked; host abstains visibly. |

The runtime does not escalate automatically to another model on overflow: that
would require a separately validated budget and might add uncounted work.
`PendingGenerator` has no exact tokenizer, so it records an unknown-budget
abstention without inference. A backend with only a string/block counter also
cannot authorize generation.

`LocalGenerator.prompt_counter(tier)` supplies the full-template counter. Just
before inference, `LocalGenerator.generate` serializes and counts again. A
changed count/prompt budget blocks with `prompt_changed`; an unavailable counter
blocks with `unknown_token_count`; an unchecked or wrong-tier preflight blocks
with `invalid_prompt_preflight`. These are bounded host abstentions in the loop.
There is no runtime switch to disable the gate.

## Trace accounting

Assembly records the budget/status, complete-prompt `measured_tokens`, a separate
chars/4 content-only `estimated_tokens`, `count_scope`, per-block attribution
counts and their counter type, redactions, exclusions, omitted evidence and
assembly time. `tokens` is the measured total when available, otherwise an
explicitly labelled estimate. Individual block counts are attribution aids;
their sum is not a complete chat-token count.

The loop records selection wall time separately from existing decision-question
latencies, plus assembly time, the final budget-guard time and the number of
blocked calls. These intervals can overlap token-level controller metrics;
do not sum both representations. Generation prompt counts come from the backend
only when inference runs; cached tokens, if any, still occupy prompt capacity.
This change adds no cache implementation or economic estimator.

The guard covers generation through `execute_user_turn` and `LocalGenerator`.
It does not retrofit budgets into controller scoring, argument extraction or the
separate native heavy-only loop. Those paths and comparator parity need their
own contracts under #16/#25 before a prospective comparison. This is an input
limit, not a claim to enforce a model's combined input/output context window.

## Historical evidence

Frozen datasets, prompts, labels, traces, scoring, reports and pages are not
rewritten. In `reports/v06/traces/heldout/gen_chooser.json`, H28's light prompt
reported 695 block-summed tokens but actually used **709**, above its 700-token
limit. That failure remains visible in the original trace.

Historical replay supplies the **recorded prompt** at the assembly boundary,
marks it `historical_unchecked` and uses a non-executing replay generator. The
test-only adapter cannot be selected by production code. Replay proves the old
observations/outcomes still reproduce; it does not certify old budget compliance
or rerun model inference. New budget behavior is tested separately against an
exact synthetic tokenizer and the real loop/backend interfaces.

## Offline verification

```sh
python -m unittest discover -s tests -p test_prompt_budget.py
python -m unittest discover -s tests
```

The regression `test_long_request_does_not_reach_model_with_default_limits` uses
the original loop API: it fails at source commit
`06379175ff419d42d875da5d71e0ed257986ebe5` because the oversized prompt reaches
the fake generator, and passes with this guard. Other cases cover chat overhead,
zero budget, long tool output, transitive/forbidden/cyclic dependencies,
redaction, tokenizer/estimate disagreement, unavailable counters, changed
templates and a range of request sizes/budgets.

No provider calls, model downloads, new held-out study or performance claim are
part of this change. A full-vs-selected-vs-native context comparison remains
**not_run**, coordinated by #9 rather than inferred from these tests.
