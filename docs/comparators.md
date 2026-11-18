# Relevant comparators — snapshot 2026-11-18

**This is a competitor/context map, not a claimed head-to-head experiment.** As of v0.5, **none** of these providers or routers has been executed by this repository.

Re-checked against primary documentation on 2026-11-18:

- **LiteLLM auto routing** routes between *models* (tiers, pools). Classification can be heuristic or keyword-based with zero API calls, or use an LLM, the JEV classifier or a custom plugin. The completion always goes to a model. ([docs](https://docs.litellm.ai/docs/proxy/auto_routing))
- **vLLM Semantic Router vision paper** ([arXiv 2603.21354](https://arxiv.org/abs/2603.21354), Chen et al., 2026). It describes a joint "(model, tool) selection" action space, and lists context options (full history, injected summaries, retrieval-first prefill) as router choices. These are presented as research opportunities, not evaluated results.
- A literature search found evaluations of model-only, tool-only and harness-level routing, but **no controlled comparison of joint per-turn routing against model-only routing**. Treat this as "not found", not "does not exist".

| Comparator | Supported / documented capability | Fair test required before claiming advantage |
|---|---|---|
| [LiteLLM Auto Router](https://docs.litellm.ai/docs/auto_router/) | Decision model (including Jev), heuristic and complexity-based routing, multi-turn context handling, evaluation on traffic | Route the same requests through deployed LiteLLM + recorded model/config; include classifier, retries and fallback costs |
| [vLLM Semantic Router](https://vllm-sr.ai/docs/overview/signal-driven-decisions/) | Signal-driven route decisions, model selection, context/tool-aware policies and extensible model runtimes | Use a supported actual recipe and runtime; keep identity, native policy and context eligibility equivalent |
| [Provider-native tools](https://developers.openai.com/api/docs/guides/tools) | Built-in function calling, MCP, tool search and deferred tool loading where supported | Run the provider's native feature, not a mock, against identical held-out tasks and eligible capabilities |
| Strong host-only baseline | Verified-answer bypass + reviewed workflow + hand-written rules, actual local read handlers | It must be allowed to win, with equal access to trusted host metadata and policies |
| Turnwise joint planning hypothesis | Path, model-tier proposal, context mode and separate host execution gate | Measure quality/latency/cost/context recall end-to-end; route-only synthetic accuracy is insufficient |

A fair experiment should separate (a) execution-path selection, (b) model-tier selection, (c) context selection, (d) authority / access checks, and (e) response generation. Native mechanisms may already cover all the relevant behavior and make a new layer redundant.

The current tiny trained baseline is **not** a meaningful competitor to Jev; it is a minimal no-network control showing how easy it is to overclaim based on authored synthetic prompts.

## Name/prior-art collision (important before promotion)

- A separate [`turnwise` PyPI package](https://pypi.org/project/turnwise/) already exists for evaluating conversational AI systems.
- A separate 2026 paper, [*TurnWise: The Gap between Single- and Multi-turn Language Model Capabilities*](https://arxiv.org/abs/2603.16759), uses the same word.
- [`turnwise-sdk` on PyPI](https://pypi.org/project/turnwise-sdk/) is also listed for conversation evaluations.
- Projects such as [AgentWeave](https://github.com/sauravsingla/agentweave) already describe pre-inference tool/agent routing.

This repo does not claim affiliation with any of them. `turnwise-decision-lab` is a descriptive research-repository working name, **not** a unique brand or novel algorithm. Consider a distinct brand if product development becomes a real goal; do not publish a package named simply `turnwise`.
