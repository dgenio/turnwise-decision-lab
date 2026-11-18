# Why One Turn, Four Paths exists

**Observed architectural pressure:** agents are often given a large tool catalog and too much prior context, then asked to reason about every small step. Model routers address part of the problem, but that doesn't automatically settle *whether to call a model*, *which previously reviewed operation to execute*, *which evidence is necessary* and *which approvals must remain outside a model's control*.

This repository is a **small falsifiable engineering exhibit**, not a new agent framework. Its initial goal is to make five decisions inspectable:

1. Is a verified host answer already available? Skip classifier and LLM.
2. Is an approved deterministic flow already sufficient? Propose it; don't implement a new workflow engine.
3. Is live evidence needed? Propose the relevant read capability and bounded source IDs.
4. Is reasoning needed? Propose the tier and context, with uncertainty-triggered escalation.
5. Is a side effect requested? Host policy must enforce approval, independently of probability.

A provider's native mechanism can be the *best* implementation of any or all of these steps. The experiment is useful only if it reveals a measurable, reproducible tradeoff.

## What is actually novel?

**No general novelty claim.** As of November 2026, LiteLLM Auto Router supports Jev and several classifier choices, and vLLM Semantic Router documents decision models for model/tool/context selection. Anthropic's Tool Search can defer tool schemas until needed. The experiment is positioned as an **independent comparison and executable explanation of per-turn decision contracts**, not an algorithm invented here.

Sources and live docs:

- LiteLLM Auto Routing: https://docs.litellm.ai/docs/proxy/auto_routing
- vLLM Semantic Router System One: https://github.com/vllm-project/semantic-router/blob/main/website/docs/system-one/get-started/overview.md
- vLLM Semantic Router overview: https://github.com/vllm-project/semantic-router/blob/main/website/docs/intro.md
- Anthropic deferred Tool Search: https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool
- PostHog decision-model deployment account (the prompt for this experiment): https://posthog.com/newsletter/decision-models

## What would be a publishable result?

Not a 99% fixture label score. A result such as:

> "Against fully configured native router and plain-rule baselines on held-out tasks, the additional per-turn context/flow gate increased end-to-end correctness by X with Y change in p95 latency, under a fixed task budget. These are the cases where it lost."

Only publish that sentence once **X** and **Y** have been measured with exact source code, provider IDs, configurations and raw per-turn receipts. The existing 8-case fixture replay is **not** such evidence: the simple rule baseline already matches the same 8/8 authored route labels with zero classifier calls. The six-turn exhibit is **not independent** evaluation data.

## What would falsify the idea?

- Direct host rules plus native model/tool routing achieve equivalent outcomes with fewer calls and less maintenance.
- Context selection loses relevant evidence or qualifications on consequential tasks.
- Error recovery and calibration consume the theoretical savings.
- External classification cannot satisfy the required data residency policy.
- A single extra classification call increases p95 end-to-end latency enough to erase advantages.

If these happen, do not expand the codebase. Publish the negative result and stop or focus on the one demonstrably useful slice.
