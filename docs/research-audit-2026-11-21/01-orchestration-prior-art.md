# Prior-art review: is "Turnwise Core" already an established pattern?

> **Status: dated external research note, archived 2026-11-21. Historical (accurate for its date).** Written by an AI research pass for the red-team review in [#94](https://github.com/dgenio/turnwise-decision-lab/issues/94). Research only: no model was called and no experiment was run by this repository. Verification flags are the author's own; the [audit index](README.md) says what was independently re-checked and lists known corrections. Do not rewrite this file; add a dated note instead.

Research date: 2026-11-20. Scope: skeptical prior-art search for an adversarial review. Research only; nothing in the repository was modified and nothing was posted.

## How to read this report

- **Verification method.** Every source marked VERIFIED was opened in this session. Web pages were read through a fetch tool that returns extracted text; short quotes are reproduced as that tool returned them. Three documents were additionally checked against locally extracted PDF text (OpenAI "A practical guide to building agents", Sutton "The Bitter Lesson", Jurafsky & Martin Appendix K).
- **NOT VERIFIED** means I could not open the primary source (HTTP error, empty page) or only saw a search snippet. Those items are leads, not evidence.
- arXiv abstract pages were opened for all papers; where I also read the full HTML this is stated. Numbers are given exactly as the source states them.
- Framework docs carry the version or date shown on the page I read. Where a page shows none, I say so. These APIs change quickly.
- "Not found" means not found by this search, not "does not exist".

## Bottom line

The Turnwise Core architecture is not new. Each of its five invariants is either a documented framework feature, a published design pattern, or a standard component of task-oriented dialogue systems that predates LLM agents. The closest single ancestor is the classic dialogue-manager loop (state tracker, then a small policy that picks the next act from a closed list, re-invoked after every action), which Rasa Core described in 2017 in nearly the same terms. The closest LLM-era relatives are Rasa CALM (2024), StateFlow (2024), 12-Factor Agents (2025) and the Dual-LLM / CaMeL / "action-selector" security patterns (2023 to 2025).

What I did not find is a credible, held-out, cost-accounted comparison of a non-generative per-step policy against a native agent loop and against "simple host rules plus the same agent" on general tool-using tasks. The two nearest 2026 papers point in opposite directions, and the strongest recent evidence on procedural tasks says external orchestration now hurts frontier models. Any novelty Turnwise has is therefore empirical, not architectural, and the prior on a positive result is weak.

The project's own `docs/comparators.md` (snapshot 2026-11-18) lists only model routers (LiteLLM, vLLM Semantic Router) and provider-native tools. It omits essentially all of the closest prior art identified below.

---

## 1. Native seams

### 1.0 The baseline: the raw API already "executes nothing"

OpenAI's function-calling guide (developers.openai.com, read 2026-11-20, no date on page) states: "When the model calls a function, you must execute it and return the result." Its five-step flow includes "Receive a tool call from the model" and "Execute code on the application side with input from the tool call". [VERIFIED: https://developers.openai.com/api/docs/guides/function-calling]

So for client-side tools, "the model executes nothing" is the default behaviour of the plain API. It becomes a design choice only when a developer opts into (a) an SDK's automatic loop or (b) provider-hosted tools. The OpenAI Agents SDK docs confirm the second exception exists: hosted and built-in execution tools "do not use this guardrail pipeline". [VERIFIED: https://openai.github.io/openai-agents-python/guardrails/]

Several SDKs document the "return the call instead of running it" mode explicitly:

- Vercel AI SDK: a tool's `execute` is "optional because you might want to forward tool calls to the client or to a queue". [VERIFIED: https://ai-sdk.dev/docs/ai-sdk-core/tools-and-tool-calling]
- PydanticAI: "When the model calls a tool that requires approval, the agent run will end with a" `DeferredToolRequests` output; externally executed tools raise `CallDeferred`. [VERIFIED: https://pydantic.dev/docs/ai/tools-toolsets/deferred-tools/]
- Claude Agent SDK: a `PreToolUse` hook may return `permissionDecision` "defer", after which "the turn ends with a result message whose `stop_reason` is `\"tool_deferred\"`". [VERIFIED: https://code.claude.com/docs/en/agent-sdk/hooks]

Answer to the sub-question: yes. "The model executes nothing" is, in substance, "do not use the SDK's auto-loop (or do not register execute functions)". Turnwise's typed `tool_proposal` outcome is the same idea expressed as structured output rather than native tool-call syntax, which 12-Factor Agents names as Factor 4, "Tools are just structured outputs" (title verified; factor body not opened).

The Anthropic Messages API tool-use page was not opened in this session: NOT VERIFIED for that specific API, though the Claude Agent SDK pages above were.

### 1.1 Seam matrix

Legend: Y = documented on a page I opened; C = true by construction because developer code owns the loop (no special API needed); P = partial; ? = not documented on the pages I read (not proof of absence).

| Framework (docs version/date read) | Host code runs after every model output | Host code runs after every tool result | Veto / replace / approve each tool call | Swap model per step | Non-LLM code can skip the model call |
|---|---|---|---|---|---|
| Raw Responses / Chat API (no date) | C | C | C | C | C |
| Vercel AI SDK (no version shown) | Y (`prepareStep`, manual loop) | Y | Y (`toolApproval`; no-`execute` tools) | **Y** (`prepareStep` returns `model`) | C in manual loop; ? in `prepareStep` |
| LangChain v1 middleware (notes up to `langchain>=1.5.0`) | Y (`after_model`) | Y (`wrap_tool_call`, `before_model`) | Y (`HumanInTheLoopMiddleware`: approve/edit/reject) | **Y** (`request.override(model=...)`) | **Y** (wrap hook may call handler "zero times") |
| LangGraph (no version shown) | C (node + conditional edge) | C | Y (`interrupt()`, `Command(resume=...)`) | C | C |
| OpenAI Agents SDK, Python (no version shown) | P (hooks observe; output guardrails) | P (`tool_use_behavior`, tool output guardrails) | Y (`needs_approval`, tool input guardrails) | **?** (only run-wide `RunConfig.model`) | ? |
| LlamaIndex Workflows (no version shown) | C | C | Y (`InputRequiredEvent` / `HumanResponseEvent`) | C | C |
| PydanticAI (no version shown) | Y (`Agent.iter`, `AgentRun.next`) | Y | Y (`requires_approval`, `ApprovalRequired`, `ToolDenied`) | ? | Y ("skip nodes based on your own logic") |
| DSPy 3.5.0 | C ("plain Python control flow") | C | ? | C | C |
| Microsoft Agent Framework (ms.date 2026-10-22) | Y (chat middleware, per model call) | Y (function middleware) | Y (function middleware, `MiddlewareTermination`, `approval_mode`) | ? | Y (set `context.result`, do not call `call_next`) |
| Haystack 3.5 | P (hooks, `exit_conditions`) | P | Y (`ConfirmationHook`: confirm/reject/modify) | ? | ? |
| Mastra (no version shown) | ? | ? | Y (`requireToolApproval`, `approveToolCall`, `declineToolCall`) | P (per request context) | ? |
| Google ADK (page tags "ADK Python v0.1.0 ...") | Y (`after_model_callback`) | Y (`after_tool_callback`) | Y (`before_tool_callback` skips and replaces) | ? | **Y** (`before_model_callback` returning `LlmResponse` skips the LLM) |
| AutoGen Core (stable docs, no version shown) | ? | ? | Y (intervention handler) | ? | ? |
| Claude Agent SDK (mentions TS SDK v0.3.317, Python v0.2.177) | P (`Stop`, `PostToolBatch` hooks) | Y (`PostToolUse`, `updatedToolOutput`) | Y (`PreToolUse` allow/deny/ask/defer, `updatedInput`, `canUseTool`) | P (`setModel()`, `PreModelSwitch` hook; not a per-step callback) | ? |
| Temporal AI cookbook (no date) | C (workflow code is the loop) | C | C | C | C |
| Restate (no date) | C | C | Y (durable approval promise) | C | C |
| Inngest AgentKit (no date) | Y (router "called after each agent runs") | P | ? | ? | **Y** (code-based router, "no LLM calls involved") |
| DBOS | NOT VERIFIED (docs URL returned 404) | | | | |
| Semantic Kernel filters | NOT VERIFIED (page not opened; superseded by Agent Framework above) | | | | |

### 1.2 Evidence per framework

**Vercel AI SDK.** "The `prepareStep` callback runs before each step in the loop" and can modify "settings (model, tools, messages, and more) between steps." The docs give a model-switch example under the heading "Switch models based on step requirements:" that returns a different `model` when `stepNumber > 2 && messages.length > 10`. `stopWhen` "controls when to stop execution when there are tool results in the last step." A hand-written `while` loop over `generateText` is documented as an alternative. Tool approval returns `tool-approval-request` parts; "The older `needsApproval` property on `tool()` definitions is deprecated" in favour of `toolApproval`. [VERIFIED: https://ai-sdk.dev/docs/agents/loop-control and https://ai-sdk.dev/docs/ai-sdk-core/tools-and-tool-calling] This is direct prior art for per-step model swap by ordinary host code.

**LangChain v1 / LangGraph.** Hooks: `before_model` ("Before each model call"), `after_model` ("After each model response"), `wrap_model_call` ("Around each model call"), `wrap_tool_call` ("Around each tool call"). For wrap hooks: "You decide if the handler is called zero times (short-circuit), once (normal flow), or multiple times (retry logic)." The dynamic-model section's key line is `return handler(request.override(model=model))`. Middleware can also "exit early" by returning `jump_to` with targets `'end'`, `'tools'`, `'model'`. [VERIFIED: https://docs.langchain.com/oss/python/langchain/middleware/custom]

Built-ins include `HumanInTheLoopMiddleware` ("Pause agent execution for human approval, editing, or rejection of tool calls before they execute"), `ModelCallLimitMiddleware`, `ToolCallLimitMiddleware`, `ModelFallbackMiddleware`, `LLMToolSelectorMiddleware`, and two beta entries requiring `langchain>=1.5.0`: `ModelRouterMiddleware` ("Use a decision model to choose the model for each agent run") and `AutoModeMiddleware` ("Use a decision model to block risky tool calls before they run"). The router is per agent run, not per step; the examples pass a `classifier` object. [VERIFIED: https://docs.langchain.com/oss/python/langchain/middleware/built-in] The HITL middleware runs "after the model generates a response but before any tool calls are executed" and requires a checkpointer. [VERIFIED: https://docs.langchain.com/oss/python/langchain/human-in-the-loop]

In LangGraph, "The routing function receives the current graph state" and "its return value is the name of the next node"; `Command` is for "when a single step must both update state and choose what runs next"; `interrupt()` suspends "at the exact point where interrupt is called". [VERIFIED: https://docs.langchain.com/oss/python/langgraph/graph-api and https://docs.langchain.com/oss/python/langgraph/interrupts] A Turnwise loop is a LangGraph with one policy node and conditional edges to tool, workflow, light-model, heavy-model, clarify, hold and finish nodes.

**OpenAI Agents SDK.** `tool_use_behavior` options: `"run_llm_again"`, `"stop_on_first_tool"`, `StopAtTools(...)`, `ToolsToFinalOutputFunction` ("A custom function that processes tool results and decides whether to end the run with a final output"). Tool input guardrails "can skip the call, replace the output with a message, or raise a tripwire"; tool output guardrails "can replace the output or raise a tripwire". Output guardrails: "A tripwire rejects the candidate final output." Limits stated in the docs: "tool guardrails do not apply to the handoff call itself", hosted tools are excluded, and "`Agent.as_tool()` does not currently expose tool-guardrail options directly." `needs_approval` accepts `True` "or provide an async function that decides per call"; pending approvals surface in `RunResult.interruptions`, and "Approval permits a tool call to execute; it does not guarantee exactly-once execution." [VERIFIED: https://openai.github.io/openai-agents-python/agents/ , /guardrails/ , /human_in_the_loop/]

The loop itself: "If the LLM produces tool calls, we run those tool calls, append the results, and re-run the loop." `RunConfig.model` "Allows setting a global LLM model to use"; `call_model_input_filter` edits the prepared input. The running-agents page documents no per-turn model selector and no hook that intercepts each model response before tools run. [VERIFIED: https://openai.github.io/openai-agents-python/running_agents/] This SDK, one of Turnwise's two demo hosts, has the weakest per-step seams of the frameworks surveyed, which can make a "native vs Turnwise" contrast look larger than it would against the AI SDK or LangChain.

**LlamaIndex Workflows.** "A workflow is an event-driven, step-based way to control the execution flow of an application." "Branches are ordinary `if` statements that return different event types." "Loops are steps that return an event handled by an earlier step." [VERIFIED: https://developers.llamaindex.ai/python/llamaagents/workflows/] Human-in-the-loop uses built-in `InputRequiredEvent` and `HumanResponseEvent`. [VERIFIED: https://developers.llamaindex.ai/python/framework/understanding/agent/human_in_the_loop/]

**PydanticAI.** "You can also drive the iteration manually by passing the node you want to run next to the `AgentRun.next(...)` method." "This allows you to inspect or modify the node before it executes or skip nodes based on your own logic". `UsageLimits` covers "tokens, requests, tool calls, and cost". [VERIFIED: https://pydantic.dev/docs/ai/core-concepts/agent/ ; first 100,000 characters of the page read]

**DSPy 3.5.0.** "Compose multiple Signatures into new modules with plain Python control flow." Signatures are "typed inputs and outputs". [VERIFIED: https://dspy.ai/]

**Microsoft Agent Framework.** Three middleware types. Function middleware "Intercepts function (tool) calls"; chat middleware "executes for **each model call**, including calls that send tool results back to the model". "Middleware can terminate execution early by setting `context.result` and raising `MiddlewareTermination`." Samples recommend `approval_mode="always_require"` in production. The page also points to "Agent Hooks" for "a standardized, fail-closed control boundary". [VERIFIED: https://learn.microsoft.com/en-us/agent-framework/user-guide/agents/agent-middleware ; ms.date 2026-10-22]

**Haystack 3.5.** `exit_conditions` default `["text"]`; `max_agent_steps` "Defaults to `100`". HITL: "A human can **confirm**, **reject**, or **modify** the parameters of each tool call in real time." Policies: `AlwaysAskPolicy`, `NeverAskPolicy`, `AskOncePolicy`. [VERIFIED: https://docs.haystack.deepset.ai/docs/agent and /docs/human-in-the-loop]

**Mastra.** `requireToolApproval` (per request) and `requireApproval` (per tool) pause a call; `approveToolCall()` / `declineToolCall()` resume it. The overview lists "Swap instructions or models based on request context". [VERIFIED: https://mastra.ai/docs/agents/agent-approval and /docs/agents/overview] Per-step model swap: NOT VERIFIED.

**Google ADK.** `before_model_callback`: "If the callback returns an `LlmResponse` object, then the call to the LLM is **skipped**." `before_tool_callback`: "If a dictionary (or `Map` in Java) is returned, the tool's `run_async` method is **skipped**." `after_tool_callback`: a returned dictionary "**replaces** the original `tool_response`." [VERIFIED: https://adk.dev/callbacks/types-of-callbacks/ ; characters 0 to 200,000 read]

**AutoGen Core.** The cookbook shows an intervention handler that intercepts `FunctionCall` messages, prompts "Do you want to execute the tool? (y/n): ", and raises `ToolException` on denial. [VERIFIED: https://microsoft.github.io/autogen/stable/user-guide/core-user-guide/cookbook/tool-use-with-intervention.html]

**Claude Agent SDK.** `PreToolUse` sets `permissionDecision` (`"allow"`, `"deny"`, `"ask"`, or `"defer"`) and `updatedInput`; `PostToolUse` can set `updatedToolOutput`. Permission evaluation order is hooks, deny rules, ask rules, permission mode, allow rules, then the `canUseTool` callback. Modes: `default`, `dontAsk`, `acceptEdits`, `bypassPermissions`, `plan`, `auto` ("A model classifier reviews actions such as shell commands and network requests"). A `TaskCompleted` hook example is "Require passing tests before a task closes". [VERIFIED: https://code.claude.com/docs/en/agent-sdk/hooks and /permissions] The loop remains model-controlled; these seams gate tools rather than choose the next operation.

**Durable-execution engines.** Temporal's recipe puts the loop in workflow code (`# The agentic loop`, `while True:`), with "invoking the LLM and invoking any functions/tools ... done within a Temporal Activity", and the branch `if item.type == "function_call":` made in workflow code. [VERIFIED: https://docs.temporal.io/ai-cookbook/agentic-loop-tool-call-openai-python] Restate: an agent can "wait on a durable approval promise, and resume exactly where it left off." [VERIFIED: https://docs.restate.dev/ai/patterns/human-in-the-loop] Inngest AgentKit: "A router is a function that gets called after each agent runs"; "Code-based routing is great when you want deterministic, predictable behavior"; "It's also the fastest option since there's no LLM calls involved"; returning `undefined` stops the network. [VERIFIED: https://agentkit.inngest.com/concepts/routers] DBOS: NOT VERIFIED.

**Managed policy layer.** Amazon Bedrock AgentCore Policy: "Every agent action through Amazon Bedrock AgentCore Gateway is intercepted and evaluated at the boundary outside of agent's code - ensuring consistent, deterministic enforcement". Policies are written in Cedar, with session-aware "temporal" conditions such as "requiring that an approval was granted before a transfer" or "keeping a running total under a budget". [VERIFIED: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy.html]

### 1.3 What the seams do not give you

1. **A default owner that is not a model.** In middleware and hook designs (LangChain `create_agent`, OpenAI Agents SDK, Claude Agent SDK, Haystack, ADK) the model remains the default proposer of the next step and host code filters it. In code-first designs (LangGraph, LlamaIndex Workflows, Temporal, DSPy, PydanticAI `iter`, Inngest code routers) host code is already the default owner. Turnwise Core is an instance of the second family, not a seam missing from it.
2. **A named closed operation enum with a decision record.** No framework ships Turnwise's exact eight-operation set. Rasa CALM ships a seven-command set (section 2.5). Multi-Head Latent Control ships a four-way resolution set plus an escalation decision (section 2.7).
3. **Light vs heavy model as a peer of "call a tool" in one decision.** Per-step model swap exists (AI SDK, LangChain), and "skip the model" exists (ADK, LangChain, code-first), but I found no framework that presents all of these as one typed decision. This is packaging.
4. **A specified learned non-generative policy.** Frameworks give the hook, not the policy. LangChain's beta `ModelRouterMiddleware` and `AutoModeMiddleware` take a `classifier`; the docs I read do not say whether it must be an LLM.

---

## 2. Named prior-art patterns

### 2.1 LLM-controlled loop (the thing Turnwise argues against)

- **ReAct** (Yao et al.; arXiv 2210.03629; ICLR camera-ready v3, 10 Mar 2023). Interleaved reasoning and acting; the abstract reports beating imitation and RL baselines on ALFWorld and WebShop by absolute success rates of 34% and 10% (paraphrased). [VERIFIED abstract: https://arxiv.org/abs/2210.03629]

### 2.2 Plan first, then execute without the model in the loop

- **Plan-and-Solve** (Wang et al.; ACL 2023; arXiv 2305.04091). A prompting method, not an agent architecture. [VERIFIED abstract]
- **ReWOO** (Xu et al.; arXiv 2305.18323; 23 May 2023; preprint). "detaches the reasoning process from external observations"; on HotpotQA the abstract reports 5x token efficiency and a 4% accuracy improvement (paraphrased). [VERIFIED abstract]
- **LLMCompiler** (Kim et al.; ICML 2024; arXiv 2312.04511). Planner, Task Fetching Unit, Executor; the abstract reports up to 3.7x latency speedup, up to 6.7x cost savings and up to about 9% accuracy improvement versus ReAct (paraphrased). [VERIFIED abstract] Prior art for Turnwise's "Decision, Preparation, Execution, Observation with parallelism where safe".
- **KAIJU** (Guerin & Guerin; arXiv 2604.02375; 31 Mar 2026; preprint). An "Executive Kernel" that "decouples the execution of agent workflows from the LLM reasoning layer", with "Intent-Gated Execution". Reports a latency penalty on simple queries versus ReAct; no figures in the abstract. [VERIFIED abstract]

Difference from Turnwise: these use an LLM planner once up front. Turnwise uses a non-LLM policy every step.

### 2.3 The opposite direction: give the model more orchestration control

- **CodeAct** (Wang et al.; ICML 2024; arXiv 2402.01030). Code actions outperform alternatives by "up to 20% higher success rate" across 17 LLMs. [VERIFIED abstract]
- **Anthropic, "Introducing advanced tool use"** (24 Nov 2025; vendor engineering blog). Programmatic Tool Calling: average usage dropped "from 43,588 to 27,297 tokens" (37%); internal knowledge retrieval 25.6% to 28.5%; a second benchmark 46.5% to 51.2%. [VERIFIED: https://www.anthropic.com/engineering/advanced-tool-use] Vendor-reported, internal evals.
- **Cloudflare, "Code Mode: the better way to use MCP"** (Varda & Pai; 26 Sep 2025; vendor blog). "Convert the MCP tools into a TypeScript API, and then ask an LLM to write code that calls that API." No benchmarks in the post; "The results are striking" is a marketing claim. [VERIFIED: https://blog.cloudflare.com/code-mode/]

These matter because the industry trend they represent runs against Turnwise's premise (section 3.2).

### 2.4 Practitioner guidance that already states the Turnwise stance

- **12-Factor Agents** (Dex Horthy, HumanLayer; GitHub; no date on page). Factors include 4 "Tools are just structured outputs", 8 "Own your control flow", 10 "Small, Focused Agents", 12 "Make your agent a stateless reducer". Good agents "are comprised of mostly just software"; many are "mostly deterministic code, with LLM steps sprinkled in at just the right points." Factor 8 calls for pausing "between the moment of tool selection and the moment of tool invocation" and dispatching on `next_step.intent`. [VERIFIED: https://github.com/humanlayer/12-factor-agents and the factor-08 file] Difference: in 12-Factor the LLM still emits `next_step`; code dispatches it.
- **Anthropic, "Building effective agents"** (Erik S. and Barry Zhang; 19 Dec 2024; vendor blog). Workflows are "systems where LLMs and tools are orchestrated through predefined code paths"; agents are where "LLMs dynamically direct their own processes and tool usage." Routing example: "Routing easy/common questions to smaller, cost-efficient models". Advice to "start by using LLM APIs directly." [VERIFIED: https://www.anthropic.com/engineering/building-effective-agents]
- **OpenAI, "A practical guide to building agents"** (PDF; no date in the document text; verified against locally extracted text). "Otherwise, a deterministic solution may suffice." "Not every task requires the smartest model—a simple retrieval or intent classification task may be handled by a smaller, faster model". "Every orchestration approach needs the concept of a 'run', typically implemented as a loop that lets agents operate until an exit condition is reached." Guardrail list includes "Tool safeguards" ("assigning a rating—low, medium, or high") and "Rules-based protections" ("Simple deterministic measures"). [VERIFIED: https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf]
- **Manus, "Context Engineering for AI Agents"** (Yichao 'Peak' Ji; 18 Jul 2025; vendor blog). A state machine "masks the token logits during decoding to prevent (or enforce) the selection of certain actions". "we've rebuilt our agent framework four times". [VERIFIED: https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus] A deterministic controller constraining the action set per state, implemented inside decoding.

### 2.5 Conversational AI and task-oriented dialogue: the closest ancestors

**Verdict on the hypothesis in the brief: confirmed.** A small policy choosing the next act from a closed set every turn is the textbook architecture of task-oriented dialogue systems.

- **Jurafsky & Martin, Speech and Language Processing, Appendix K "Frame-Based Dialogue Systems"** (draft of 19 Aug 2026; textbook). Section K.1.3, "Dialogue Policy: Which act to generate": "A more sophisticated dialogue policy can help a system decide when to answer the user's questions, when to instead ask the user a clarification question, and so on. A dialogue policy thus decides what dialogue act to generate." The appendix also covers the dialogue state tracker and a history of reinforcement-learned policies. [VERIFIED against extracted PDF text: https://web.stanford.edu/~jurafsky/slp3/K.pdf]
- **Rasa Core** (Bocklisch, Faulkner, Pawlowski, Nichol; arXiv 1712.05181; Dec 2017; NIPS Workshop on Conversational AI). Dialogue management is framed as classification: the system "predicts which action to take from a predefined list." The loop: the tracker receives the message; "The policy chooses which action to take next."; "The chosen action is logged by the tracker."; "The action is executed"; "If the predicted action is not 'listen', go back to step 3." An action can be an utterance or "an arbitrary function to execute." [VERIFIED: https://ar5iv.arxiv.org/html/1712.05181] This is Turnwise invariant 1 (policy regains control after every action) with a small classifier policy and a closed action list, nine years earlier.
- **Hybrid Code Networks** (Williams, Asadi, Zweig; ACL 2017; arXiv 1702.03274). "combine an RNN with domain-specific knowledge encoded as software and system action templates"; reported to "outperform two commercially deployed customer-facing dialog systems." [VERIFIED abstract] A small learned policy whose choices are constrained by developer code.
- **POMDP dialogue systems** (Young, Gašić, Thomson, Williams; Proceedings of the IEEE 101(5), 2013). Abstract verified via Microsoft Research: policy optimised "via a reward-driven process" over an explicit Bayesian model of uncertainty. [Abstract VERIFIED: https://www.microsoft.com/en-us/research/publication/pomdp-based-statistical-spoken-dialogue-systems-a-review/ ; full text NOT VERIFIED, the Cambridge PDF returned HTTP 403]
- **Alexa Conversations** (Acharya et al.; NAACL 2021 demos; arXiv 2104.09088; developer docs last updated 27 Nov 2023). "The runtime processes events and predicts the actions that should take place."; action prediction "predicts the next action type and action name to run."; for API actions the engine "Invokes an API in the skill endpoint." [VERIFIED: https://developer.amazon.com/docs/alexa/conversations/how-alexa-conversations-works.html and arXiv abstract]
- **Dialogflow CX** (Google Cloud docs; no date shown). A conversation "can be described and visualized as a state machine"; pages are states; routes are "called when an end-user input matches an intent and/or some condition"; fulfillment can include "Webhook calls". [VERIFIED: https://docs.cloud.google.com/dialogflow/cx/docs/basics]
- **Rasa CALM** (Bocklisch, Werkmeister, Varshneya, Nichol; arXiv 2402.12234; 19 Feb 2024; preprint; plus Rasa docs, undated). "LLMs are used to translate between the surface form of the conversation and a domain-specific language (DSL)." The output is "a short sequence of commands (typically 1-3)". "The dialogue manager executes the relevant business logic deterministically." LLMs "cannot directly remove or modify existing flows on the stack." Commands: `StartFlow`, `CancelFlow`, `SetSlot`, `ChitChat`, `KnowledgeAnswer`, `HumanHandoff`, `Clarify`. Docs: "LLMs keep the conversation fluent but don't guess your business logic." [VERIFIED: https://arxiv.org/html/2402.12234 and https://rasa.com/docs/learn/concepts/calm/]
  - Evaluation in the paper: 71 hand-written test conversations, GPT-4; pass rate 95.8% versus 47.9% for an intent-based Rasa baseline. The authors caution it "should not be overly relied upon as a quantitative guide." The baseline is an NLU bot, not an LLM agent.
  - Mapping to Turnwise: CALM matches invariants 2 and 3 (the model emits typed commands; deterministic code owns execution). It differs on who goes first: CALM calls the LLM on every user turn; Turnwise's policy may never call a model.
- **Parlant** (Emcie; GitHub README; undated; vendor). "On every turn, Parlant works out which of them the conversation has made relevant"; it "checks actions such as refunds before they run". "20x–100x cheaper to run, right off the bat" is an unsupported marketing claim. [README VERIFIED: https://raw.githubusercontent.com/emcie-co/parlant/HEAD/README.md ; docs site returned an empty page] Prior art for composing only the instructions relevant to the next step.

Why this lineage matters for review: dialogue policies worked because state was a small slot/intent feature vector. Industry moved the LLM into the understanding seat (CALM) precisely because hand-featurised state did not generalise. A Turnwise policy that must judge "is the evidence sufficient?" on open tasks faces the same state-representation problem. This is my analysis, not a sourced finding.

### 2.6 Security patterns that separate deciding from executing

- **Dual LLM** (Simon Willison; personal blog; 25 Apr 2023). The Controller is "regular software, not a language model"; the Quarantined LLM is "expected to have the potential to go rogue at any moment." Caveat: "this isn't a 100% reliable solution." [VERIFIED: https://simonwillison.net/2023/Apr/25/dual-llm-pattern/]
- **CaMeL** (Debenedetti et al.; attributed to Google DeepMind in Willison's 2025 update; arXiv 2503.18813; v1 24 Mar 2025, v2 24 Jun 2025; preprint). A privileged LLM writes a program from the trusted query; a quarantined LLM "that has no tool access" parses untrusted data; "a custom Python interpreter" enforces capability policies. The abstract reports solving 77% of AgentDojo tasks with provable security, compared with 84% for an undefended system (paraphrased). Overhead about 2.82x input and 2.73x output tokens (Claude 3.5 Sonnet, median task). Limits: "CaMeL also comes with a user burden"; one-bit exception side channel. [VERIFIED abstract and first 100,000 characters of https://arxiv.org/html/2503.18813]
- **Design Patterns for Securing LLM Agents against Prompt Injections** (Beurer-Kellner et al.; arXiv 2506.08837; v3 27 Jun 2025; preprint). Six patterns: Action-Selector, Plan-Then-Execute, LLM Map-Reduce, Dual LLM, Code-Then-Execute, Context-Minimization. Action-Selector "acts like an *LLM-modulated* 'switch' statement that selects from a list of possible actions." Trade-off noted: "Utility is reduced by cutting the feedback loop between query results and the LLM." No empirical experiments. [VERIFIED: https://arxiv.org/html/2506.08837 ; first 100,000 characters]
  - Turnwise's closed op set is an action-selector whose selector is not an LLM; its tool-less model step is a quarantined LLM.
- **AI Control** (Greenblatt, Shlegeris, Sachan, Roger; arXiv 2312.06942; v1 12 Dec 2023). Protocols combining an untrusted strong model (GPT-4), a trusted weak model (GPT-3.5) and limited human labour; the abstract names "trusted editing" and "untrusted monitoring". [VERIFIED abstract. The names "trusted monitoring" and "defer-to-trusted" are not in the abstract; body not opened.] Prior art for a host protocol that routes work between a light and a heavy model.
- **AgentSpec** (Wang, Poskitt, Sun; ICSE 2026; arXiv 2503.18666). A DSL of triggers, predicates and enforcement; the abstract reports preventing unsafe executions in over 90% of code-agent cases with millisecond-level overhead (paraphrased; no exact overhead figure). [VERIFIED abstract]
- **Progent** (Shi et al.; arXiv 2504.11703; v3 14 May 2026; preprint). Symbolic rules over tool names and arguments check every tool call deterministically (paraphrased); demonstrated in LangChain and the OpenAI Agents SDK. No figures in the abstract. [VERIFIED abstract]

### 2.7 State machines and explicit per-step controllers for LLM agents

- **StateFlow** (Wu, Yue, Zhang, Wang, Wu; arXiv 2403.11322; v5 14 Sep 2024; venue not listed on arXiv). Models task-solving as a state machine; transitions governed by heuristic rules or LLM decisions. It "achieves 13% and 28% higher success rates compared to ReAct in InterCode SQL and ALFWorld benchmark," with 5x and 3x less cost respectively. [VERIFIED abstract]
- **Behavior Trees Enable Structured Programming of Language Model Agents** (Kelley; arXiv 2404.07439; 11 Apr 2024; preprint). Introduces the Dendron library; case studies, not benchmarks. [VERIFIED abstract]
- **CoALA** (Sumers, Yao, Narasimhan, Griffiths; TMLR; arXiv 2309.02427). A framework with a structured action space and "a generalized decision-making process". [VERIFIED abstract]
- **Utility-Guided Agent Orchestration for Efficient LLM Tool Use** (Liu, Zhao, Xu; IEEE JCC 2026; arXiv 2603.19896). An explicit per-step policy that "selects among actions such as respond, retrieve, tool call, verify, and stop". The scorer is a heuristic formula, but "The LLM estimates the heuristic signals". On 200 HotpotQA examples with one retrieval tool: ReAct F1 0.2662 at 546.6 tokens; utility policy F1 0.236 at 1294.2 tokens. The authors state the controller "does not universally outperform strong free-form baselines." [VERIFIED: https://arxiv.org/html/2603.19896] The explicit controller was worse and more expensive than ReAct here.
- **Multi-Head Latent Control** (Ghasemabadi, Chen, Rashidi, Niu; arXiv 2607.14277; 15 Jul 2026; preprint). Two "lightweight control heads" on a frozen backbone. "A Capability Head predicts whether the current model can solve the instance" and, in agent loops, "decides at each step whether to remain local or escalate control." A Resolution Head selects among "Clarification, Tool Use, Abstention, or Direct Answering." Reported: large-model usage down by up to 90.7% on AndroidWorld and 27 to 53% on average; up to +158% relative score gain; 65.5% fewer missed-required tool calls. Works "without modifying the backbone or introducing an additional orchestration model." [VERIFIED abstract and first 100,000 characters of https://arxiv.org/html/2607.14277 ; limitations appendix not read] This is the closest academic match to Turnwise's closed set plus light/heavy escalation with a non-generative decider. It needs hidden-state access.
- **ToolOrchestra** (Su et al.; affiliation not checked; arXiv 2511.21689; 26 Nov 2025; preprint). An 8B orchestrator trained with RL to choose among models and tools: 37.1% on Humanity's Last Exam versus 35.1% for GPT-5, "2.5x more efficient"; "only about 30% of the cost" on τ²-Bench and FRAMES. [VERIFIED abstract] The controller is a small generative model, so this is "small model controls the loop", which Turnwise labels differently.
- **LedgerAgent** (Uddin, Saeidi, Blanco, Baral; arXiv 2606.20529; 18 Jun 2026; "Work in Progress"). Keeps observed task state in a ledger and checks state-dependent policy constraints before environment-changing tool calls; improved average pass^k in four customer-service domains; no figures in the abstract. [VERIFIED abstract]
- **JourneyBench** (Balaji, Mishra, Sachdeva, Agrawal; arXiv 2601.00596; 2 Jan 2026; preprint). A Dynamic-Prompt Agent that "explicitly models policy control" "significantly boosts policy adherence"; with it GPT-4o-mini can outperform GPT-4o; 703 conversations, three domains. [VERIFIED abstract]
- "Formally Specifying the High-Level Behavior of LLM-Based Agents" (arXiv 2310.08535): search snippet only. NOT VERIFIED.
- "Agent workflows as finite state machines": I found no source with this title. Not found.

---

## 3. Evidence on which control style wins

### 3.1 Evidence favouring structured or deterministic control

| Claim | Source | Strength and limits |
|---|---|---|
| FSM control beats ReAct by 13% / 28% success at 5x / 3x lower cost | StateFlow, 2024 | Preprint on arXiv; GPT-3.5/4-era models; two benchmarks |
| Planner plus executor: up to 3.7x faster, 6.7x cheaper, ~9% more accurate than ReAct | LLMCompiler, ICML 2024 | Peer-reviewed; "up to" figures; LLM planner, not a non-LLM policy |
| No-agent pipeline: 32.00% on SWE-bench Lite at $0.70, best open-source at the time | Agentless (Xia et al.; arXiv 2407.01489; v2 29 Oct 2024) | Preprint; a mid-2024 snapshot (see 3.2) |
| "SOTA agents are needlessly complex and costly" | AI Agents That Matter (Kapoor et al.; arXiv 2407.01502; 1 Jul 2024) | Preprint; an evaluation-methodology argument |
| Design-level isolation: 0 successful attacks versus 276 for GPT-4o Mini's native tool calling; utility 77% versus 84% | CaMeL, 2025 | Preprint; about 2.8x tokens; user burden |
| 12 recent model-level defenses bypassed, with attack success rates above 90% for most (paraphrased) | The Attacker Moves Second (Nasr et al.; arXiv 2510.09023; 10 Oct 2025) | Preprint; supports host-side authority by implication (my inference) |
| Function-calling agents succeed on under 50% of tasks; pass^8 under 25% in retail | τ-bench (Yao et al.; arXiv 2406.12045; 17 Jun 2024) | Documents the reliability gap; not a comparison of control styles |
| Explicit policy control lets GPT-4o-mini beat GPT-4o on adherence | JourneyBench, 2026 | Preprint; abstract only; no numbers |
| Ledger state plus pre-action policy checks improve pass^k | LedgerAgent, 2026 | Work in progress; no numbers in abstract |
| CALM $0.04 versus LangGraph $0.10 per message; 2.08 s versus 7.4 s; 1 of 5 LangGraph runs problem-free | Rasa blog, 8 Aug 2024 | **Vendor marketing.** GPT-4; sample sizes for cost and latency not stated; five conversations for consistency; baseline is a LangChain tutorial bot |
| Head-based escalation cuts large-model usage 27 to 53% on average | Multi-Head Latent Control, 2026 | Preprint; white-box heads |

[All VERIFIED at abstract level or better; Rasa blog: https://rasa.com/blog/cutting-ai-assistant-costs-the-power-of-enhancing-llms-with-business]

τ²-bench (Barres et al.; arXiv 2506.07982; 9 Jun 2025) reports "large performance drops" from no-user to dual-control settings but gives no figures in the abstract. [VERIFIED abstract] I found no τ-bench or τ²-bench paper that directly compares a state-machine controller with function calling under pass^k.

### 3.2 Evidence favouring model-controlled loops and thinner scaffolding

- **In-Context Prompting Obsoletes Agent Orchestration for Procedural Tasks** (Dennis, Diamond, Patil, Shabahang, Guo; arXiv 2604.27891; v2 5 May 2026; preprint). Same model, two conditions: whole procedure in the system prompt versus a LangGraph orchestrator that tracks state and injects routing instructions. Three domains (14, 14 and 55 nodes), 200 conversations per condition, LLM-as-judge. Quality 4.53 to 5.00 versus 4.17 to 4.84. Failure rates: travel 11.5% versus 24%; Zoom support 0.5% versus 9%; insurance 5% versus 17%, all in favour of no orchestration. The authors write "external orchestration may have been necessary for earlier models". [VERIFIED abstract] Limits: preprint, LLM judge, model unnamed in the abstract. This is the most direct counter-evidence to Turnwise's premise in exactly the procedural customer-service regime where structured control is supposed to be strongest.
- **Utility-Guided Agent Orchestration** (section 2.7): explicit per-step controller lost to ReAct on both F1 and tokens.
- **SWE-bench history.** mini-SWE-agent: "Just some 100 lines of python for the agent class", "Does not have any tools other than bash", "Scores >74% on the SWE-bench verified benchmark"; "as LMs have become more capable, a lot of this is not needed at all to build a useful agent!" [VERIFIED: https://github.com/SWE-agent/mini-swe-agent ; the README does not name the model] Anthropic reports Claude 3.5 Sonnet reached 49% on SWE-bench Verified in late 2024 with only bash and a text editor. Read with Agentless (32.00% on Lite in mid-2024), the workflow advantage on this benchmark did not persist. The benchmarks differ (Lite versus Verified), so this is a trend reading, not a controlled comparison.
- **Anthropic, "Harness design for long-running application development"** (Prithvi Rajasekaran; 24 Mar 2026; vendor blog). "every component in a harness encodes an assumption about what the model can't do on its own". After moving to Opus 4.6: "I started by removing the sprint construct entirely." But also: solo run 20 minutes and $9 versus full harness 6 hours and $200, where "the difference in output quality was immediately apparent"; and "the space of interesting harness combinations doesn't shrink as models improve." [VERIFIED: https://www.anthropic.com/engineering/harness-design-long-running-apps]
- **Anthropic, "Agent Harness Design: 3 Patterns for Harnessing Claude's Intelligence"** (Lance Martin; 2 Apr 2026; vendor blog). Assumptions "grow stale as Claude gets more capable." On code-based tool orchestration: "The orchestration decision moves from the harness to the model." It also says "Agent harnesses provide structure around Claude to enforce UX, cost, or security" and "hard-to-reverse actions such as external API calls can be gated by user confirmation." [VERIFIED: https://claude.com/blog/harnessing-claudes-intelligence]
- **Cognition, "Don't Build Multi-Agents"** (Walden Yan; 12 Jun 2025; vendor blog). "Share context, and share full agent traces, not just individual messages." "Actions carry implicit decisions, and conflicting decisions carry bad results." On 2024 designs where a small model applied a large model's edits: "these systems would still be very faulty." [VERIFIED: https://cognition.com/blog/dont-build-multi-agents] Directly relevant to Turnwise's light-model step and to composing only next-step context.
- **Manus** (section 2.4): four framework rebuilds; "If model progress is the rising tide, we want Manus to be the boat, not the pillar stuck to the seabed."
- **METR, "Measuring AI Ability to Complete Long Software Tasks"** (Kwa et al.; arXiv 2503.14499; NeurIPS 2025 per arXiv journal reference). Claude 3.7 Sonnet has a 50% time horizon of about 50 minutes; horizons have been "doubling approximately every seven months since 2019". [VERIFIED abstract] METR's time-horizons page (last updated 8 Sep 2026, no longer actively updated) gives GPT-5 at about 2 hours 17 minutes in text and warns that measurements above 16 hours are unreliable and tasks are "cleaner than most real work". [VERIFIED: https://metr.org/time-horizons/]
- **Sutton, "The Bitter Lesson"** (13 Mar 2019; personal essay). "general methods that leverage computation are ultimately the most effective, and by a large margin." [VERIFIED against a PDF copy hosted at cs.utexas.edu; incompleteideas.net returned HTTP 503] An argument by analogy, not evidence about agents.
- **Boris Cherny** is reported to have said scaffolding gains of roughly 10 to 20% are short-lived: "the gain is wiped out with the next model." Source: Arize blog (Laurie Voss, Sep 2026) citing a Y Combinator interview. [Secondary source VERIFIED: https://arize.com/blog/agent-harness-distillation/ ; primary interview NOT VERIFIED] The same article argues the surviving harness parts are "the ones tied to your specific tools, data and environment."
- Programmatic tool calling, Code Mode and CodeAct (section 2.3) improve token cost and accuracy by giving the model more orchestration control, not less.

### 3.3 Reading the evidence

1. **Security and authority: structured control wins, with a utility and token cost.** CaMeL is the strongest result. This supports Turnwise invariant 3 (host owns authority) and says nothing about invariant 1 (a non-LLM policy picks every step).
2. **Weak models and narrow procedures: structure helped in 2023 to 2024.** StateFlow, LLMCompiler, Agentless and JourneyBench's GPT-4o-mini result all fit this.
3. **Frontier models: the advantage of external step control shrinks or reverses.** Dennis et al. (2026), the SWE-bench trajectory and both Anthropic posts point this way. Vendors have an interest in "trust the model", so discount accordingly, but Dennis et al. is an academic preprint.
4. **Cost and latency: genuinely mixed.** Structure cut cost in StateFlow and in Rasa's vendor test; it raised cost in CaMeL (about 2.8x) and in Liu et al. (about 2.4x tokens versus ReAct).
5. **No study isolates Turnwise's variable.** None compares a non-generative per-step policy with (a) a native loop, (b) simple host rules plus the same agent, and (c) a checklist-prompted agent on held-out tasks with every policy call counted.

Unverified leads from search snippets only: a multi-agent failure taxonomy reporting specification failures at 41.8% and coordination failures at 36.9%; ServiceNow "AgentArch"; "Compiled AI" (arXiv 2604.05150). All NOT VERIFIED.

---

## 4. Verdict: what in Turnwise is not already covered?

### 4.1 Exists as a documented feature

| Turnwise element | Where it already exists |
|---|---|
| Model proposes, host executes (invariant 2) | Raw function-calling API; AI SDK tools without `execute`; PydanticAI `DeferredToolRequests`; Claude Agent SDK `defer` |
| Host regains control after every model output and tool result (invariant 1, mechanically) | LangChain `after_model` / `wrap_*`; AI SDK `prepareStep`; PydanticAI `Agent.iter`; ADK callbacks; LangGraph, LlamaIndex Workflows, Temporal by construction |
| Veto, rewrite or approve each tool call; writes held for approval | Every framework surveyed |
| Per-step light/heavy model swap by host code | AI SDK `prepareStep`; LangChain `request.override(model=...)` |
| Ordinary code decides not to call a model | ADK `before_model_callback`; LangChain wrap hook "zero times"; Inngest code router; any code-first loop |
| Budgets | `ModelCallLimitMiddleware`, `ToolCallLimitMiddleware`, PydanticAI `UsageLimits`, Haystack `max_agent_steps`, OpenAI `max_turns` |
| Terminal acceptance check before finishing | OpenAI output guardrails; Claude `TaskCompleted` / `Stop` hooks; LangChain `after_model` / `after_agent` |
| Authority outside agent code, deterministic, session-aware | AgentCore Policy (Cedar); Claude Agent SDK permission rules |
| Deterministic router invoked after each agent step | Inngest AgentKit code-based routers |

### 4.2 Exists as a published pattern

- Own the control flow; tools are structured outputs; stateless reducer: 12-Factor Agents.
- Workflow versus agent, routing to smaller models: Anthropic 2024; OpenAI guide.
- Closed action set chosen by a selector: Action-Selector pattern (Beurer-Kellner et al. 2025).
- Tool-less model handling data, controller in ordinary software: Dual LLM (2023), CaMeL (2025).
- Rule-governed transitions between LLM steps: StateFlow (2024); behaviour trees (2024).
- Decide, prepare, execute with safe parallelism: LLMCompiler (2024), ReWOO (2023), KAIJU (2026).
- Trusted-weak plus untrusted-strong model protocols: AI Control (2023).
- Explicit per-step choice among respond / retrieve / tool / verify / stop: Liu et al. (2026).
- Non-generative heads choosing escalate versus stay and clarify / tool / abstain / answer: Multi-Head Latent Control (2026).
- Per-turn composition of only the relevant instructions: Parlant (vendor); JourneyBench's Dynamic-Prompt Agent.

### 4.3 Exists in an adjacent field

- A small typed policy re-invoked after every action, choosing from a closed list, with a tracker holding state: task-oriented dialogue management (Jurafsky & Martin; Rasa Core 2017; Hybrid Code Networks 2017; Alexa Conversations; Dialogflow CX; POMDP systems).
- The LLM restricted to emitting typed commands that a deterministic manager executes: Rasa CALM (2024).

### 4.4 Apparently not studied (not found)

1. A held-out, cost-accounted experiment in which a **non-generative** policy owns **every** step of a **general tool-using** agent, with the three nulls the project already names. Nearest neighbours: Liu et al. (negative; LLM-estimated signals; one tool; 200 questions) and Multi-Head Latent Control (positive; white-box heads).
2. The specific composition: light-model call, heavy-model call, tool, workflow, clarify, hold and finish as peers in one decision, with a tool-less model step returning a three-way typed outcome that re-enters the policy. Each part is prior art; the combination as a tested unit was not found. This is a packaging difference.
3. Whether a small policy can judge evidence sufficiency and terminal acceptance on open tasks without an LLM. Dialogue-system history suggests state representation is the hard part.
4. Whether per-step context composition helps or harms when the policy, not the model, selects the context. Cognition's principles predict harm; Parlant and JourneyBench claim benefit for policy adherence. No controlled test found.

### 4.5 Blunt assessment

- **Architecture novelty: none of substance.** "Turnwise Core" is a dialogue-manager loop with model calls added to the action list, built from seams that are documented features. A reviewer could accurately call it "Rasa Core's policy loop plus 12-Factor's Factor 8, with CaMeL-style quarantine of the model step".
- **"The model executes nothing" is not a contribution.** It is the raw API's default.
- **Per-step model routing is not a contribution.** `prepareStep` and `request.override(model=...)` document it.
- **The only defensible research question is empirical:** does a cheap non-generative policy at every step beat (a) host rules plus the same capable agent and (b) the native loop, on held-out tasks, counting every call? The project's own framing ("the expected outcome is SHRINK/STOP") matches the state of the evidence.
- **The prior is unfavourable for frontier models on procedural tasks** (Dennis et al. 2026) and **favourable only for the authority/security slice**, which does not need a per-step policy to obtain.
- **Synthetic evidence cannot answer the question.** The decisive variable is how real model outputs interact with a policy's state featurisation, which simulated replies fix by construction.
- **Gap in the project's own documentation:** `docs/comparators.md` should add task-oriented dialogue policies, Rasa Core and CALM, StateFlow, 12-Factor Agents, Dual LLM / CaMeL / Action-Selector, Multi-Head Latent Control, Liu et al., Dennis et al., and the `prepareStep` / LangChain middleware / ADK callback seams.

---

## Source table

Type key: PR = peer-reviewed venue; PP = preprint; DOC = official docs; VB = vendor blog; PB = personal blog or essay; TB = textbook; GH = repository README. Status: V = opened and verified this session; V-abs = abstract page only; NV = not verified.

| # | Title | Authors / org | Date | URL | Type | Finding (as stated) | Limitations | Relevance | Status |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Function calling guide | OpenAI | no date | https://developers.openai.com/api/docs/guides/function-calling | DOC | "you must execute it and return the result" | Client tools only | Invariant 2 is the API default | V |
| 2 | AI SDK: Loop control | Vercel | no version | https://ai-sdk.dev/docs/agents/loop-control | DOC | `prepareStep` runs before each step; can switch model | No version on page | Per-step model swap | V |
| 3 | AI SDK: Tools and tool calling | Vercel | no version | https://ai-sdk.dev/docs/ai-sdk-core/tools-and-tool-calling | DOC | `execute` optional; `toolApproval` | `needsApproval` deprecated | Propose-only tools, approval | V |
| 4 | LangChain custom middleware | LangChain | notes to 1.3.15 | https://docs.langchain.com/oss/python/langchain/middleware/custom | DOC | wrap hooks call handler zero, one or many times; `request.override(model=model)`; `jump_to` | Model section is code only | Per-step swap; skip model | V |
| 5 | LangChain built-in middleware | LangChain | notes to 1.5.0 | https://docs.langchain.com/oss/python/langchain/middleware/built-in | DOC | HITL, call limits, fallback, `ModelRouterMiddleware` (beta), `AutoModeMiddleware` (beta) | Router is per run | Budgets, approval, routing | V |
| 6 | LangChain human-in-the-loop | LangChain | no date | https://docs.langchain.com/oss/python/langchain/human-in-the-loop | DOC | Runs after model, before tool execution | Needs checkpointer | Write approval | V |
| 7 | LangGraph graph API; interrupts | LangChain | no date | https://docs.langchain.com/oss/python/langgraph/graph-api ; /interrupts | DOC | Routing function returns next node; `interrupt()` | | Code-owned loop | V |
| 8 | OpenAI Agents SDK: agents, guardrails, HITL, running agents | OpenAI | no version | https://openai.github.io/openai-agents-python/ | DOC | `tool_use_behavior`; tool guardrails; `needs_approval`; no per-turn model hook documented | Guardrails skip handoffs and hosted tools | Turnwise demo host; weakest per-step seams | V |
| 9 | LlamaIndex Workflows intro; agent HITL | LlamaIndex | no version | https://developers.llamaindex.ai/python/llamaagents/workflows/ | DOC | "Branches are ordinary `if` statements" | | Code-owned loop; Turnwise demo host | V |
| 10 | PydanticAI agents; deferred tools | Pydantic | no version | https://pydantic.dev/docs/ai/core-concepts/agent/ ; /tools-toolsets/deferred-tools/ | DOC | `AgentRun.next`; `DeferredToolRequests` | Agent page partly read | Step control; propose-only | V |
| 11 | DSPy home | DSPy | 3.5.0 | https://dspy.ai/ | DOC | "plain Python control flow" | Home page only | Code-owned loop | V |
| 12 | Agent Middleware | Microsoft | 2026-10-22 | https://learn.microsoft.com/en-us/agent-framework/user-guide/agents/agent-middleware | DOC | Agent, function, chat middleware; termination | | Step interception | V |
| 13 | Haystack Agent; Human in the loop | deepset | 3.5 | https://docs.haystack.deepset.ai/docs/agent | DOC | `exit_conditions`; confirm / reject / modify | | Approval | V |
| 14 | Mastra agent approval; overview | Mastra | no version | https://mastra.ai/docs/agents/agent-approval | DOC | `requireToolApproval`, approve / decline | Per-step model swap NV | Approval | V |
| 15 | ADK callbacks | Google | tags v0.1.0+ | https://adk.dev/callbacks/types-of-callbacks/ | DOC | Returning `LlmResponse` skips the LLM; returning dict skips the tool | Last 15k chars unread | Skip model by code | V |
| 16 | AutoGen: tool use with intervention | Microsoft | no version | https://microsoft.github.io/autogen/stable/user-guide/core-user-guide/cookbook/tool-use-with-intervention.html | DOC | Intercepts `FunctionCall`; deny via `ToolException` | Cookbook | Approval | V |
| 17 | Claude Agent SDK hooks; permissions | Anthropic | SDK v0.3.317 / v0.2.177 mentioned | https://code.claude.com/docs/en/agent-sdk/hooks ; /permissions | DOC | allow / deny / ask / defer; `updatedInput`; six-step evaluation | Loop stays model-controlled | Host authority | V |
| 18 | Temporal AI cookbook: agentic loop | Temporal | no date | https://docs.temporal.io/ai-cookbook/agentic-loop-tool-call-openai-python | DOC | Loop in workflow code; LLM and tools as Activities | | Code-owned loop | V |
| 19 | Restate human-in-the-loop | Restate | no date | https://docs.restate.dev/ai/patterns/human-in-the-loop | DOC | Durable approval promise | | Approval | V |
| 20 | Inngest AgentKit routers | Inngest | no date | https://agentkit.inngest.com/concepts/routers | DOC | Router "called after each agent runs"; code routing has "no LLM calls" | Granularity is agent, not model call | Deterministic step router | V |
| 21 | Policy in Amazon Bedrock AgentCore | AWS | no date | https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy.html | DOC | Deterministic enforcement "outside of agent's code"; Cedar | | Host authority | V |
| 22 | DBOS agent docs | DBOS | | https://docs.dbos.dev/python/tutorials/ai-agents | DOC | 404 | | | NV |
| 23 | ReAct | Yao et al. | ICLR 2023 | https://arxiv.org/abs/2210.03629 | PR | +34% / +10% abs. on ALFWorld / WebShop | | Baseline loop | V-abs |
| 24 | Plan-and-Solve | Wang et al. | ACL 2023 | https://arxiv.org/abs/2305.04091 | PR | Zero-shot planning prompt | Prompting only | Plan-then-execute | V-abs |
| 25 | ReWOO | Xu et al. | 23 May 2023 | https://arxiv.org/abs/2305.18323 | PP | 5x token efficiency, +4% on HotpotQA | | Decoupled planning | V-abs |
| 26 | LLMCompiler | Kim et al. | ICML 2024 | https://arxiv.org/abs/2312.04511 | PR | Up to 3.7x faster, 6.7x cheaper, ~9% more accurate than ReAct | "up to" | Parallel execution | V-abs |
| 27 | CodeAct | Wang et al. | ICML 2024 | https://arxiv.org/abs/2402.01030 | PR | Up to 20% higher success | | Model-side orchestration | V-abs |
| 28 | Introducing advanced tool use | Anthropic | 24 Nov 2025 | https://www.anthropic.com/engineering/advanced-tool-use | VB | 43,588 to 27,297 tokens; 25.6 to 28.5%; 46.5 to 51.2% | Internal evals | Counter-trend | V |
| 29 | Code Mode | Varda, Pai / Cloudflare | 26 Sep 2025 | https://blog.cloudflare.com/code-mode/ | VB | LLM writes code against a TypeScript API | No benchmarks; marketing | Counter-trend | V |
| 30 | 12-Factor Agents | Horthy / HumanLayer | no date | https://github.com/humanlayer/12-factor-agents | GH | Factors 4, 8, 12; "mostly deterministic code" | Opinion | Same stance | V |
| 31 | Building effective agents | Anthropic | 19 Dec 2024 | https://www.anthropic.com/engineering/building-effective-agents | VB | Workflows versus agents; routing | Opinion | Same stance | V |
| 32 | A practical guide to building agents | OpenAI | no date in PDF | https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf | VB | "a deterministic solution may suffice"; smaller models; tool risk ratings | Opinion | Same stance | V |
| 33 | Context Engineering for AI Agents | Ji / Manus | 18 Jul 2025 | https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus | VB | State machine masks logits; four rebuilds | Anecdotal | Controller-constrained actions; scaffolding churn | V |
| 34 | Speech and Language Processing, App. K | Jurafsky, Martin | draft 19 Aug 2026 | https://web.stanford.edu/~jurafsky/slp3/K.pdf | TB | "A dialogue policy thus decides what dialogue act to generate." | | Core ancestor | V |
| 35 | Rasa: Open Source Language Understanding and Dialogue Management | Bocklisch et al. | Dec 2017 | https://ar5iv.arxiv.org/html/1712.05181 | PP (workshop) | Policy "predicts which action to take from a predefined list"; loop until 'listen' | Workshop paper | Closest structural match | V |
| 36 | Hybrid Code Networks | Williams, Asadi, Zweig | ACL 2017 | https://arxiv.org/abs/1702.03274 | PR | RNN policy plus "domain-specific knowledge encoded as software" | | Learned policy constrained by code | V-abs |
| 37 | POMDP-based Statistical Spoken Dialogue Systems: a Review | Young et al. | Proc. IEEE 2013 | https://www.microsoft.com/en-us/research/publication/pomdp-based-statistical-spoken-dialogue-systems-a-review/ | PR | Policy optimised "via a reward-driven process" | Full text not opened (403) | Dialogue policy lineage | V-abs |
| 38 | How Alexa Conversations Works | Amazon | 27 Nov 2023 | https://developer.amazon.com/docs/alexa/conversations/how-alexa-conversations-works.html | DOC | Runtime "predicts the next action type and action name" | | Learned next-action policy | V |
| 39 | Alexa Conversations | Acharya et al. | NAACL 2021 demos | https://arxiv.org/abs/2104.09088 | PR | "over 50% improvement in turn-level action signature prediction accuracy" | Demo paper | Same | V-abs |
| 40 | Dialogflow CX basics | Google Cloud | no date | https://docs.cloud.google.com/dialogflow/cx/docs/basics | DOC | Conversation "described and visualized as a state machine" | | State-machine control | V |
| 41 | Task-Oriented Dialogue with In-Context Learning | Bocklisch et al. / Rasa | 19 Feb 2024 | https://arxiv.org/abs/2402.12234 | PP | LLM emits DSL commands; manager executes "deterministically"; 95.8% vs 47.9% on 71 tests | Vendor authors; tiny test set; NLU baseline | Closest LLM-era match | V |
| 42 | CALM concepts | Rasa | no date | https://rasa.com/docs/learn/concepts/calm/ | DOC | LLMs "don't guess your business logic" | Vendor | Same | V |
| 43 | Cut AI Assistant Costs by 77.8% | Rasa | 8 Aug 2024 | https://rasa.com/blog/cutting-ai-assistant-costs-the-power-of-enhancing-llms-with-business | VB | $0.04 vs $0.10; 2.08 s vs 7.4 s; 1 of 5 runs clean | Marketing; tiny sample | Cost evidence (weak) | V |
| 44 | Parlant README | Emcie | no date | https://raw.githubusercontent.com/emcie-co/parlant/HEAD/README.md | GH | Per-turn relevance matching; "20x–100x cheaper" | Marketing; docs page empty | Per-step context composition | V |
| 45 | The Dual LLM pattern | Willison | 25 Apr 2023 | https://simonwillison.net/2023/Apr/25/dual-llm-pattern/ | PB | Controller is "regular software, not a language model" | "isn't a 100% reliable solution" | Tool-less model step | V |
| 46 | Defeating Prompt Injections by Design (CaMeL) | Debenedetti et al. | v2 24 Jun 2025 | https://arxiv.org/abs/2503.18813 | PP | 77% vs 84% utility; 0 attacks; ~2.82x / 2.73x tokens | User burden; side channels | Host authority evidence | V |
| 47 | Design Patterns for Securing LLM Agents | Beurer-Kellner et al. | v3 27 Jun 2025 | https://arxiv.org/abs/2506.08837 | PP | Six patterns; Action-Selector is an "LLM-modulated" switch | No experiments | Closed action set | V |
| 48 | AI Control | Greenblatt et al. | v1 12 Dec 2023 | https://arxiv.org/abs/2312.06942 | PP | Trusted editing, untrusted monitoring | Abstract only | Light/heavy protocol | V-abs |
| 49 | AgentSpec | Wang, Poskitt, Sun | ICSE 2026 | https://arxiv.org/abs/2503.18666 | PR | >90% unsafe code executions prevented; ms overhead | | Runtime enforcement | V-abs |
| 50 | Progent | Shi et al. | v3 14 May 2026 | https://arxiv.org/abs/2504.11703 | PP | Deterministic per-call privilege checks | No numbers in abstract | Host authority | V-abs |
| 51 | StateFlow | Wu et al. | v5 14 Sep 2024 | https://arxiv.org/abs/2403.11322 | PP | +13% / +28% vs ReAct; 5x / 3x less cost | Older models | FSM control evidence | V-abs |
| 52 | Behavior Trees Enable Structured Programming of LM Agents | Kelley | 11 Apr 2024 | https://arxiv.org/abs/2404.07439 | PP | Dendron library | Case studies | Behaviour-tree control | V-abs |
| 53 | CoALA | Sumers et al. | TMLR; v3 15 Mar 2024 | https://arxiv.org/abs/2309.02427 | PR | Decision-cycle framework | Conceptual | Framing | V-abs |
| 54 | Utility-Guided Agent Orchestration | Liu, Zhao, Xu | IEEE JCC 2026 | https://arxiv.org/abs/2603.19896 | PR | Per-step utility policy: F1 0.236 at 1294.2 tokens vs ReAct 0.2662 at 546.6 | 200 HotpotQA items; LLM self-estimates | Nearest test; negative | V |
| 55 | Multi-Head Latent Control | Ghasemabadi et al. | 15 Jul 2026 | https://arxiv.org/abs/2607.14277 | PP | Large-model use down up to 90.7%; 27 to 53% avg | White-box; limitations unread | Nearest design; positive | V |
| 56 | ToolOrchestra | Su et al. | 26 Nov 2025 | https://arxiv.org/abs/2511.21689 | PP | 8B orchestrator: 37.1% vs 35.1% (GPT-5) on HLE | Orchestrator is generative | Small controller | V-abs |
| 57 | KAIJU | Guerin, Guerin | 31 Mar 2026 | https://arxiv.org/abs/2604.02375 | PP | Executive kernel; intent-gated execution | No numbers in abstract | Decoupled execution | V-abs |
| 58 | LedgerAgent | Uddin et al. | 18 Jun 2026 | https://arxiv.org/abs/2606.20529 | PP | Ledger state plus pre-action checks improve pass^k | Work in progress | Structured state | V-abs |
| 59 | Beyond IVR (JourneyBench) | Balaji et al. | 2 Jan 2026 | https://arxiv.org/abs/2601.00596 | PP | Policy-controlled agent boosts adherence; 703 conversations | No numbers in abstract | Structure helps small models | V-abs |
| 60 | In-Context Prompting Obsoletes Agent Orchestration for Procedural Tasks | Dennis et al. | v2 5 May 2026 | https://arxiv.org/abs/2604.27891 | PP | Failure 11.5 / 0.5 / 5% in-context vs 24 / 9 / 17% orchestrated | LLM judge; model unnamed | Strongest counter-evidence | V-abs |
| 61 | Agentless | Xia et al. | v2 29 Oct 2024 | https://arxiv.org/abs/2407.01489 | PP | 32.00% SWE-bench Lite at $0.70 | 2024 snapshot | Workflow beat agents then | V-abs |
| 62 | AI Agents That Matter | Kapoor et al. | 1 Jul 2024 | https://arxiv.org/abs/2407.01502 | PP | "SOTA agents are needlessly complex and costly" | | Cost-aware evaluation | V-abs |
| 63 | AgentDojo | Debenedetti et al. | v3 24 Nov 2024 | https://arxiv.org/abs/2406.13352 | PP | 97 tasks, 629 security test cases | | Security benchmark | V-abs |
| 64 | τ-bench | Yao et al. | 17 Jun 2024 | https://arxiv.org/abs/2406.12045 | PP (ICLR 2025 per search listing, NV) | <50% success; pass^8 <25% retail | | Reliability gap | V-abs |
| 65 | τ²-bench | Barres et al. | 9 Jun 2025 | https://arxiv.org/abs/2506.07982 | PP | Large drops in dual-control setting | No numbers in abstract | Benchmark | V-abs |
| 66 | The Attacker Moves Second | Nasr et al. | 10 Oct 2025 | https://arxiv.org/abs/2510.09023 | PP | 12 defenses bypassed, >90% ASR for most | | Model-level defenses weak | V-abs |
| 67 | Measuring AI Ability to Complete Long Software Tasks | Kwa et al. / METR | NeurIPS 2025 | https://arxiv.org/abs/2503.14499 | PR | ~50 min horizon; doubling ~7 months | Software tasks | Loop capability trend | V-abs |
| 68 | Time horizons page | METR | 8 Sep 2026 | https://metr.org/time-horizons/ | DOC | GPT-5 ~2 h 17 min; >16 h unreliable | No longer updated | Same | V |
| 69 | mini-SWE-agent README | SWE-agent team | no date | https://github.com/SWE-agent/mini-swe-agent | GH | ~100 lines, bash only, ">74%" SWE-bench Verified | Model not named | Thin scaffold suffices | V |
| 70 | Harness design for long-running application development | Rajasekaran / Anthropic | 24 Mar 2026 | https://www.anthropic.com/engineering/harness-design-long-running-apps | VB | Harness parts encode stale assumptions; $9 vs $200 | Vendor; one author's runs | Scaffolding decay, and its limits | V |
| 71 | Agent Harness Design: 3 Patterns | Martin / Anthropic | 2 Apr 2026 | https://claude.com/blog/harnessing-claudes-intelligence | VB | "The orchestration decision moves from the harness to the model." | Vendor | Counter-trend; keeps security in harness | V |
| 72 | Don't Build Multi-Agents | Yan / Cognition | 12 Jun 2025 | https://cognition.com/blog/dont-build-multi-agents | VB | Share full traces; small-model apply step "very faulty" | Opinion | Risk for light step and context slicing | V |
| 73 | Are agent harnesses dying? | Voss / Arize | Sep 2026 | https://arize.com/blog/agent-harness-distillation/ | VB | Reports Cherny: "the gain is wiped out with the next model." | Secondary; primary NV | Scaffolding decay | V (secondary) |
| 74 | The Bitter Lesson | Sutton | 13 Mar 2019 | http://www.incompleteideas.net/IncIdeas/BitterLesson.html (503); copy read at https://www.cs.utexas.edu/~eunsol/courses/data/bitter_lesson.pdf | PB | General methods that leverage computation win | Analogy only; verified via cs.utexas.edu PDF copy | Framing | V (mirror) |
| 75 | Small Language Models are the Future of Agentic AI | Belcak et al. | v3 22 Sep 2026 | https://arxiv.org/abs/2506.02153 | PP | Position: SLMs "sufficiently powerful" for many agent calls | Position paper | Supports light-model use | V-abs |
| 76 | Semantic Kernel filters | Microsoft | | | DOC | | Not opened | | NV |
| 77 | Anthropic Messages API tool-use overview | Anthropic | | | DOC | | Not opened | | NV |
| 78 | Formally Specifying the High-Level Behavior of LLM-Based Agents | | | https://arxiv.org/abs/2310.08535 | PP | | Search snippet only | | NV |
