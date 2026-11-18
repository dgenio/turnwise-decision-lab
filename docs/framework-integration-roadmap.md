# Framework integration roadmap — discussion-first, evidence-gated

**Status (2026-11-18):** exploratory outreach plan; **no external issues opened**. An initial source-based review of LangGraph and LangChain Python APIs found existing composition points; **no missing upstream extension hook has been demonstrated**. This is not a tested adapter or a declaration that all host safety requirements are provided automatically. The other frameworks have not yet been audited.

## Integration sequence
1. **LangGraph / LangChain (first candidate).** **First implement with existing APIs, not an upstream hook proposal.** Start with an opt-in `StateGraph` composition: a policy node, explicit host gate nodes, light/heavy model nodes and an observation loop. Compare with `create_agent` middleware where possible. Do not confuse tool filtering/model swapping with validated direct-tool execution or bypassing an LLM step. Ask upstream only if a minimal implementation proves a specific, unreproducible capability gap.
2. **OpenAI Agents SDK.** Explore compatibility with existing agent loop, handoffs, tool approvals, model settings and tracing; preserve SDK host authorization. Identify extension seam or demonstrate why a wrapper would be insufficient.
3. **LlamaIndex.** Map workflow/agent execution and tool selection hooks; evaluate a typed policy at each observation boundary without duplicating workflow capabilities.
4. **Pipecat.** Treat as a separate real-time voice/pipeline use case. Examine streaming, interruptions, turn boundaries and strict latency budgets before claiming applicability.

## Initial upstream API fit (Python, checked 2026-11-18)

This is a **documentation/source check**, not a running compatibility test. It changes the default recommendation from *request a new framework hook* to *compose existing primitives first*. Check installed dependency versions and run the example before asserting behavior.

| Need in the AAE contract | Existing mechanism | Interpretation and guard |
| --- | --- | --- |
| Decide again after each observation | LangGraph `StateGraph.add_conditional_edges` and a loop back to the policy node; `Command(update=..., goto=...)` for update-and-route | **Already composable.** Do not mix a dynamic `Command` route with a static outgoing edge from the same node: both paths may execute. |
| Select heavy versus light generation | Separate graph nodes, or LangChain `create_agent` `wrap_model_call` middleware for dynamic model selection | **Already composable.** Middleware that swaps models is not evidence-aware direct execution by itself. |
| Filter available tools or inspect tool calls | LangChain `wrap_model_call` + `wrap_tool_call` and tools declared to `create_agent` | **Existing facility.** Filtering schemas is not authorization or a substitute for the host gate. |
| Bypass model generation for a host-verified fact | Dedicated LangGraph verification node returning a result only after referent/freshness/provenance checks; LangChain `before_model` also supports a guarded `jump_to="end"` | **Composition, not automatic verification.** An LLM assertion or controller score must never count as the fact receipt. |
| Execute a controller-proposed `CALL_TOOL` | Explicit host-validator/executor node; optionally integrate with `ToolNode` where its expected tool-call message contract is satisfied | **Do not feed arbitrary policy output directly to `ToolNode`** and assume it validated AuthN/AuthZ, intent, argument correctness or approvals. |
| Hold an action and resume on approval | LangGraph `interrupt()`, `Command(resume=...)`, checkpointer | **Existing facility with hazards.** The node restarts on resume; side effects before an interrupt/retry must be idempotent. Authorization must be rechecked when resuming. |
| Verify `DIRECT` / `FINISH` | Project-defined host sufficiency/provenance checks and an explicit terminal gate | **Not built in.** Correct referent, evidence coverage, unresolved action intent and safety remain application responsibilities. |

**Primary-source evidence:**
- [LangGraph graph API: routing, `Command` and edge semantics](https://docs.langchain.com/oss/python/langgraph/graph-api)
- [LangGraph workflows/agents: native tool-loop and `ToolNode` example](https://docs.langchain.com/oss/python/langgraph/workflows-agents)
- [LangChain custom middleware: `before_model`, `wrap_model_call`, `wrap_tool_call` and `jump_to`](https://docs.langchain.com/oss/python/langchain/middleware/custom)
- [LangChain tools: dynamic filtering and runtime context](https://docs.langchain.com/oss/python/langchain/tools)

### Smallest worthwhile implementation experiment

1. Build **one** LangGraph graph using native nodes/conditional edges. Policy outputs are proposals only; host validation executes tools and checks evidence/permissions. Include a conservative same-model heavy path and a native heavy-only graph as the comparator.
2. Run offline tests with fake tools and fake models: verified direct answer; stale/wrong-referent direct answer rejected; missing evidence escalated; unsupported causal conclusion blocked; unapproved write held **without losing the intent**; denied approval; idempotent resume; failed tool; retry and budget exhaustion; model/tool accounting.
3. Only if those pass, run an **optional dependency** integration smoke test pinned to a published LangGraph/LangChain version. Confirm each node transition and approval replay; this source audit alone does not satisfy that gate.
4. Compare the native composition with middleware. If there is no demonstrated missing capability, **do not open an upstream feature request**. If there is one, produce a minimal failing reproduction, version matrix, and maintainer-friendly question first.

The work above is **not** authorization to spend on hosted models, run the v0.7 evaluation, change frozen v0.6 traces, or approach external maintainers.

## Readiness gates before upstream outreach
- [ ] Publish a versioned provider-neutral contract and reference adapter.
- [ ] Reproduce CI and traces, preserve the v0.6 negative findings and issue #5 release gates.
- [ ] Run a capable executed heavy-only baseline and same-model hybrid comparison with explicit cost authorization.
- [ ] Show prospective quality/safety evidence and total cost/latency; report negative results.
- [ ] Check each project's latest contribution guidelines, architecture, prior issues and equivalent APIs (**LangGraph/LangChain: preliminary API inventory done; runnable integration and compatibility check still pending**).
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
