# Arm-parity preflight for prospective Turnwise studies

**Scope:** a small, dependency-free, **static structural audit** for the independent benchmark in [#9](https://github.com/dgenio/turnwise-decision-lab/issues/9), motivated by the comparator confound in [#25](https://github.com/dgenio/turnwise-decision-lab/issues/25).

**This is not a runtime agent, a quality scorer, an instrumented v0.6 replay or evidence of causal parity.** It is deliberately a preflight checklist with machine-verifiable receipts.

## Why this exists

A cost/quality advantage is uninterpretable if one arm gets a runbook injected implicitly while another must spend a tool call, or if one arm can make multiple tool calls in one "step" while another counts each operation as a full step. Cached tokens and unmeasured decision/retrieval calls also distort economics.

Require each study arm to declare the same *non-negotiable* host principal, permissions, available tools/flows, source corpus, possible tool facts, host facts, side-effect approval policy, maximum tool calls and maximum wall time. Different **document-access paths, initial context or cache regimes** are allowed only as named, explicitly justified *experimental treatments*, not silent confounds.

## Run locally

```sh
python -m unittest tests.test_parity
python -m turnwise_lab.parity fixtures/benchmark-parity-example.json
```

The example is **fabricated for schema/unit tests**. Its recorded durations, tokens and event sequence do **not** come from a model benchmark and are not comparisons of performance. The command exits nonzero for blockers and prints:

- `structural_parity_passed`: whether the **declared** setup and events satisfy these checks, not whether any scientific hypothesis passed;
- `blockers`: mismatches, undeclared retrieval differences, missing receipts, unknown prompt sources, insufficient accounting or exceeded budgets;
- `declared_treatments`: differences explicitly designated as independent variables (do not merge with the primary parity comparator without labeling);
- `arm_summaries`: reported counts and tokens, *sum of event durations* (not wall time), elapsed wall time and cost only when all events carry known amounts.

Do **not** map a missing `billed_usd` to 0. It remains `null`; a genuinely offline/local run may have no provider charge but still consumes measured compute.

## Minimal manifest contract: `turnwise-comparison-parity/v1`

A manifest has `schema_version`, `declared_treatments: [{field, reason}]`, and at least two `arms`.

Each arm provides:

- `id`, `principal`, `permissions`, `capabilities`, `available_documents`, `available_tool_facts`, `host_facts`, `approval_policy`, `max_tool_calls`, `max_wall_ms`;
- `document_access_mode`, `initial_context_sources`, `cache_regime` for visibility into intended experimental differences;
- `wall_ms`, a complete `declared_event_counts` map for `decision`, `context`, `retrieval`, `tool`, `workflow` and `model`, plus ordered `events`.

Every event has `kind`, `duration_ms` and `billed_usd` (number or `null` for unavailable). Every `decision`, `context` or `model` event also records `input_tokens_new`, `input_tokens_cached` and `output_tokens` (zero is valid for deterministic choices). `retrieval`, `tool` and `workflow` events include `source_ids`, possibly empty. Every `model` event includes `prompt_source_ids`. A source cannot appear in a model prompt unless it was declared initially, supplied as a host fact, or entered through a prior retrieval/tool/workflow receipt. Sources must come from the declared corpus/tool-fact universe.

An **internal implicit document lookup must emit a retrieval receipt** even if no public `search_runbooks` tool was called. A `model` prompt with a document ID but no earlier evidence receipt fails. Source IDs should be stable identifiers or content hashes, not actual private document contents. The simple source checks do not validate whether that content was truthful or authorized to be disclosed; real data security remains a separate host responsibility.

The comparison uses **tool invocations**, not a vague common notion of "step": independent model rounds, controller decisions and retrieval events are separately counted. It deliberately does not require the two arms to make the *same* decisions or incur the *same* expense; those are outcomes to measure, not parity preconditions.

## What this cannot prove

- An arm can omit an operation from *both* its declared counts and its receipts; no static checker can observe invisible work. Future instrumentation should emit these events from shared host adapters, not from self-reported benchmark summaries.
- The checker cannot prove real prompt bytes, tokenization, cache use, data residency or wall-clock comparability. It cannot certify response correctness, independence of scenario authors, adequate sample size, model equivalence, statistical non-inferiority or absence of unrequested actions.
- A validated manifest is **not** permission to call hosted providers, spend money, publish claims, merge v0.6, or approach framework maintainers.

## Next integration step (not implemented here)

When #6 and the #11–#13 safety gates are reviewed, add a **non-invasive, versioned trace exporter** on a separately reviewed branch. It should emit true tool/retrieval/source receipts and controller/model costs for each executed arm, without editing frozen historical v0.5/v0.6 records. Run this preflight on separately authored prospective sessions before independent grading and analysis under #9. Preserve the [#5](https://github.com/dgenio/turnwise-decision-lab/issues/5) research HOLD.
