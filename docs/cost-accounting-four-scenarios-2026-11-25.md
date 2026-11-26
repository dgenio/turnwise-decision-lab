# Cost structure over the four demo scenarios, 2026-11-25

**Status: Demonstrated with simulated inference (structural).** Offline, provider double, simulated replies, synthetic token counts. This is arithmetic about request shapes under stated billing assumptions. It is **not** a cost measurement and it says nothing about quality or latency. Issue: [#85](https://github.com/dgenio/turnwise-decision-lab/issues/85); first snapshot: [cost-accounting-2026-11-21.md](cost-accounting-2026-11-21.md).

## Why this exists

Issue #85 pre-declared a falsifier for its hypothesis:

> **H:** under cache-aware billing and a batching native agent, Turnwise Core has no input-cost advantage on the showcase.
>
> **Falsified if** the structural estimate at realistic prefix size shows B at least 15% below A' in billed cost, aggregated over the four demo scenarios.

The first report covered `investigate` only, so the falsifier was "not evaluated as written". This run evaluates it.

## How the rule was fixed before the result

The words "realistic prefix size" and "billed cost" needed an operational meaning. It was fixed in code (`FALSIFIER_RULE` in `examples/architecture/cost_structure.py`) and pushed as commit `397804c` **before any four-scenario number was computed**:
- **Deciding rows:** the 5,000- and 20,000-token stable-prefix rows, under both cache-aware assumptions, with the 1,024-token minimum cacheable length applied. No-caching rows are reported but do not decide.
- **Verdict, per framework:**
  - **FALSIFIED** if B vs A' is at or below -15% in every deciding row;
  - **CONSISTENT** if it is above -15% in every one;
  - **MIXED** otherwise.
- **Aggregation:** each arm's structural USD is summed over the four scenarios (`investigate`, `status`, `severity`, `rollback`), one run each, so the scenarios weigh equally.

## Result

| | openai-agents | llamaindex |
|---|---|---|
| #85 falsifier, as written | **FALSIFIED** | **FALSIFIED** |
| B vs A', deciding rows | -46%, -46%, -49%, -49% | -46%, -46%, -49%, -49% |

**The saving comes entirely from two scenarios in which Turnwise Core makes no model call.**

| B vs A' per scenario (deciding rows) | What B did |
|---|---|
| `investigate`: **+2% to +8%** | 2 model calls; A' also made 2 |
| `status`: **-4% to -5%** | 1 model call; A' made 2 |
| `severity`: **-100%** | 0 model calls: the host answered from its own incident record (`answered_directly`) |
| `rollback`: **-100%** | 0 model calls: the host held the write request (`held`) |

On the two scenarios where a model is used, B is never 15% below A'.

### A post-hoc comparison, labelled as such

The report adds one row that was **not pre-declared**: A' with the host's no-model shortcuts. Wherever Turnwise Core sent no request, this row charges the batched native agent nothing either, as if the same deterministic front door ran before it. Elsewhere it charges A' as measured.

| Deciding row | openai-agents: B vs A' with the front door | llamaindex |
|---|---|---|
| 5,000-token prefix, cache reads discounted | +2% | +2% |
| 5,000, cache reads discounted, fresh input at the write price | +2% | +3% |
| 20,000, cache reads discounted | -1% | -1% |
| 20,000, cache reads discounted, fresh input at the write price | -1% | -0% (-0.5%) |

## Reading

1. **The falsifier fired, and H is false as written.** On the four-scenario mix, Turnwise Core's structural cost is about half the batching agent's.
2. **The cause is skipping the model, not steering it.** The whole difference comes from the two requests the host settles without a model. Give the native agent the same front door and the difference is within about 3%.
3. **Those shortcuts are host rules, not per-step control.**
   - The severity answer comes from `TriagePolicy`'s keyword rule.
   - The rollback hold comes from the host's lexical write-intent check.
   - A native agent behind the same host rules, the "shielded native agent" of [#88](https://github.com/dgenio/turnwise-decision-lab/issues/88), would get the same saving.
   - These are also the rules the red-team review ([#94](https://github.com/dgenio/turnwise-decision-lab/issues/94), criticism D) calls brittle, and v0.5 showed such rules failing silently on paraphrases. Cost here says nothing about whether they route correctly.
4. **The aggregate depends on the mix.** Two of the four demo scenarios are host-answerable by design. The same author wrote the scenarios, the rules and the simulated model. Another mix gives another number; the per-scenario rows are the portable part.
5. **This is consistent with the outside evidence #85 cites.** If turn count drives cost ([TurnCost](https://arxiv.org/abs/2610.15093)), removing whole model turns is the lever, and that is what happened here. It is a property of the front door, available to any architecture.

## What this does not show

- **No measurement.** There is no real cost: token counts are the double's `bytes // 4`, and prices are operator-supplied. Every reply is simulated, and a real model may batch differently or not at all.
- **Nothing on quality or latency.** In particular, nothing about whether the keyword and lexical rules route real requests correctly.
- **The front-door row is derived, not run.** It comes from B's request counts, not from an implemented native agent with a front door. Implementing that arm, as #88 proposes, would turn it into a measurement of the same structural kind.

## Snapshot

Produced on 2026-11-25 with Python 3.13.18, openai-agents 0.25.0, llama-index-core 0.14.26, llama-index-llms-openai 0.9.0, openai 3.59.0 and pydantic 2.14.4. Price card: the one recorded for `gpt-6.1-sol` in the [decision packet](live-smoke-decision-packet.md), operator-supplied. As with the first snapshot, request sizes depend on how those packages serialise requests, so this output is a dated record and is **not** compared byte for byte in CI. The tests pin the mechanisms and the rule instead. Two runs in a row gave identical output.

```text
Cost structure over the demo scenarios | PROVIDER DOUBLE (simulated responses; no inference performed)
SIMULATED, structural: request shapes come from the offline provider double, token counts are synthetic and replies are simulated. Arithmetic under stated assumptions, NOT a cost measurement.
scenarios investigate, status, severity, rollback | price card: input $2, cached input $0.1, cache write $2.5, output $10 per MTok (docs/live-smoke-decision-packet.md (gpt-6.1-sol; prices read 2026-11-19))

Issue #85's pre-declared falsifier: H (Turnwise Core has no input-cost advantage over a batching native agent) is falsified if, at realistic prefix size, B is at least 15% below A' in billed cost aggregated over the four demo scenarios. Operationalised before the four-scenario numbers were computed: realistic prefix size means the 5,000- and 20,000-token stable-prefix rows; billed cost means both cache-aware assumptions with the minimum cacheable length applied. Per framework, the verdict is FALSIFIED if B vs A' is at or below -15% in every one of those rows, CONSISTENT if it is above -15% in every one, and MIXED otherwise. No-caching rows are reported but do not decide.

=== openai-agents: what each arm did, per scenario (requests; how the run ended; mechanism verdict) ===
investigate  | A 4 req, completed (SDK final_output), PASS | A' 2 req, completed (SDK final_output), PASS | B 2 req, finished, PASS
status       | A 2 req, completed (SDK final_output), PASS | A' 2 req, completed (SDK final_output), PASS | B 1 req, finished, PASS
severity     | A 1 req, completed (SDK final_output), INCONCLUSIVE | A' 1 req, completed (SDK final_output), INCONCLUSIVE | B 0 req, answered_directly, INCONCLUSIVE
rollback     | A 2 req, completed (SDK final_output), INCONCLUSIVE | A' 2 req, completed (SDK final_output), INCONCLUSIVE | B 0 req, held, INCONCLUSIVE
(B with 0 requests: the host answered or held the request without a model call. A mechanism verdict of INCONCLUSIVE there only means no provider response was exercised.)

=== openai-agents: summed over the 4 scenarios (USD, arithmetic) ===
stable prefix | assumption                                                         | min cacheable |         A A-batched         B |  B vs A B vs A-b | B vs A-b per scenario
            0 | no caching                                                         |           n/a |   0.01942   0.01589   0.01009 |    -48%     -36% | investigate +21%, status -35%, severity -100%, rollback -100%
            0 | cache reads discounted                                             |       ignored |   0.01229   0.01214   0.00870 |    -29%     -28% | investigate +24%, status -6%, severity -100%, rollback -100%
            0 | cache reads discounted                                             |          1024 |   0.01942   0.01589   0.01009 |    -48%     -36% | investigate +21%, status -35%, severity -100%, rollback -100%
            0 | cache reads discounted, fresh input billed at the cache-write price |       ignored |   0.01398   0.01383   0.00998 |    -29%     -28% | investigate +27%, status -4%, severity -100%, rollback -100%
            0 | cache reads discounted, fresh input billed at the cache-write price |          1024 |   0.01998   0.01645   0.01132 |    -43%     -31% | investigate +29%, status -35%, severity -100%, rollback -100%
         5000 | no caching                                                         |           n/a |   0.10942   0.08589   0.04009 |    -63%     -53% | investigate +5%, status -48%, severity -100%, rollback -100%
         5000 | cache reads discounted                                             |          1024 |   0.05479   0.05364   0.02920 |    -47%     -46% | investigate +8%, status -5%, severity -100%, rollback -100%
         5000 | cache reads discounted, fresh input billed at the cache-write price |          1024 |   0.06648   0.06533   0.03548 |    -47%     -46% | investigate +8%, status -4%, severity -100%, rollback -100%
        20000 | no caching                                                         |           n/a |   0.37942   0.29589   0.13009 |    -66%     -56% | investigate +2%, status -49%, severity -100%, rollback -100%
        20000 | cache reads discounted                                             |          1024 |   0.18229   0.17814   0.09070 |    -50%     -49% | investigate +2%, status -5%, severity -100%, rollback -100%
        20000 | cache reads discounted, fresh input billed at the cache-write price |          1024 |   0.22398   0.21983   0.11198 |    -50%     -49% | investigate +3%, status -4%, severity -100%, rollback -100%

#85 falsifier, openai-agents: FALSIFIED (deciding rows, B vs A-batched: 5000 prefix / cache reads discounted: -46%, 5000 prefix / cache reads discounted, fresh input billed at the cache-write price: -46%, 20000 prefix / cache reads discounted: -49%, 20000 prefix / cache reads discounted, fresh input billed at the cache-write price: -49%)

POST HOC, not pre-declared: A' with the host's no-model shortcuts. Wherever Turnwise Core sent no request (the host answered from its own record, or held a write, before any model call), this row charges the batched native agent nothing either, as if the same deterministic front door ran before it. Elsewhere it charges A' as measured. It separates the saving from skipping the model entirely, which any agent behind the same host rules could have, from the saving of per-step control while a model is in use.
Scenarios Turnwise Core handled with no model call: rollback, severity
stable prefix | assumption                                                         | min cacheable | A-b + door         B | B vs it
            0 | no caching                                                         |           n/a |    0.01016   0.01009 |     -1%
            0 | cache reads discounted                                             |       ignored |    0.00767   0.00870 |    +14%
            0 | cache reads discounted                                             |          1024 |    0.01016   0.01009 |     -1%
            0 | cache reads discounted, fresh input billed at the cache-write price |       ignored |    0.00864   0.00998 |    +16%
            0 | cache reads discounted, fresh input billed at the cache-write price |          1024 |    0.01072   0.01132 |     +6%
         5000 | no caching                                                         |           n/a |    0.05016   0.04009 |    -20%
         5000 | cache reads discounted                                             |          1024 |    0.02867   0.02920 |     +2%
         5000 | cache reads discounted, fresh input billed at the cache-write price |          1024 |    0.03464   0.03548 |     +2%
        20000 | no caching                                                         |           n/a |    0.17016   0.13009 |    -24%
        20000 | cache reads discounted                                             |          1024 |    0.09167   0.09070 |     -1%
        20000 | cache reads discounted, fresh input billed at the cache-write price |          1024 |    0.11264   0.11198 |     -1%

=== llamaindex: what each arm did, per scenario (requests; how the run ended; mechanism verdict) ===
investigate  | A 4 req, completed (FunctionAgent response), PASS | A' 2 req, completed (FunctionAgent response), PASS | B 2 req, finished, PASS
status       | A 2 req, completed (FunctionAgent response), PASS | A' 2 req, completed (FunctionAgent response), PASS | B 1 req, finished, PASS
severity     | A 1 req, completed (FunctionAgent response), INCONCLUSIVE | A' 1 req, completed (FunctionAgent response), INCONCLUSIVE | B 0 req, answered_directly, INCONCLUSIVE
rollback     | A 2 req, completed (FunctionAgent response), INCONCLUSIVE | A' 2 req, completed (FunctionAgent response), INCONCLUSIVE | B 0 req, held, INCONCLUSIVE
(B with 0 requests: the host answered or held the request without a model call. A mechanism verdict of INCONCLUSIVE there only means no provider response was exercised.)

=== llamaindex: summed over the 4 scenarios (USD, arithmetic) ===
stable prefix | assumption                                                         | min cacheable |         A A-batched         B |  B vs A B vs A-b | B vs A-b per scenario
            0 | no caching                                                         |           n/a |   0.01945   0.01594   0.01016 |    -48%     -36% | investigate +22%, status -35%, severity -100%, rollback -100%
            0 | cache reads discounted                                             |       ignored |   0.01233   0.01218   0.00874 |    -29%     -28% | investigate +24%, status -5%, severity -100%, rollback -100%
            0 | cache reads discounted                                             |          1024 |   0.01945   0.01594   0.01016 |    -48%     -36% | investigate +22%, status -35%, severity -100%, rollback -100%
            0 | cache reads discounted, fresh input billed at the cache-write price |       ignored |   0.01403   0.01388   0.01003 |    -28%     -28% | investigate +27%, status -4%, severity -100%, rollback -100%
            0 | cache reads discounted, fresh input billed at the cache-write price |          1024 |   0.02000   0.01649   0.01141 |    -43%     -31% | investigate +31%, status -35%, severity -100%, rollback -100%
         5000 | no caching                                                         |           n/a |   0.10945   0.08594   0.04016 |    -63%     -53% | investigate +5%, status -48%, severity -100%, rollback -100%
         5000 | cache reads discounted                                             |          1024 |   0.05483   0.05368   0.02924 |    -47%     -46% | investigate +8%, status -5%, severity -100%, rollback -100%
         5000 | cache reads discounted, fresh input billed at the cache-write price |          1024 |   0.06653   0.06538   0.03553 |    -47%     -46% | investigate +8%, status -4%, severity -100%, rollback -100%
        20000 | no caching                                                         |           n/a |   0.37945   0.29594   0.13016 |    -66%     -56% | investigate +2%, status -49%, severity -100%, rollback -100%
        20000 | cache reads discounted                                             |          1024 |   0.18233   0.17818   0.09074 |    -50%     -49% | investigate +3%, status -5%, severity -100%, rollback -100%
        20000 | cache reads discounted, fresh input billed at the cache-write price |          1024 |   0.22403   0.21988   0.11203 |    -50%     -49% | investigate +3%, status -4%, severity -100%, rollback -100%

#85 falsifier, llamaindex: FALSIFIED (deciding rows, B vs A-batched: 5000 prefix / cache reads discounted: -46%, 5000 prefix / cache reads discounted, fresh input billed at the cache-write price: -46%, 20000 prefix / cache reads discounted: -49%, 20000 prefix / cache reads discounted, fresh input billed at the cache-write price: -49%)

POST HOC, not pre-declared: A' with the host's no-model shortcuts. Wherever Turnwise Core sent no request (the host answered from its own record, or held a write, before any model call), this row charges the batched native agent nothing either, as if the same deterministic front door ran before it. Elsewhere it charges A' as measured. It separates the saving from skipping the model entirely, which any agent behind the same host rules could have, from the saving of per-step control while a model is in use.
Scenarios Turnwise Core handled with no model call: rollback, severity
stable prefix | assumption                                                         | min cacheable | A-b + door         B | B vs it
            0 | no caching                                                         |           n/a |    0.01017   0.01016 |     -0%
            0 | cache reads discounted                                             |       ignored |    0.00767   0.00874 |    +14%
            0 | cache reads discounted                                             |          1024 |    0.01017   0.01016 |     -0%
            0 | cache reads discounted, fresh input billed at the cache-write price |       ignored |    0.00864   0.01003 |    +16%
            0 | cache reads discounted, fresh input billed at the cache-write price |          1024 |    0.01072   0.01141 |     +6%
         5000 | no caching                                                         |           n/a |    0.05017   0.04016 |    -20%
         5000 | cache reads discounted                                             |          1024 |    0.02867   0.02924 |     +2%
         5000 | cache reads discounted, fresh input billed at the cache-write price |          1024 |    0.03464   0.03553 |     +3%
        20000 | no caching                                                         |           n/a |    0.17017   0.13016 |    -24%
        20000 | cache reads discounted                                             |          1024 |    0.09167   0.09074 |     -1%
        20000 | cache reads discounted, fresh input billed at the cache-write price |          1024 |    0.11264   0.11203 |     -0%

Nothing here measures answer quality, real cost or real latency. Token counts are synthetic and every reply is simulated; a real model may batch differently or not at all.
```

## Reproduce

```bash
pip install -r examples/architecture/requirements.txt
python -m examples.architecture.cost_structure --scenario all
```

Tests:
- `tests/test_architecture_cost_scenarios.py` (stdlib only) pins the rule, the aggregation arithmetic and the front-door row on hand-made data.
- `CostScenariosReportTests` in `tests/test_architecture_cost_accounting.py` runs all four scenarios offline, with network connections refused. It checks that every arm ran without error or executed write, that the no-model scenarios are exactly the ones the host answered or held, and that the verdict printed is the one the rule computes.
