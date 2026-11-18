# Why Turnwise Decision Lab exists

**Observed architectural pressure:** many ReAct/native-tool-calling agents ask a generative LLM to decide the next operation repeatedly, even when some steps need only a host-verified fact, a registered read tool or an existing deterministic workflow. An entry-point model router changes *which model is called*; it does not necessarily change **who decides each successive operation**.

Turnwise's central research question is whether a cheap **typed, per-step execution policy**, reinvoked after every observation, can preserve the complete task outcome while avoiding unnecessary generative control calls. A strong LLM remains available as a **tool-capable fallback**, and the host independently enforces authorization, evidence sufficiency, approval and execution. We do **not** claim to have invented conditional graphs, decision models, tool search or agent loops.

See the explicit [per-step hypothesis, illustrative trace, comparators and falsifiers](per-step-execution-hypothesis.md). The repository is a **small falsifiable engineering exhibit**, not a new agent framework. Its initial goal is to make five decisions inspectable:

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

> "Against a real heavy-only tool-calling agent, on independently held-out tasks, the candidate preserved end-to-end task success within the pre-registered non-inferiority margin while changing total cost per attempted task by X%, p95 end-to-end latency by Y%, and input tokens per unavoidable heavy call by Z%. These are the cases where it lost."

Only publish that sentence once the actual heavy-only baseline has run, **X/Y/Z** and paired quality uncertainty have been measured with exact source code, provider IDs, configurations, prices and raw per-turn receipts; the safety and statistical gates must be reported. The hypothesis does not require accuracy *improvement*, only a bounded, justified loss if efficiency improves materially. See [candidate v0.6 protocol](quality-constrained-efficiency-v06.md). The existing 8-case fixture replay is **not** such evidence: the simple rule baseline already matches the same 8/8 authored route labels with zero classifier calls. The six-turn exhibit is **not independent** evaluation data.

## What would falsify the idea?

- Direct host rules plus native model/tool routing achieve equivalent outcomes with fewer calls and less maintenance.
- Context selection loses relevant evidence or qualifications on consequential tasks.
- Error recovery and calibration consume the theoretical savings.
- External classification cannot satisfy the required data residency policy.
- A single extra classification call increases p95 end-to-end latency enough to erase advantages.

If these happen, do not expand the codebase. Publish the negative result and stop or focus on the one demonstrably useful slice.

## What v0.5 found

See [`reports/arena.md`](../reports/arena.md). On authored synthetic sessions, the no-model headroom was large: the oracle answers 80% of turns without a model. Session state was the coupling that unlocked follow-ups, but it also produced silent wrong answers. The route-aware context hypothesis was falsified. By the criteria above this is **HOLD / SHRINK**: the evidence supports studying the state–route coupling and its failure modes, not building a product.
