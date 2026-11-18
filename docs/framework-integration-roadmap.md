# Framework integration roadmap — discussion-first, evidence-gated

**Status:** proposed outreach plan. No external framework issues have been opened. Framework extension APIs and existing features must be checked against current upstream documentation and code before proposing any changes. Avoid claims that these frameworks cannot already implement the pattern.

## Integration sequence
1. **LangGraph / LangChain (first candidate).** Prototype an opt-in decision node/middleware inside the agent execution loop, reusing graph state, tool execution, checkpointing and tracing. Establish whether existing conditional edges and middleware already provide an adequate solution. Ask maintainers whether a reusable typed step-policy abstraction is useful, rather than proposing another agent runtime.
2. **OpenAI Agents SDK.** Explore compatibility with existing agent loop, handoffs, tool approvals, model settings and tracing; preserve SDK host authorization. Identify extension seam or demonstrate why a wrapper would be insufficient.
3. **LlamaIndex.** Map workflow/agent execution and tool selection hooks; evaluate a typed policy at each observation boundary without duplicating workflow capabilities.
4. **Pipecat.** Treat as a separate real-time voice/pipeline use case. Examine streaming, interruptions, turn boundaries and strict latency budgets before claiming applicability.

## Readiness gates before upstream outreach
- [ ] Publish a versioned provider-neutral contract and reference adapter.
- [ ] Reproduce CI and traces, preserve the v0.6 negative findings and issue #5 release gates.
- [ ] Run a capable executed heavy-only baseline and same-model hybrid comparison with explicit cost authorization.
- [ ] Show prospective quality/safety evidence and total cost/latency; report negative results.
- [ ] Check each project's latest contribution guidelines, architecture, prior issues and equivalent APIs.
- [ ] Start with one tailored discussion; incorporate maintainer feedback before other repositories.

## Tailored discussion templates — drafts only
Each proposal should link to the spec, benchmark methodology and reproducible traces, state limitations up front, and ask whether an extension is desirable.

### LangGraph / LangChain
**Title:** Discussion: opt-in typed per-step execution policy inside agent loops?
We are investigating a framework-neutral Adaptive Agent Execution pattern, choosing deterministic tool execution, light inference or capable LLM reasoning at each observation boundary. LangGraph already supports conditional graph routing; the question is whether a reusable typed policy seam would help, without replacing existing nodes or authorization. Current experiments show substantial silent-error risks and do not establish non-inferiority. Would a small example integration and benchmark be useful? [link to spec and traces]

### OpenAI Agents SDK
**Title:** Discussion: policy hook for evidence-aware next-step execution in the agent loop?
We are exploring an optional typed policy controlling direct host-validated tools vs model invocation within one turn, while preserving the SDK's approvals, tools and tracing. This is research, not a claim of superiority; early experiments reveal missed evidence and dropped intents. Is there a supported extension point, or should this remain a compositional example? [link]

### LlamaIndex
**Title:** Discussion: reusable adaptive step policy for agent workflows?
Could an opt-in policy interface select direct tool calls, lightweight inference or capable agent reasoning after each tool observation, using existing workflow machinery? We would like to avoid duplicating current workflow routing and test whether a small reference integration is useful. Quality benefits remain unproven. [link]

### Pipecat
**Title:** Exploration: adaptive execution decisions within real-time voice pipelines?
This pattern is currently defined for agent step loops; Pipecat's streaming/interrupt semantics may make it a poor fit. Would a bounded policy decision at safe turn boundaries be useful, and what latency/interrupt constraints would rule it out? No benchmark claim yet. [link]

## Contribution strategy
Do not create issues merely to advertise a repository. Open a concrete technical discussion only after verifying a real gap and presenting a working minimal example. Do not promise maintainers a supported integration or claim that a Decision API is mandatory.
