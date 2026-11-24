# External research audit, 2026-11-21

**Status: Historical (accurate for its date). Dated external research, not evidence produced by this repository.** No model was called, no experiment was run and nothing was spent. Nothing here changes the status of any evidence layer in [release status](../release-status.md).

These five reports are the literature, documentation and market research behind the independent red-team review recorded in [#94](https://github.com/dgenio/turnwise-decision-lab/issues/94). They are archived as written so that the issues that cite them can be checked against their sources. Follow the repository rule for dated audits: do not rewrite the findings; add a dated note.

## The reports

| File | Scope | Size |
|---|---|---|
| [01-orchestration-prior-art.md](01-orchestration-prior-art.md) | Whether Turnwise Core is an established pattern: framework seams, named patterns, dialogue-policy ancestry, evidence on which control style wins | about 10,000 words, 78 sources |
| [02-model-routing.md](02-model-routing.md) | Model routing, cascades and adaptive inference; per-step routing inside agents; prompt caching, effort settings and price trends | about 12,900 words |
| [03-tools-and-context.md](03-tools-and-context.md) | Tool selection, execution and authorisation; candidate host benchmarks; context engineering and instruction selection; cache arithmetic | about 13,700 words |
| [04-decision-theory-and-evaluation.md](04-decision-theory-and-evaluation.md) | Metareasoning, control theory, shielding, AI control and systems analogies; evaluation science, sample sizes and a minimum credible design | about 18,900 words |
| [05-commercial-landscape.md](05-commercial-landscape.md) | Who already ships each product shape, evidence of willingness to pay, and whether any moat exists | about 9,100 words, 87 sources |

## How they were produced

- Each report was written on 2026-11-20 or 2026-11-21 by a separate AI research pass with web search and page fetching. Each pass was told to prefer primary sources, to open a page before citing it, to mark anything it could not open, and never to invent sources, quotes or numbers.
- The passes did not see each other's work. Overlap between them was not removed, and where two reports describe the same source they may differ in wording or level of detail.
- The repository is described as it stood on 2026-11-20. Later changes (the backlog consolidation into #9, the context-module exhibit on `main`, the strong-null experiment branch) are not reflected in the reports. The issues are.

## Verification flags

Each report states its own legend at the top. They differ:

| Report | Flags |
|---|---|
| 01 | VERIFIED, NOT VERIFIED; in the source table V, V-abs (abstract page only), NV |
| 02 | [F] full text or official page, [A] abstract only, [S] secondary source, [NV] not verified |
| 03 | Source type per row, with "abstract only" and NOT VERIFIED where they apply |
| 04 | V (primary document opened), VI (supported through another primary document), NOT VERIFIED |
| 05 | OPENED, NOT OPENED per numbered source |

A flag records what the research pass says it did. It is not an independent check.

## What the reviewer re-checked independently

The review that used these reports re-opened the following sources itself. Everything else rests on the research passes.

| Source | What was re-checked |
|---|---|
| [PostHog, "Not everything needs an LLM"](https://posthog.com/newsletter/decision-models) | Read in full: what decision models were used for, the stated limits, the reported numbers |
| [LangChain and NVIDIA, "How many of your agent's calls actually need a frontier model?"](https://langchain.com/blog/switchyard-agent-routing-benchmark) | Read in full: all three arms' accuracy and cost, judge share of spend, the authors' caveats |
| arXiv [2608.24358](https://arxiv.org/abs/2608.24358), [2610.15093](https://arxiv.org/abs/2610.15093), [2605.18859](https://arxiv.org/abs/2605.18859), [2611.13176](https://arxiv.org/abs/2611.13176) | Abstract pages only: existence, title, authors, dates and the abstract's own claims |
| arXiv [2604.27891](https://arxiv.org/abs/2604.27891), [2603.21354](https://arxiv.org/abs/2603.21354), [2408.02442](https://arxiv.org/abs/2408.02442) | Abstract pages only |
| [OpenAI function calling guide](https://developers.openai.com/api/docs/guides/function-calling), [OpenAI cookbook on reasoning items](https://developers.openai.com/cookbook/examples/responses_api/reasoning_items), [LiteLLM auto routing](https://docs.litellm.ai/docs/proxy/auto_routing) | The specific statements quoted in the issues |

## Known limits and corrections

- **Many 2026 sources are unreviewed preprints**, several single-author or workshop papers. Most agent-level routing studies use SWE-bench Verified.
- **Abstract-only reads are common.** Numbers attributed to a paper's body were not always confirmable from its abstract page. Three examples found during re-checking, all in report 02:
  - The Handoff Tax (2608.24358): the abstract confirms "recovers less than half of the LC-to-HC quality gap"; it does not name the benchmark. The SWE-bench Verified tables come from the full text.
  - TwinRouterBench (2605.18859): the abstract confirms the dataset and the "execution-verified target tier"; the figures for rule-based routers failing 38 and 39 of 40 trajectories come from the full text.
  - ShadowPrefill (2611.13176): the abstract confirms "KV caches are per model" and the prefix hit rates; the phrase "model switch tax" does not appear on the abstract page.
- **Vendor numbers are marketing unless stated otherwise**, and are labelled as such in the reports.
- **All arithmetic is labelled as arithmetic.** It derives figures from list prices or standard formulas. It measures nothing.
- **Prices, product behaviour and acquisition status change quickly.** Each page's read date is given in the reports.
- **Not verified at all:** each report ends with its own list.

## Where the findings went

| Issue | Reports it draws on |
|---|---|
| [#94](https://github.com/dgenio/turnwise-decision-lab/issues/94) Red-team reassessment (parent) | all |
| [#85](https://github.com/dgenio/turnwise-decision-lab/issues/85) Cache-aware accounting | 02, 03 |
| [#86](https://github.com/dgenio/turnwise-decision-lab/issues/86) Stage 0 headroom audit | 02, 05 |
| [#87](https://github.com/dgenio/turnwise-decision-lab/issues/87) Native tool-call interception | 01, 03 |
| [#88](https://github.com/dgenio/turnwise-decision-lab/issues/88) Shielded native agent as primary candidate | 01, 04 |
| [#89](https://github.com/dgenio/turnwise-decision-lab/issues/89) Public host benchmark and sample sizes | 02, 03, 04 |
| [#90](https://github.com/dgenio/turnwise-decision-lab/issues/90) Host authority on AgentDojo | 03, 04 |
| [#91](https://github.com/dgenio/turnwise-decision-lab/issues/91) Learned gates per decision type | 02, 04 |
| [#92](https://github.com/dgenio/turnwise-decision-lab/issues/92) Context modules: test or retire | 03 |
| [#93](https://github.com/dgenio/turnwise-decision-lab/issues/93) Outcome class and positioning | 01, 05 |

The one measurement the review made itself, the offline capture of what each architecture sends on the wire in the provider-double rehearsal, is recorded with its script in #85. It is not in these reports.

## What this audit does not show

Anything about Turnwise's quality, cost, latency or safety with a real model. Those remain **Not tested** (study gate [#9](https://github.com/dgenio/turnwise-decision-lab/issues/9)).
