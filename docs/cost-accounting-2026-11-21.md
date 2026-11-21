# Cache-aware accounting of the showcase, 2026-11-21

**Status: Demonstrated with simulated inference (structural).** Offline, provider double, simulated replies, synthetic token counts. This is arithmetic about request shapes under stated billing assumptions. It is **not** a cost measurement and it says nothing about quality or latency. Issue: [#85](https://github.com/dgenio/turnwise-decision-lab/issues/85).

## Why this exists

The demo's side-by-side counts operations: four model responses for the conventional agent, two `CALL_HEAVY` steps for Turnwise Core. A count of model calls is not what a provider bills. Two things decide the bill and neither is visible in a call count:

1. **Prompt caching.** Caches match an exact prefix. A conventional agent appends to its conversation, so most of each request repeats the previous one. Turnwise Core builds a fresh packet for each model step.
2. **Batched tool calls.** Tool-calling APIs let a model ask for several tools in one response. The demo's simulated model asks for one per response, which is the least favourable behaviour for the conventional arm.

## What is implemented

| Piece | Where | What it does |
|---|---|---|
| Billing units | `examples/architecture/cost_accounting.py` | One schema (`turnwise-billing/v1`) for reported usage: fresh input, cache reads, cache writes, output. A value the provider did not report is `None`, never `0`. Every smoke record now carries it as `billing` |
| Request shape | `ProviderLedger` (`Exchange.structure`) | For every admitted request: the length of its canonical text and how much of it is an exact prefix of the previous request. Text lengths, not tokens |
| Batched native arm | `SimulatedInvestigator(batch_reads=True)`, `ProviderDouble` | The same simulated investigator asks for all its evidence reads in one response. Off by default: the demo, its sample output and the smoke matrix are unchanged |
| Report | `python -m examples.architecture.cost_structure` | Runs three arms per framework against the provider double and prices their shapes under three billing assumptions, with a stable-prefix sensitivity and a minimum cacheable length |

The three arms share the task, tools, host and simulated model:

- **A**: the conventional agent, one tool call per response.
- **A'**: the same agent when the model batches its evidence reads.
- **B**: the same agent under Turnwise Core.

## Snapshot

Produced on 2026-11-21 with openai-agents 0.25.0, llama-index-core 0.14.26, llama-index-llms-openai 0.9.0, openai 3.57.0, pydantic 2.14.4. The request sizes depend on how those packages serialise requests and schemas, so this output is recorded here as a dated snapshot and is **not** compared byte for byte in CI. The tests pin the mechanisms instead (see below). Price card: the one recorded for `gpt-6.1-sol` in the [decision packet](live-smoke-decision-packet.md), operator-supplied.

```text
Cost structure of the showcase task | PROVIDER DOUBLE (simulated responses; no inference performed)
SIMULATED, structural: request shapes come from the offline provider double, token counts are synthetic and replies are simulated. Arithmetic under stated assumptions, NOT a cost measurement.
scenario 'investigate' | price card: input $2, cached input $0.1, cache write $2.5, output $10 per MTok (docs/live-smoke-decision-packet.md (gpt-6.1-sol; prices read 2026-11-19))

=== openai-agents: what each arm sends ===
A  conventional agent
     requests            : 4  (sequential (1 tool call per response))
     request chars       : 2563, 3131, 3763, 4359
     prefix of previous  : -, 82%, 83%, 86%
     input tokens (synth): 670, 812, 970, 1119  | output tokens (synth): 262
A' conventional agent, batched reads
     requests            : 2  (batched (up to 3 tool calls per response))
     request chars       : 2563, 4371
     prefix of previous  : -, 59%
     input tokens (synth): 670, 1122  | output tokens (synth): 265
B  Turnwise Core
     requests            : 2  (no native tool calls (the model only proposes))
     request chars       : 4816, 4778
     prefix of previous  : -, 60%
     input tokens (synth): 1236, 1227  | output tokens (synth): 263

=== openai-agents: the same shapes under each billing assumption (USD, arithmetic) ===
stable prefix | assumption                                                         | min cacheable |         A A-batched         B |  B vs A B vs A-b
            0 | no caching                                                         |           n/a |   0.00976   0.00623   0.00756 |    -23%     +21%
            0 | cache reads discounted                                             |       ignored |   0.00513   0.00499   0.00617 |    +20%     +24%
            0 | cache reads discounted                                             |          1024 |   0.00976   0.00623   0.00756 |    -23%     +21%
            0 | cache reads discounted, fresh input billed at the cache-write price |       ignored |   0.00570   0.00555   0.00703 |    +23%     +27%
            0 | cache reads discounted, fresh input billed at the cache-write price |          1024 |   0.01032   0.00679   0.00879 |    -15%     +29%
         5000 | no caching                                                         |           n/a |   0.04976   0.02623   0.02756 |    -45%      +5%
         5000 | cache reads discounted                                             |          1024 |   0.01663   0.01549   0.01667 |     +0%      +8%
         5000 | cache reads discounted, fresh input billed at the cache-write price |          1024 |   0.01970   0.01855   0.02003 |     +2%      +8%
        20000 | no caching                                                         |           n/a |   0.16976   0.08623   0.08756 |    -48%      +2%
        20000 | cache reads discounted                                             |          1024 |   0.05113   0.04699   0.04817 |     -6%      +2%
        20000 | cache reads discounted, fresh input billed at the cache-write price |          1024 |   0.06170   0.05755   0.05903 |     -4%      +3%
Input-only break-even: B's input costs less than A's only if a cache read costs more than 0.35x the fresh input price (no write premium, minimum ignored).

=== llamaindex: what each arm sends ===
A  conventional agent
     requests            : 4  (sequential (1 tool call per response))
     request chars       : 2466, 2994, 3586, 4142
     prefix of previous  : -, 82%, 84%, 87%
     input tokens (synth): 681, 813, 961, 1100  | output tokens (synth): 262
A' conventional agent, batched reads
     requests            : 2  (batched (up to 3 tool calls per response))
     request chars       : 2466, 4150
     prefix of previous  : -, 59%
     input tokens (synth): 681, 1102  | output tokens (synth): 265
B  Turnwise Core
     requests            : 2  (no native tool calls (the model only proposes))
     request chars       : 4893, 4855
     prefix of previous  : -, 60%
     input tokens (synth): 1248, 1238  | output tokens (synth): 263

=== llamaindex: the same shapes under each billing assumption (USD, arithmetic) ===
stable prefix | assumption                                                         | min cacheable |         A A-batched         B |  B vs A B vs A-b
            0 | no caching                                                         |           n/a |   0.00973   0.00622   0.00760 |    -22%     +22%
            0 | cache reads discounted                                             |       ignored |   0.00513   0.00497   0.00618 |    +21%     +24%
            0 | cache reads discounted                                             |          1024 |   0.00973   0.00622   0.00760 |    -22%     +22%
            0 | cache reads discounted, fresh input billed at the cache-write price |       ignored |   0.00569   0.00554   0.00705 |    +24%     +27%
            0 | cache reads discounted, fresh input billed at the cache-write price |          1024 |   0.01028   0.00677   0.00885 |    -14%     +31%
         5000 | no caching                                                         |           n/a |   0.04973   0.02622   0.02760 |    -44%      +5%
         5000 | cache reads discounted                                             |          1024 |   0.01663   0.01547   0.01668 |     +0%      +8%
         5000 | cache reads discounted, fresh input billed at the cache-write price |          1024 |   0.01969   0.01854   0.02005 |     +2%      +8%
        20000 | no caching                                                         |           n/a |   0.16973   0.08622   0.08760 |    -48%      +2%
        20000 | cache reads discounted                                             |          1024 |   0.05113   0.04697   0.04818 |     -6%      +3%
        20000 | cache reads discounted, fresh input billed at the cache-write price |          1024 |   0.06169   0.05754   0.05905 |     -4%      +3%
Input-only break-even: B's input costs less than A's only if a cache read costs more than 0.36x the fresh input price (no write premium, minimum ignored).

How to read this: 'stable prefix' adds the same stable tokens (a larger system prompt and tool catalogue) to every request of every arm.
'min cacheable' is a provider's minimum cacheable prompt length; below it nothing is read from cache.
Latency is not modelled: fewer round trips is a real advantage over a sequential agent and none over one that batches.
Nothing here measures answer quality, real cost or real latency.
```

## What the snapshot shows

- **Turnwise Core's requests are larger, and reuse less.** Each of its two requests is larger than the largest conventional request, because the step contract, the output schema and the tool descriptions travel inside every packet. Its second request repeats about 60% of the first. The conventional agent's later requests repeat 82% to 87% of the previous one.
- **The sign of the comparison depends on the billing assumption.** Against the sequential conventional agent, Turnwise Core is about 23% cheaper with no caching, about 20% dearer when cache reads are discounted and the minimum cacheable length is ignored, and between level and about 6% cheaper once a stable prefix of 5,000 to 20,000 tokens is added.
- **Against a conventional agent that batches its reads, Turnwise Core is not cheaper in any row.** The batched arm makes the same two round trips.
- **The toy prompts are below typical minimum cacheable lengths.** With a 1,024-token minimum and no added prefix, nothing would be cached, which is why the rows with the minimum applied equal the no-caching row. The stable-prefix rows show the regime a real system prompt and tool catalogue would be in.

## What it does not show

- Real cost. Token counts are the double's `bytes // 4`, not a tokenizer's, and prices are operator-supplied.
- Whether a real model batches its reads on this task, or at all.
- Latency. Two round trips instead of four is a real advantage over a sequential agent and none over one that batches.
- Quality. Every reply is simulated.
- Anything beyond this one scenario.

## Tests

`tests/test_architecture_cost_accounting.py` pins mechanisms, not the verdict:

- an unreported value stays unknown, in units, totals and cost;
- the canonical request text ignores key order and transport settings, and an appended conversation keeps its prefix where a rebuilt packet does not;
- hand-computed costs under each assumption, the minimum cacheable length and a stable prefix;
- the batched arm really returns several tool calls in one response, reaches the same host reads and makes fewer requests; writes and answers are never batched;
- every report states, from the wire record, how its native arm issued tool calls;
- the default provider double and the committed sample output are unchanged.

## Reproduce

```bash
pip install -r examples/architecture/requirements.txt
```

```bash
python -m examples.architecture.cost_structure
```

Use `--cached-input-usd-per-mtok`, `--cache-write-usd-per-mtok`, `--min-cacheable-tokens` and `--stable-prefix-tokens` to change the assumptions.
