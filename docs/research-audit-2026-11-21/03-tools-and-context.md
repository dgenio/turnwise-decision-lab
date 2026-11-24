# Tools, authorization and context engineering: skeptical literature and engineering review for Turnwise Decision Lab

> **Status: dated external research note, archived 2026-11-21. Historical (accurate for its date).** Written by an AI research pass for the red-team review in [#94](https://github.com/dgenio/turnwise-decision-lab/issues/94). Research only: no model was called and no experiment was run by this repository. Verification flags are the author's own; the [audit index](README.md) says what was independently re-checked and lists known corrections. Do not rewrite this file; add a dated note instead.

Date of research: 2026-11-20. Scope: Part 1 (tool selection, execution, authorization) and Part 2 (context engineering, instruction selection). Research only; no repository or external system was modified.

## How to read this report

- **Verification.** Every source below was opened with a fetch tool on 2026-11-20 unless marked **NOT VERIFIED**. The fetch tool returns a model-written extraction of the page, with short quotes only. Numbers are reported as the page stated them, but anyone quoting them in a publication should re-open the primary source. Where only an abstract page was opened, the record says "abstract only".
- **Source types.** *Peer-reviewed* (venue named on the page), *preprint* (arXiv, no venue), *official docs*, *vendor blog* (treat numbers as marketing unless a method is given), *personal/practitioner blog*.
- **Status of claims.** Nothing in this report is a measurement of Turnwise. The arithmetic in section 2.3 is my own illustrative calculation, not a measurement.
- **Dates in docs.** Vendor documentation was read in its November 2026 state, so model names and prices are the ones live on that date.
- **Titles and affiliations.** Where the fetch did not return a page's exact title, I use a descriptive label instead. Organisation names in parentheses after author lists come from my background knowledge unless the page stated them; treat them as unconfirmed.

## Short summary

1. "The host owns authority" is established practice with several independent implementations and some measurements (Google's deterministic policy-engine layer, AWS AgentCore Policy with Cedar, Progent, AgentSpec, Invariant, Microsoft's toolkit, CaMeL). It is not a distinguishing contribution.
2. The parts of tool use where a decision policy could plausibly help (multi-turn, stateful, long-horizon) are exactly the parts with no verified evidence that a rules or small-classifier policy helps. The parts where the evidence is strong (single-turn selection, schema-valid arguments, tool shortlisting) are already handled by native tool calling, strict decoding and vendor tool search.
3. The industry direction for orchestration is the opposite of Turnwise: fewer model round trips by moving loops into model-written code (programmatic tool calling, Code Mode, CodeAct). Turnwise adds a policy hop after every observation.
4. Per-step rewriting of the prompt prefix conflicts with prefix-match prompt caching. Whether it raises cost depends on what is rewritten. Rewriting the front while keeping history is 2 to 7 times more expensive in my arithmetic. Replacing history with a small typed state can be cheaper, but that saving comes from dropping history, not from selecting instruction blocks, and it shrinks as cache-read prices fall.
5. Evidence on instruction selection is mixed and does not single out a non-LLM selector: focused instruction sets help, model-selected skills are often not invoked, static always-on context won one vendor comparison, and repository context files did not generally improve success in an academic study.

---

# Part 1. Tool selection, execution and authorization

## 1.1 Tool-count overload and retrieval-based tool selection

**Finding in one line:** more tools in context costs tokens and lowers selection accuracy; shortlisting a few relevant tools fixes most of it; vendors now ship this natively and in a cache-preserving form.

| Source | Type | Specific finding (as stated) | Limitations | Relevance |
|---|---|---|---|---|
| RAG-MCP: Mitigating Prompt Bloat in LLM Tool Selection via Retrieval-Augmented Generation. Gan, Sun. 6 May 2025. https://arxiv.org/abs/2505.03275 | Preprint (abstract only) | Retrieval before the LLM "more than triples tool selection accuracy (43.13% vs 13.62% baseline)" and cuts prompt tokens "by over 50%" | Two authors, no venue; absolute accuracy after the fix is still 43% | Shows overload is real, and that a non-LLM retriever is a workable first stage |
| Less is More: Optimizing Function Calling for LLM Execution on Edge Devices. Paramanayakam et al. 23 Nov 2024. https://arxiv.org/abs/2411.15399 | Peer-reviewed (DATE 2025; abstract only) | Reducing the number of tools offered improves success, with "execution time reduced by up to 70% and power consumption by up to 40%" | Edge hardware and small models; success-rate gain not quantified in the abstract | Supports tool subsetting for small models |
| Retrieval Models Aren't Tool-Savvy (ToolRet). Shi et al. 3 Mar 2025. https://arxiv.org/abs/2503.01763 | Peer-reviewed (ACL 2025; abstract only) | Benchmark of 7.6k retrieval tasks over 43k tools; strong IR models "exhibit poor performance" and low retrieval quality "degrades the task pass rate" | Abstract gives no per-model numbers | Caution: an embedding router is not automatically good at tool retrieval |
| Advanced tool use (engineering blog post). Anthropic (Bin Wu et al.). 24 Nov 2025. https://www.anthropic.com/engineering/advanced-tool-use | Vendor blog, internal evaluations | 58 tools from five MCP servers ≈ 55K tokens; Tool Search Tool gives an "85% reduction in token usage"; MCP-eval accuracy Opus 4 "from 49% to 74%", Opus 4.5 "from 79.5% to 88.1%"; tool-use examples raise complex-parameter accuracy "from 72% to 90%"; states tool search "doesn't break prompt caching" | Internal evaluations, no task list or method; adds a search step and latency; not useful under 10 tools | Vendor-native answer to overload; selection is done by the model issuing a search |
| Tool search tool. Anthropic. Read 2026-11-20. https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool | Official docs | "Claude's ability to pick the right tool degrades once you exceed 30–50 available tools"; typical five-server setup "~55k tokens", reduced "by over 85 percent"; up to 10,000 deferred tools; default 5 results; custom client-side search (for example embeddings) is supported through `tool_reference` blocks | The 30–50 threshold is asserted, not sourced | A host-side embedding or rules selector can be plugged in without leaving the vendor mechanism |
| Tool search. OpenAI. Read 2026-11-20. https://developers.openai.com/api/docs/guides/tools-tool-search | Official docs | `defer_loading` plus hosted or client-executed search; "designed to preserve the model's cache" because loaded tools are added at the end of context; no numbers given | No quantitative claims | Same convergence: dynamic tools are appended, not rewritten into the prefix |
| Function calling. OpenAI. Read 2026-11-20. https://developers.openai.com/api/docs/guides/function-calling | Official docs | "Aim for fewer than 20 functions available at the start of a turn ... a soft suggestion"; "Don't make the model fill arguments you already know" | Guidance, not measurement | Direct vendor endorsement of deterministic argument filling by the host |
| How we're making GitHub Copilot smarter with fewer tools. Agarwal, Peet (GitHub). 19 Nov 2025. https://github.blog/ai-and-ml/github-copilot/how-were-making-github-copilot-smarter-with-fewer-tools/ | Vendor blog with online A/B data | Default toolset cut from about 40 to 13 core tools; full toolset cost a 2–5 percentage point drop in resolution rate (SWE-Lancer, SWEbench-Verified); Tool Use Coverage: embedding-based 94.5%, LLM-based 87.5%, static list 69.0%; TTFT down 190 ms, final token down 400 ms; notes that expanding tool groups causes cache misses | "Coverage" is whether the right tool is visible, not final task success; one product | The strongest verified case of a non-LLM selector beating an LLM selector, for the shortlisting sub-problem only |
| Tool-space interference in the MCP era. Fourney, Payne, Murad, Amershi (Microsoft Research). 11 Sep 2025. https://www.microsoft.com/en-us/research/blog/tool-space-interference-in-the-mcp-era-designing-for-agent-compatibility-at-scale/ | Vendor research blog | 1,470 MCP servers analysed; largest server 256 tools; 775 tools with name collisions ("search" in 32 servers); mean tool output 4,431 tokens, 16 tools return over 128,000 tokens; cites drops "by up to 85% for some models" with large tool spaces and up to 91% with long responses | The 85% and 91% figures are cited from other work, not measured here | Overload is partly a response-size and naming problem, which a selection policy does not solve |
| Efficient and Scalable Estimation of Tool Representations in Vector Space (Tool2Vec). Moon et al. 2 Sep 2024. https://arxiv.org/abs/2409.02141 | Preprint (abstract only) | Small encoder retrieval; Recall@K improvements "up to 27.28" on ToolBench and "30.5" on ToolBank | Synthetic data; retrieval metric only | Small encoders can do tool retrieval when trained on usage data |
| TinyAgent: Function Calling at the Edge. Erdogan et al. 1 Sep 2024. https://arxiv.org/abs/2409.00608 | Peer-reviewed (EMNLP 2024 demo; abstract only) | Fine-tuned 1.1B and 7B models plus a tool-retrieval step claimed to match GPT-4-Turbo function calling on a Mac assistant task | Narrow demo domain; abstract has no numbers | Small models can do tool calling in a closed domain after fine-tuning |

Candidates named in the brief that I did not find as a single primary source: a neutral, peer-reviewed 2026 "MCP tool overload" study. Search returned mainly secondary blogs with inconsistent thresholds (10–15, 15–20, 25–50, 30–50 tools). Treat any specific threshold as unsettled.

## 1.2 Programmatic tool calling and code-as-orchestration

**Finding in one line:** vendors report large token and round-trip savings by letting the model write code that calls tools; the evidence is mostly vendor-reported, and the host can still keep execution authority.

| Source | Type | Specific finding | Limitations | Relevance |
|---|---|---|---|---|
| Advanced tool use, programmatic tool calling section. Anthropic. 24 Nov 2025. URL above | Vendor blog, internal evaluation | Average usage "dropped from 43,588 to 27,297 tokens", a "37% reduction" on complex research tasks; internal knowledge retrieval "from 25.6% to 28.5%"; GIA "from 46.5% to 51.2%" | Internal; accuracy gains are small; less useful for single calls or when the model should see intermediate results | Moves the loop into model-written code, the opposite direction from Turnwise |
| Programmatic tool calling. Anthropic. Read 2026-11-20. https://platform.claude.com/docs/en/agents-and-tools/tool-use/programmatic-tool-calling | Official docs | The client still supplies each tool result; "intermediate results are not loaded into Claude's context window"; incompatible with `strict: true`, forced `tool_choice`, `disable_parallel_tool_use`, MCP-connector tools; `allowed_callers` is not a security boundary ("Do not rely on `allowed_callers` as a security boundary"); warns of code-injection risk from tool results | Trades fixed overhead (container start, script generation) for savings | Important nuance: host execution authority is preserved even when orchestration moves into code |
| Code execution with MCP. Jones, Kelly (Anthropic). 4 Nov 2025. https://www.anthropic.com/engineering/code-execution-with-mcp | Vendor blog | "reduces the token usage from 150,000 tokens to 2,000 tokens", "a time and cost saving of 98.7%" | No method, model or task set given; surrounding examples are hypothetical. Treat as illustrative, not a benchmark. Needs a sandbox, which adds "operational overhead and security considerations that direct tool calls avoid" | Headline number is marketing-grade |
| Code Mode (first blog post). Varda, Pai (Cloudflare). 26 Sep 2025. https://blog.cloudflare.com/code-mode/ | Vendor blog | Thesis: "LLMs are better at writing code to call MCP, than at calling MCP directly" | **No quantitative evaluation at all**; explanation is hedged ("Perhaps this is because ...") | Opinion plus product launch |
| Code Mode for the Cloudflare API MCP server (blog post). Carey (Cloudflare). 20 Feb 2026. https://blog.cloudflare.com/code-mode-mcp/ | Vendor blog | Over 2,500 endpoints as native MCP tools would be 1.17 million tokens; Code Mode exposes two tools (`search`, `execute`) in "roughly 1,000 tokens", a 99.9% input reduction; code runs in a V8 isolate with no file system and outbound fetch disabled by default; OAuth-downscoped token | Token counts only; **no task-accuracy evaluation**; the post itself gives two different native-token figures | Shows where the token argument for code orchestration comes from |
| Executable Code Actions Elicit Better LLM Agents (CodeAct). Wang et al. 1 Feb 2024. https://arxiv.org/abs/2402.01030 | Peer-reviewed (ICML 2024; abstract only) | Across 17 LLMs, code actions give "up to 20% higher success rate" than JSON or text actions | 2024 models and benchmarks; "up to" figure | The academic basis for code actions |
| What are agents? smolagents documentation. Hugging Face. Read 2026-11-20. https://huggingface.co/docs/smolagents/conceptual_guides/intro_agents | Official docs | Code actions preferred for composability and training-data familiarity; also: "If that deterministic workflow fits all queries, by all means just code everything! This will give you a 100% reliable system" | Framework documentation | Same library that promotes code agents also states the null: use no agent when a fixed workflow fits |

**Caveats that matter for the review.** (i) None of the large token figures comes with an independent accuracy evaluation. (ii) Code orchestration reduces *model* round trips; a Turnwise loop adds a policy invocation at every observation, so the two approaches pull in opposite directions on latency. (iii) Code orchestration is compatible with host authority: the client still executes or mediates every call.

## 1.3 Parallel and speculative tool execution

| Source | Type | Specific finding | Limitations | Relevance |
|---|---|---|---|---|
| An LLM Compiler for Parallel Function Calling. Kim et al. 7 Dec 2023. https://arxiv.org/abs/2312.04511 | Peer-reviewed (ICML 2024; abstract only) | Planner emits a dependency graph; versus ReAct: "latency speedup of up to 3.7x", "cost savings of up to 6.7x", "accuracy improvement of up to ~9%" | Baseline is 2023 sequential ReAct, before native parallel tool calls were standard | Prior art for the "Decision → Preparation → Execution → Observation with parallelism" idea |
| ReWOO: Decoupling Reasoning from Observations. Xu et al. 23 May 2023. https://arxiv.org/abs/2305.18323 | Preprint (abstract only) | Plan first, then execute: "5x token efficiency and a 4% accuracy improvement" on HotpotQA | 2023 models | Prior art for separating planning from observation |
| Parallel tool use. Anthropic. Read 2026-11-20. https://platform.claude.com/docs/en/agents-and-tools/tool-use/parallel-tool-use | Official docs | Parallel calls are on by default; the model decides which calls to emit together; "How you run those calls is your decision"; "Independent, read-only operations are usually safe to run in parallel ... Tools with side effects, shared state, or ordering requirements might be better run sequentially" | Guidance only | Native feature already covers the parallel-reads case; the host already decides execution order |
| Speculative Actions: A Lossless Framework for Faster Agentic Systems. Ye et al. 5 Oct 2025 (v2 Apr 2026). https://arxiv.org/abs/2510.04371 | Preprint; search results list it at ICLR 2026, but the arXiv page I opened names no venue | A fast model predicts the next action and pre-executes it; "up to 55% next-action prediction accuracy", "up to 20% latency reductions" | Gains are modest; a lossy variant is needed for some settings | Speculation is real but small; it needs a predictor, and a Turnwise-style policy could be one |
| Speculate with Memory: Lossless Acceleration for LLM Agents. Li et al. 14 Jul 2026. https://arxiv.org/abs/2607.12236 | Preprint (abstract only) | Memory-augmented speculator: 19–39% relative accuracy gain on action prediction, up to 2.5× on observation prediction | Abstract gives no latency numbers. A restriction to read-only actions appeared in a search snippet but **not** on the abstract page: NOT VERIFIED | Speculation is safe only for side-effect-free actions, which requires the host to know which tools are read-only |

## 1.4 Deterministic routing and argument extraction without an LLM

| Source | Type | Specific finding | Limitations | Relevance |
|---|---|---|---|---|
| semantic-router. aurelio-labs. Read 2026-11-20. https://github.com/aurelio-labs/semantic-router | Source repository README | Routes by comparing a request against route utterances in vector space; "decides in milliseconds" | **No accuracy or latency numbers on the page.** By default "the best route always wins"; an out-of-scope result needs `fit()` with labelled negatives and a threshold | The popular implementation of the idea has no published accuracy evidence |
| An Evaluation Dataset for Intent Classification and Out-of-Scope Prediction (CLINC150). Larson et al. 4 Sep 2019. https://arxiv.org/abs/1909.02027 | Peer-reviewed (EMNLP-IJCNLP 2019; abstract only) | 150 intents, 10 domains; classifiers do well in scope but "struggle to identify out-of-scope queries" | 2019 models | The classic brittleness result for small intent classifiers |
| Intent Detection in the Age of LLMs. Arora, Jain, Merugu. 2 Oct 2024. https://arxiv.org/abs/2410.01627 | Peer-reviewed (EMNLP 2024 Industry; abstract only) | Hybrid SetFit-plus-LLM with uncertainty routing reaches "within 2% of native LLM accuracy" with about 50% less latency; LLM out-of-scope ability depends on label scope and label-space size | Industry track, intent detection only | Best evidence that a small model can cover most routing if it can escalate when unsure. Out-of-scope remains the weak point for both small models and LLMs |
| Task-Oriented Dialogue with In-Context Learning (Rasa CALM). Bocklisch et al. 19 Feb 2024. https://arxiv.org/abs/2402.12234 | Vendor preprint (abstract only) | LLM translates conversation into a DSL; business logic runs deterministically; claims less build effort than intent-based NLU | Qualitative claims from the vendor | Close prior art for "model proposes, deterministic host executes" |
| StateFlow: Enhancing LLM Task-Solving through State-Driven Workflows. Wu et al. 17 Mar 2024. https://arxiv.org/abs/2403.11322 | Preprint (abstract only) | Finite-state control with per-state prompts: 13% and 28% higher success than ReAct on InterCode SQL and ALFWorld, at 5× and 3× lower cost | 2024 models; state machines hand-built per benchmark | The closest positive evidence for an explicit state/decision layer, on dated baselines |
| Structured outputs. OpenAI. Read 2026-11-20. https://developers.openai.com/api/docs/guides/structured-outputs | Official docs | Strict mode constrains "completed, non-refusal model output to your supplied JSON Schema"; app must still "validate any business rules that the schema does not express"; first request per schema has extra latency | Schema subset only; refusals and truncation escape the guarantee | Format validity is solved by the provider; value correctness is not |
| JSONSchemaBench. Geng et al. 18 Jan 2025. https://arxiv.org/abs/2501.10868 | Preprint (abstract only) | 10K real-world schemas; six constrained-decoding frameworks (Guidance, Outlines, Llamacpp, XGrammar, OpenAI, Gemini) compared on efficiency, coverage, quality | Abstract reports no headline numbers | Coverage of real schemas varies by engine |
| Let Me Speak Freely? Tam et al. 5 Aug 2024. https://arxiv.org/abs/2408.02442 | Preprint (abstract only) | "a significant decline in LLMs reasoning abilities under format restrictions"; stricter formats, larger drops | Contested in later discussion; 2024 models | A model step forced to emit a rigid typed envelope may reason worse. Relevant to Turnwise's typed `StepOutcome` |
| Building effective agents. Anthropic. 19 Dec 2024. https://www.anthropic.com/engineering/building-effective-agents | Vendor guidance | Routing may be done "either by an LLM or a more traditional classification model/algorithm"; advises "finding the simplest solution possible, and only increasing complexity when needed" | Guidance | The routing workflow with a non-LLM classifier is a documented, named pattern |
| 12-factor agents. Dex Horthy (HumanLayer). 2025. https://github.com/humanlayer/12-factor-agents | Practitioner guide | Factors include "Tools are just structured outputs", "Own your control flow", "Own your context window"; claims good production agents are "mostly deterministic code, with LLM steps sprinkled in" | No empirical evidence; anecdote | Shows the Turnwise framing is common practitioner advice |

## 1.5 Safe retries, idempotency and side-effect control

| Source | Type | Specific finding | Limitations | Relevance |
|---|---|---|---|---|
| Activity definition. Temporal. Read 2026-11-20. https://docs.temporal.io/activity-definition | Official docs | "Temporal recommends that Activities be idempotent"; an activity can complete and the worker crash "just before it notifies the Temporal Service", so it is retried; use Workflow Run ID plus Activity ID as an idempotency key, enforced by the called service | The key must be honoured by the downstream system | Durable execution does not make tool side effects exactly-once by itself |
| Durable agents. Restate. Read 2026-11-20. https://docs.restate.dev/ai/patterns/durable-agents | Official vendor docs | "Every step is recorded in a journal"; completed steps "are replayed from the journal (no re-execution)"; claims "Side effects are executed exactly once" | Vendor claim; the page does not explain the mechanism or the failure window between effect and journal write | Journaling is the standard answer for agent loops |
| DBOS guidance for agents | — | **NOT VERIFIED.** Only secondary pages surfaced in search; no primary DBOS page was opened | — | — |
| Model Context Protocol specification, Tools (2025-06-18) and Schema (2025-11-25). https://modelcontextprotocol.io/specification/2025-06-18/server/tools and https://modelcontextprotocol.io/specification/2025-11-25/schema | Official specification | `readOnlyHint` (default false), `destructiveHint` (default true), `idempotentHint` (default false), `openWorldHint` (default true). "all properties in ToolAnnotations are **hints**. They are not guaranteed to provide a faithful description of tool behavior"; "Clients should never make tool use decisions based on ToolAnnotations received from untrusted servers"; clients "MUST consider tool annotations to be untrusted unless they come from trusted servers"; there "SHOULD always be a human in the loop with the ability to deny tool invocations" | Hints are self-declared by servers | A host policy cannot derive write intent or idempotency from MCP metadata alone. It needs its own trusted registry, which is what Turnwise's host does |

## 1.6 Host-side authorization and runtime policy enforcement

**Finding in one line:** deterministic, out-of-model enforcement before tool execution is a crowded field with shipped products and measured results. Turnwise's "host owns authority" invariant matches it closely and adds nothing new at that layer.

| Source | Type | What it enforces | What it measured | Distance from Turnwise's claim |
|---|---|---|---|---|
| Google's Approach for Secure AI Agents: An Introduction. Díaz, Kern, Olive. May 2025. https://services.google.com/fh/files/misc/googles_approach_for_secure_ai_agents.pdf | Vendor white paper (PDF text extracted and read) | Layer 1: deterministic "policy engines, that operate outside the AI model's reasoning process" and intercept actions "before they are executed"; outcomes are allow, block, or "require user confirmation". Layer 2: reasoning-based defences | No measurements. States limits of both layers: policies are "complex and difficult to scale" and "often lack deep contextual understanding"; reasoning-based defences are "non-deterministic and cannot provide absolute guarantees" | Very close. Turnwise's host is a Layer 1 engine. Google argues Layer 1 alone is insufficient |
| Policy in Amazon Bedrock AgentCore. AWS. Read 2026-11-20. https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy.html | Official docs | Cedar policies evaluated at the Gateway on every tool request, "at the boundary outside of agent's code"; conditions on identity and tool input parameters; session-aware temporal conditions; natural-language authoring checked by automated reasoning | None on the page. Release status not checked | Same idea as a managed product |
| Progent: Securing AI Agents with Privilege Control. Shi et al. 16 Apr 2025 (v3 May 2026). https://arxiv.org/abs/2504.11703 | Preprint (full HTML read for numbers) | Allow/forbid rules over tool names and arguments, default deny; fallback can terminate, ask the user, or return an error to the agent; LLM writes policies, an SMT solver separates narrowing (automatic) from expansion (needs approval) | AgentDojo ASR "from 39.9% to 1.0%"; ASB "from 70.3% to 3.9%"; manual rules reach 0% on ASB; about 6% of updates needed approval. Runtime overhead not reported in the text read | Very close to Turnwise's host validation. Stated limits: cannot stop attacks that stay within least privilege; wrong user approvals weaken guarantees |
| AgentSpec: Customizable Runtime Enforcement for Safe and Reliable LLM Agents. Wang, Poskitt, Sun. 24 Mar 2025. https://arxiv.org/abs/2503.18666 | Peer-reviewed (ICSE 2026, pp. 2938–2950; abstract only) | DSL of triggers, predicates and enforcement actions at runtime | "prevents unsafe executions in over 90% of code agent cases", "eliminates all hazardous actions in embodied agent tasks", "100% compliance" for autonomous vehicles; overhead "in milliseconds"; LLM-generated rules reach "precision of 95.56% and recall of 70.96%" | Close. Rule recall of 71% for generated rules shows the hard part is writing complete rules |
| Defeating Prompt Injections by Design (CaMeL). Debenedetti et al. 24 Mar 2025. https://arxiv.org/abs/2503.18813 | Preprint (abstract only) | Control and data flow extracted from the trusted query; capabilities enforced at tool calls | "solving 77% of tasks with provable security (compared to 84% with an undefended system) in AgentDojo" | Stronger than Turnwise: data-flow tracking, not just per-call checks. Seven-point utility cost |
| Design Patterns for Securing LLM Agents against Prompt Injections. Beurer-Kellner et al. 10 Jun 2025. https://arxiv.org/abs/2506.08837 | Preprint (HTML read) | Six patterns: Action-Selector, Plan-Then-Execute, LLM Map-Reduce, Dual LLM, Code-Then-Execute, Context-Minimization. Principle: after untrusted input, "it is impossible for that input to trigger any consequential actions" | Case studies, no benchmark. Action-Selector "mostly loses the benefits of an LLM's fuzzy search abilities"; unanticipated benign requests "will be falsely blocked" | Turnwise's deterministic operations are the Action-Selector pattern. The paper names the utility cost |
| Agents Rule of Two. Meta. 31 Oct 2025. https://ai.meta.com/blog/practical-ai-agent-security/ | Vendor blog | An agent should satisfy "no more than two" of: processes untrustworthy inputs; accesses sensitive systems or private data; changes state or communicates externally. With all three it "should not be permitted to operate autonomously" | None. Says satisfying it is not sufficient | A design heuristic that Turnwise's "writes are held" already satisfies |
| Invariant Guardrails. Invariant Labs. Read 2026-11-20. https://github.com/invariantlabs-ai/invariant | Source repository README | Rule language (`raise "..." if:`) over messages, tool calls, arguments and data flow (`->`), enforced by a proxy between app and LLM or MCP server; can import ML detectors such as `prompt_injection` | No evaluation on the page | Deterministic matching plus optional ML detectors. Acquisition status not verified |
| Agent Governance Toolkit. Microsoft. Read 2026-11-20. https://github.com/microsoft/agent-governance-toolkit | Source repository README | "Every tool call, message send, and delegation is intercepted in deterministic application code"; fail-closed policy runtime; YAML shown, OPA and Cedar named | README claims "10/10 OWASP Agentic Top 10" while its own badge encodes 7 full and 3 partial; no latency numbers. Enforces at middleware level, not OS level | Another shipped implementation. README marketing is internally inconsistent |
| ShieldAgent. Chen, Kang, Li. 26 Mar 2025. https://arxiv.org/abs/2503.22738 | Preprint (abstract only) | A guard agent extracts rules from policy documents and verifies trajectories | 11.3% average improvement over prior guardrails, recall 90.1%, 64.7% fewer API queries, 58.2% less inference time | Model-based guard, so probabilistic |
| GuardAgent. Xiang et al. 13 Jun 2024. https://arxiv.org/abs/2406.09187 | Peer-reviewed (ICML 2025; abstract only) | LLM turns a safety request into guardrail code that runs deterministically | Over 98% guardrail accuracy on EICU-AC, 83% on Mind2Web-SC | Hybrid: model-written checks, deterministic execution |
| The Attacker Moves Second. Nasr et al. 10 Oct 2025. https://arxiv.org/abs/2510.09023 | Preprint (abstract only) | Adaptive attacks against 12 recent jailbreak and injection defences | Attack success "above 90% for most"; most had reported near-zero | Supports deterministic host checks over model-based filters. Also a warning that static-attack ASR numbers (including Progent's) overstate robustness |
| OWASP Top 10 for Agentic Applications for 2026. OWASP GenAI Security Project. 9 Dec 2025. https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/ | Community standard | Title and date verified. **Category names NOT VERIFIED** (landing page only links a download) | — | — |

**Assessment.** Turnwise's host does per-call permission and argument validation, holds writes and checks citations at finish. Progent, AgentSpec, AgentCore Policy, Invariant and the Google Layer 1 description all do per-call deterministic validation. CaMeL and the design-patterns paper go further with data-flow guarantees. The utility cost of enforcement varies by mechanism: CaMeL solves 77% of tasks against 84% undefended; on AgentDojo with GPT-4o, `transformers_pi_detector` drops utility to 41.24% from 69.07%, while `tool_filter` did not reduce it (72.16%). Turnwise has not reported an AgentDojo-style utility and attack-success pair, so its position relative to these systems is **Not tested**.

## 1.7 Benchmarks that could host a fair test

"Pluggable" is my assessment from each benchmark's described design, not something a source states.

| Benchmark | What it measures | Key numbers (as stated) | Cost to run | Known validity problems | External policy arm pluggable? |
|---|---|---|---|---|---|
| τ-bench. Yao et al. 17 Jun 2024. https://arxiv.org/abs/2406.12045 | Tool-agent-user dialogue under a written policy; final database state plus required outputs; pass^k reliability | 115 retail and 50 airline tasks; gpt-4o pass^1 61.2% retail, 35.2% airline; retail pass^8 below 25% | Paper: about $0.38 agent plus $0.23 user per retail task, roughly $200 per trial. HAL (https://hal.cs.princeton.edu/taubench_airline): $11.36 to $180.49 for a 50-task airline run, flagged as possibly overstated up to 2× and ignoring caching | LLM user simulator errors; reward "necessary but not sufficient"; the ABC paper says it "counts empty responses as successful"; HAL removed a few-shot scaffold for test leakage; taubench.com mentions a March 2026 audit that fixed 50+ airline and retail tasks | Yes. The agent is a function from conversation to action; a host-plus-policy agent fits |
| τ²-bench. Barres et al. 9 Jun 2025. https://arxiv.org/abs/2506.07982; leaderboard https://taubench.com/ | Adds a dual-control telecom domain where the user also acts with tools | Leaderboard landing page (read 2026-11-20): top τ²-bench text pass^1 87.9%; τ³-Banking top 55.2% | unknown | Top scores near 88% suggest limited headroom on the text track; submissions are self-reported | Yes |
| ToolSandbox. Lu et al. (Apple). 8 Aug 2024. https://arxiv.org/abs/2408.04682 | Stateful tools, implicit state dependencies, on-policy user simulator, milestone scoring | State Dependency, Canonicalization and Insufficient Information are hard "even for the most capable" models | unknown | Small scenario set; simulator-dependent | Yes. Hold and clarify operations map onto its insufficient-information category |
| BFCL v4. Patil et al. ICML 2025, PMLR 267:48371–48392. https://proceedings.mlr.press/v267/patil25a.html; data https://gorilla.cs.berkeley.edu/data_overall.csv | Function-call correctness by AST match: single-turn, live, multi-turn, web search, memory, relevance and irrelevance detection | See section 1.8 | CSV "Total Cost ($)" per full run: $0.46 (Qwen3-0.6B) to $355.17 (Grok-4 FC); Claude Opus 4.5 $86.55 | AST matching does not execute tools; prompt and function-calling modes differ; the CSV snapshot I read tops out at late-2025 models although the page says updated 2026-04-12 | Partly. A custom handler can wrap a policy, but the benchmark scores emitted calls, so deterministic dispatch would be scored as if it were a model |
| AgentDojo. Debenedetti et al. 19 Jun 2024. https://arxiv.org/abs/2406.13352; results https://agentdojo.spylab.ai/results/ | Utility and targeted attack success under prompt injection in tool outputs | 97 tasks, 629 security cases. GPT-4o undefended: utility 69.07%, under attack 50.08%, targeted ASR 47.69%; `tool_filter` ASR 6.84% at utility 72.16%; Claude 3.7 Sonnet undefended ASR 7.31% | unknown | Static attacks (see The Attacker Moves Second); results page says it is "not a leaderboard"; latest rows are early 2025 | Yes, and it is the natural host. Defences are pipeline components |
| MCP-Universe. Luo et al. (Salesforce). 20 Aug 2025. https://arxiv.org/abs/2508.14704 | Real MCP servers, 6 domains, 11 servers, execution-based evaluators | GPT-5 43.72%, Grok-4 33.33%, Claude-4.0-Sonnet 29.44%; notes long-context growth and "unknown-tools" problems | unknown | Live services and time-varying ground truth hurt reproducibility | Yes in principle, at high engineering cost |
| MCPMark. Wu et al. 28 Sep 2025. https://arxiv.org/abs/2509.24002 | 127 CRUD-heavy MCP tasks with programmatic verification | gpt-5-medium 52.56% pass@1, 33.86% pass^4; average 16.2 turns and 17.4 tool calls per task | unknown | Live services | Yes in principle |
| MCP-Bench. Wang et al. 28 Aug 2025. https://arxiv.org/abs/2508.20453 | 28 live MCP servers, 250 tools, fuzzy instructions, multi-hop planning | 20 models tested; abstract gives no scores | unknown | Live servers; scoring method not described in the abstract | Yes in principle |
| AppWorld. Trivedi et al. 26 Jul 2024. https://arxiv.org/abs/2407.18901 | 9 apps, 457 APIs, 750 tasks, state-based tests that detect collateral damage | GPT-4o about 49% normal, about 30% challenge | unknown | Built for interactive code generation, so it favours code agents | Awkward for a typed-operation policy |
| WorkArena. Drouin et al. (ServiceNow). 12 Mar 2024. https://arxiv.org/abs/2403.07718 | 33 browser tasks on ServiceNow | Abstract gives no scores | unknown; needs a ServiceNow instance | Browser UI, not API tools | Poor fit, although the domain is ITSM |
| TheAgentCompany. Xu et al. 18 Dec 2024. https://arxiv.org/abs/2412.14161 | Simulated software company: browse, code, message colleagues | Best agent completes 30% | unknown, heavy | Long open-ended tasks | Poor fit |
| CRMArena-Pro. Huang et al. (Salesforce). 24 May 2025. https://arxiv.org/abs/2505.18878 | 19 CRM tasks, single and multi-turn, confidentiality awareness | About 58% single-turn, about 35% multi-turn; Workflow Execution above 83%; "near-zero inherent confidentiality awareness" | unknown | Vendor-built | Yes. Confidentiality is a host-authority property |
| ST-WebAgentBench. Levy et al. (IBM). 9 Oct 2024. https://arxiv.org/abs/2410.06703 | 222 web tasks with safety and trust policies; Completion under Policy (CuP) | Average CuP "less than two-thirds" of nominal completion | unknown | Web UI agents | Metric is ideal for Turnwise; the environment is not |
| ITBench. Jha et al. (IBM, UIUC). 7 Feb 2025. https://arxiv.org/abs/2502.05352 | 94 SRE, CISO and FinOps scenarios | 13.8% SRE, 25.2% CISO, 0% FinOps resolved | unknown, needs live infrastructure | Heavy setup | Closest domain to Turnwise's incident demo, but costly to stand up |

Cross-cutting evaluation guidance:

- **Establishing Best Practices for Building Rigorous Agentic Benchmarks.** Zhu et al. 3 Jul 2025. https://arxiv.org/abs/2507.02825. Preprint (abstract only). Flaws can misestimate performance "by up to 100% in relative terms"; provides the Agentic Benchmark Checklist.
- **AI Agents That Matter.** Kapoor et al. 1 Jul 2024. https://arxiv.org/abs/2407.01502. Preprint (abstract only). Calls for joint cost and accuracy reporting and proper hold-out sets; narrow accuracy focus yields "needlessly complex and costly" agents.

**Recommendation.** τ²-bench or τ-bench for policy-following dialogue with tools (report pass^k, apply the audited task fixes), AgentDojo for the authority claim (report utility and ASR together and note that attacks are static), and BFCL multi-turn as a cheap sanity check. I found no public ITSM or incident-triage benchmark that is cheap to run; ITBench is the nearest and is heavy.

## 1.8 Where is an explicit decision policy unnecessary, and where is a model unnecessary?

Evidence from the BFCL v4 CSV as fetched on 2026-11-20 (top rows are late-2025 models; 2026 frontier models were not in the file):

| Model | Non-live AST (single turn) | Live | Multi-turn | Irrelevance detection | Cost of full run |
|---|---|---|---|---|---|
| Claude Opus 4.5 (FC), rank 1 | 88.58% | 79.79% | 68.38% | 84.72% | $86.55 |
| Claude Sonnet 4.5 (FC) | 88.65% | 81.13% | 61.37% | 86.61% | $43.73 |
| Gemini 3 Pro Preview (Prompt) | 90.65% | 83.12% | 60.75% | 85.59% | $298.47 |
| Claude Haiku 4.5 (FC) | 86.50% | 78.68% | 53.62% | 85.11% | $14.23 |
| Qwen3-8B (FC) | 87.58% | 80.53% | 41.75% | 79.07% | $43.32 |
| Qwen3-4B-Instruct (FC) | 87.88% | 76.39% | 22.12% | 84.93% | $6.37 |
| xLAM-2-3b-fc-r (FC) | 82.96% | 62.92% | 58.38% | 63.45% | $3.36 |
| Qwen3-0.6B (FC) | 71.79% | 56.62% | 3.62% | 80.84% | $0.46 |

The BFCL paper's own summary is that models "excel at singleturn calls" while "memory, dynamic decision-making, and long-horizon reasoning remain open challenges".

**An explicit decision policy is unnecessary for:**

- *Single-turn tool selection from a small, well-described toolset.* Frontier models and 3B to 8B open models both sit at 82–91% on single-turn AST. Qwen3-4B (87.88%) is within one point of the top-ranked model overall (88.58%) and within three points of the best single-turn score (90.65%). There is little for a policy to add, and a light model already suffices.
- *Schema-valid arguments.* Strict modes guarantee structure (OpenAI and Anthropic docs).
- *Shortlisting from large catalogues.* Vendor tool search with deferred loading, or an embedding pre-filter inside it.
- *Parallelising independent reads.* Native parallel tool calls; the host already chooses execution order.

**A model is unnecessary for:**

- *Enumerable request categories with a fixed workflow.* Anthropic's routing pattern allows a "traditional classification model"; smolagents says to "just code everything".
- *Arguments the host already knows.* OpenAI: "Don't make the model fill arguments you already know."
- *Authorization, approval gating, limits, argument range checks, retries, idempotency keys.* Policy engines and durable execution (section 1.5 and 1.6).
- *Tool pre-selection.* Embedding routing reached 94.5% coverage against 87.5% for an LLM selector at GitHub.
- *In-scope intent routing with escalation.* SetFit hybrid within 2% of LLM accuracy at about half the latency.

**Neither is established for:**

- *Multi-turn, stateful control.* BFCL multi-turn ranges from 3.6% to 68.4%; MCPMark best pass^4 is 33.86%; τ-bench retail pass^8 was below 25% in 2024.
- *Abstention and out-of-scope detection.* Irrelevance detection is 63–87% for the models above; CLINC150 shows the same weakness for classifiers.
- *Context-dependent authorization.* Google's example: send-after-read is sometimes wanted and sometimes exfiltration; "a simple static rule struggles with this nuance".

**Consequence for Turnwise.** The per-step policy has to earn its place in the third group. That is where a rules or small-classifier policy has the least supporting evidence, and where its known weakness (out-of-scope and distribution shift) bites. In the first two groups, simple host rules plus a native agent already do the job, which is the project's own SHRINK/STOP condition.

---

# Part 2. Context engineering and instruction selection

## 2.1 Long-context and multi-turn degradation

| Source | Type | Specific finding | Limitations | Relevance |
|---|---|---|---|---|
| Lost in the Middle. Liu et al. 6 Jul 2023. https://arxiv.org/abs/2307.03172 | Peer-reviewed (TACL; abstract only) | "performance is often highest when relevant information occurs at the beginning or end of the input context" and degrades in the middle | 2023 models | Position matters; an argument for placing selected instructions at the tail |
| Context Rot: How Increasing Input Tokens Impacts LLM Performance. Hong, Troynikov, Huber (Chroma). 14 Jul 2025. https://www.trychroma.com/research/context-rot | Vendor technical report, code released | 18 models; "model performance consistently degrades with increasing input length"; on LongMemEval, focused prompts (about 300 tokens) beat full prompts (about 113k tokens) for all models; shuffled haystacks beat coherent ones | Vendor sells retrieval infrastructure; authors say the evaluation "is not exhaustive of real-world use cases" and "do not explain the mechanisms" | Supports focused context. Does not say who should do the focusing |
| NoLiMa: Long-Context Evaluation Beyond Literal Matching. Modarressi et al. 7 Feb 2025. https://arxiv.org/abs/2502.05167 | Peer-reviewed (ICML 2025; abstract only) | 13 models; at 32K tokens 11 fall below 50% of their short-context baseline; GPT-4o from 99.3% to 69.7% | Synthetic needle task | Degradation holds when literal matching is removed |
| LLMs Get Lost In Multi-Turn Conversation. Laban et al. 9 May 2025. https://arxiv.org/abs/2505.06120 | Preprint (abstract only) | Over 200,000 simulated conversations; average 39% drop from single-turn to multi-turn across six tasks; mostly increased unreliability; "when LLMs take a wrong turn in a conversation, they get lost and do not recover" | Simulated, underspecified conversations | Supports consolidating state into a fresh, well-specified prompt, which is the pro-Turnwise reading |

I did not find and verify a 2026 primary update to these studies on current frontier models. Whether the size of these effects persists is **unknown**.

## 2.2 Vendor and practitioner guidance

| Source | Type | Specific guidance | Relevance |
|---|---|---|---|
| Effective context engineering for AI agents. Anthropic Applied AI team. 29 Sep 2025. https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents | Vendor guidance | Context is a finite "attention budget"; aim for the "minimal set of information that fully outlines your expected behavior"; warns against "bloated tool sets"; favours "just in time" retrieval where the agent holds lightweight identifiers and loads data with tools; sub-agents return summaries "often 1,000-2,000 tokens"; "do the simplest thing that works" | Agrees with Turnwise on minimal context, disagrees on who selects: it mostly favours the model |
| Context management announcement (context editing and memory tool). Anthropic. 29 Sep 2025. https://claude.com/blog/context-management | Vendor blog, internal evaluation | Memory tool plus context editing improved an internal agentic-search evaluation by 39% over baseline; context editing alone 29%; in a 100-turn web search evaluation context editing cut token consumption by 84% | Internal evaluation, no method |
| Context editing. Anthropic. Read 2026-11-20. https://platform.claude.com/docs/en/build-with-claude/context-editing | Official docs | Server-side clearing of old tool results (default trigger 100,000 input tokens, keep 3 tool uses). Clearing "Invalidates cached prompt prefixes when content is cleared ... You'll incur cache write costs each time content is cleared"; `clear_at_least` exists to make the invalidation worthwhile | The vendor states outright that editing history costs a cache rewrite |
| Equipping agents for the real world with Agent Skills. Zhang, Lazuka, Murag (Anthropic). 16 Oct 2025. https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills and docs https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview | Vendor blog and official docs | Level 1: name and description of every skill in the system prompt, "~100 tokens per Skill"; Level 2: `SKILL.md` body, "Under 5k tokens", read when the model judges it relevant; Level 3: files read as needed. The model matches the request against the description | Skills are predefined instruction blocks loaded on demand and **selected by the model**. This is the direct incumbent for Turnwise's historical idea (i) |
| Context Engineering for AI Agents: Lessons from Building Manus. Yichao "Peak" Ji. 18 Jul 2025. https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus | Vendor practitioner blog | "the KV-cache hit rate is the single most important metric for a production-stage AI agent"; input-to-output ratio "around 100:1"; cached Claude Sonnet input 0.30 USD/MTok against 3 USD/MTok uncached; keep the prefix stable, make context append-only, serialise deterministically; "Mask, don't remove": do not change tool definitions mid-task, instead use a state machine that "masks the token logits during decoding"; about 50 tool calls per typical task | Strongest practitioner statement against rewriting the prefix. Also a precedent for a non-LLM state machine that constrains actions while leaving the prompt untouched |
| Don't Build Multi-Agents. Walden Yan (Cognition). 12 Jun 2025. https://cognition.com/blog/dont-build-multi-agents | Vendor blog | "Share context, and share full agent traces, not just individual messages"; "Actions carry implicit decisions"; prefers a single-threaded linear agent, with a compression model for long histories that is "hard to get right" | Argues against splitting context between steps. A model step that sees only a recomposed slice may miss implicit decisions |
| Context Engineering. LangChain team. 2 Jul 2025. https://www.langchain.com/blog/context-engineering-for-agents | Vendor blog | Four strategies: write, select, compress, isolate; cites RAG on tool descriptions improving selection "3-fold"; notes procedural memories are usually fixed always-loaded files | Taxonomy; Turnwise's idea is "select" done by a non-LLM policy |
| How Long Contexts Fail. Drew Breunig. 22 Jun 2025. https://www.dbreunig.com/2025/06/22/how-contexts-fail-and-how-to-fix-them.html | Personal blog citing studies | Poisoning, distraction, confusion, clash; cites a quantised Llama 3.1 8b failing with 46 tools and succeeding with 19 | Secondary source |
| Compaction. OpenAI. Read 2026-11-20. https://developers.openai.com/api/docs/guides/compaction | Official docs | Server-side compaction at a token threshold or a standalone endpoint; the compaction item "is opaque and not intended to be human-interpretable" | OpenAI equivalent of history compression |
| Context compaction. Google ADK. Read 2026-11-20. https://adk.dev/context/compaction/ | Official docs | Token-threshold or sliding-window summarisation of older events | Google equivalent |
| Dynamic context discovery. Jediah Katz (Cursor). 6 Jan 2026. https://cursor.com/blog/dynamic-context-discovery | Vendor blog, A/B test | MCP tool descriptions moved to files with only names static: total agent tokens down 46.9% for runs that called an MCP tool; savings "varied widely" | The model pulls context; the harness decides what is available |

## 2.3 Prompt caching mechanics and economics

### What the official documents say

| Provider | Mechanics | Price multipliers | Source |
|---|---|---|---|
| Anthropic | Prefix match over `tools`, then `system`, then `messages`. Changing tool definitions "invalidates the entire cache"; web-search or citations toggles invalidate system and messages; `tool_choice` and images invalidate messages. Default lifetime 5 minutes, refreshed free on each hit; optional 1 hour. Lookback of 20 positions. Minimum cacheable length 512 to 4,096 tokens by model; shorter prompts silently do not cache | 5-minute write 1.25× base input; 1-hour write 2×; read 0.1× (0.05× on Claude Opus 5.5 and Sonnet 5.5 per the footnote) | https://platform.claude.com/docs/en/build-with-claude/prompt-caching and https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-use-with-prompt-caching (official docs, read 2026-11-20) |
| OpenAI | "Cache reuse requires the entire rendered prefix to match." Changing model, tools, `parallel_tool_calls`, output schema, reasoning effort, verbosity or compaction can alter the prefix. Minimum 1,024 tokens on GPT-5.6 and later. Guidance: stable instructions first, dynamic content "at the end rather than the beginning" | On GPT-5.6 and later: read 0.1× (0.05× on some models), write 1.25× for a 30-minute lifetime or 2.5× for 12 hours. Earlier models: no write surcharge, model-dependent cached rate. Worked example: one write plus nine reads costs "2.15× ... compared with 10× without caching" | https://developers.openai.com/api/docs/guides/prompt-caching (official docs, read 2026-11-20) |
| Google Gemini | Implicit caching on by default for Gemini 2.5 and newer; minimum 2,048 to 4,096 tokens by model; advice to put "large and common contents at the beginning of your prompt" and send similar prefixes close together | **Discount rate NOT VERIFIED**: the page I read says only that savings are passed on | https://aistudio.google.com/docs/caching (official docs, read 2026-11-20) |

Vendors have also added cache-preserving ways to change things mid-run: Anthropic appends discovered tools inline as `tool_reference` blocks so "The prefix is untouched"; OpenAI adds discovered tools "at the end of the context window". The supported pattern is append, not rewrite.

### Independent measurement

**Don't Break the Cache: An Evaluation of Prompt Caching for Long-Horizon Agentic Tasks.** Lumer et al. (PricewaterhouseCoopers). 9 Jan 2026, v2 31 Jan 2026. https://arxiv.org/html/2601.06007v2. Preprint (full HTML read).

- Setup: DeepResearch Bench, web-search agents, 10,000-token system prompts, 40 sessions per model per condition, four models.
- Cost reduction and TTFT change versus no caching:

| Model | Full-context caching | System prompt only | Excluding tool results |
|---|---|---|---|
| GPT-5.2 | 79.3% / 9.5% | 81.4% / 10.5% | 79.6% / 13.0% |
| Claude Sonnet 4.5 | 77.8% / 21.8% | 78.5% / 22.9% | 78.1% / 20.9% |
| Gemini 2.5 Pro | 38.3% / 6.0% | 41.4% / 6.1% | 27.8% / −2.9% |
| GPT-4o | 47.8% / −8.8% | 45.9% / 30.9% | 46.8% / 28.1% |

- Conclusions: caching the system prompt only was the most consistent; full-context caching can hurt latency because tool results trigger writes that are never reused; dynamic content in the system prompt and changing tool sets break the cache.
- Limitations: one task family; latency depends on provider load; the fetch tool noted the paper's abstract and body give different TTFT ranges (13–31% versus 6–31%); consultancy authors, not peer reviewed.
- Relevance: realised savings (41–81% in the best mode) are below the theoretical maximum, and "cache everything" is not always best. The effect of caching is workload-specific and must be measured.

### Key question: does per-step recomposition destroy cache hits and raise cost?

**It depends on which part is recomposed. The following is my arithmetic, not a measurement.**

Assumptions: cost unit is one uncached input token = 1.0. Cache write 1.25×, cache read 0.10× (Anthropic 5-minute multipliers; OpenAI documents the same pair for GPT-5.6 and later). Output tokens are identical across arms and excluded. Every step falls inside the cache lifetime. An unchanged prefix always hits. Prefixes exceed the minimum cacheable length. The loop has N steps, a 10,000-token stable prefix (tools plus all instruction blocks), and each step adds 1,500 tokens of model output and tool result.

| Arm | N = 10 | N = 30 | N = 50 |
|---|---|---|---|
| **A.** Append-only, static 10k prefix, cached | 43,775 | 156,775 | 329,775 |
| A with 0.05× reads | 36,575 | 111,825 | 217,075 |
| A with 0.025× reads | 32,975 | 89,350 | 160,725 |
| **C2.** Same content as A, but something at the front of the prefix changes each step (equals no caching) | 167,500 | 952,500 | 2,337,500 |
| C2 with cache markers left on (write premium, never read) | 209,375 | 1,190,625 | 2,921,875 |
| **C1.** Selected 2k block at the front, full history kept behind it, uncached | 87,500 | 712,500 | 1,937,500 |
| **B.** Fresh minimal prompt each step, no history: 3k tokens | 30,000 | 90,000 | 150,000 |
| B at 5k tokens (for example 2k block + 3k typed state) | 50,000 | 150,000 | 250,000 |
| B at 9k tokens | 90,000 | 270,000 | 450,000 |
| **D.** 8k cached core + cached append-only history + 2k selected block re-sent uncached at the tail, not retained | 59,475 | 208,475 | 417,475 |
| **D′.** As D, but each step's 2k block is appended and retained | 69,175 | 302,175 | 675,175 |

Worked check for A at N = 10: first step writes 10,000 × 1.25 = 12,500. Steps 2 to 10 read the existing prefix at 0.1× (sum 14,400) and write 1,500 new tokens at 1.25× (9 × 1,875 = 16,875). Total 43,775.

What the arithmetic shows:

1. **Recomposing the front while keeping history (C1, C2) is 2.0× to 7.1× the cost of the append-only arm**, and up to 8.9× if cache markers are left on so that every step pays a write premium that is never read. This is the case the vendor documents and Manus warn about, and it is the natural reading of "compose the prompt for each step".
2. **A fresh minimal prompt with no history (B) is not automatically more expensive.** At 5k tokens per step it is 1.14× arm A at N = 10, 0.96× at N = 30 and 0.76× at N = 50. Break-even prompt size is about 4.4k, 5.2k and 6.6k tokens per step respectively. At 9k it is 1.4× to 2.1× worse.
3. **Falling cache-read prices weaken arm B.** With 0.05× reads the N = 30 break-even drops to about 3.7k tokens per step, and with 0.025× to about 3.0k.
4. **Selecting instruction blocks while keeping a cached history (D, D′) costs about 1.3× to 2.1× the fully static prefix.** A 10k static library read from cache costs about 1k per step; a fresh 2k block costs 2k per step. In general, an uncached per-step block of size b beats a cached static library of size L only when b < L × (w + r × (N − 1)) / N. At N = 30 that is b below roughly 14% of L.
5. **The saving in arm B comes from replacing history with a compact state, not from selecting instructions.** An append-only agent can also bound history with compaction or context editing, paying one cache rewrite per clearing. A fair test therefore needs an "append-only plus compaction" arm, or Turnwise will be credited for a saving that the baseline could also have.

What the arithmetic does not show: quality effects, latency (cached prefixes cut TTFT in the measured study; arm B sends shorter prompts but forfeits the cache), cache misses from lifetime expiry or routing, and prompts below the minimum cacheable length, which cannot cache at all. All of these are **unknown** for Turnwise.

**Answer.** Yes for the literal historical idea (rewrite the prefix each step and keep history): it destroys cache hits and raises cost several-fold. Not necessarily for the Turnwise Core shape (short fresh prompt plus typed state): that can be cost-neutral or cheaper on long loops, provided the per-step prompt stays under roughly 3–6k tokens. The project should report billed cost with cache-read and cache-write tokens broken out, not raw token counts. Raw tokens will flatter recomposition.

## 2.4 Compression, pruning and memory

| Source | Type | Specific finding | Limitations | Relevance |
|---|---|---|---|---|
| LLMLingua. Jiang et al. 9 Oct 2023. https://arxiv.org/abs/2310.05736 | Peer-reviewed (EMNLP 2023; abstract only) | "up to 20x compression with little performance loss" | 2023 tasks; compressed text breaks byte-level caching | Token-level compression is an alternative to block selection |
| The Complexity Trap. Lindenbauer et al. (JetBrains Research). 29 Aug 2025. https://arxiv.org/abs/2508.21433 | Peer-reviewed workshop (DL4C at NeurIPS 2025; abstract only) | On SWE-bench Verified, simple observation masking "roughly halves cost" versus the raw agent and matches LLM summarisation on solve rate; a hybrid saves a further 7% versus masking and 11% versus summarisation | Coding agents only; exact solve rates not in the abstract | The simple null matched the sophisticated method. A warning for any elaborate context composer |
| ACON: Optimizing Context Compression for Long-horizon LLM Agents. Kang et al. (Microsoft). 1 Oct 2025. https://arxiv.org/abs/2510.00615 | Peer-reviewed per arXiv listing (ICML 2026; abstract only) | Peak tokens down 26–54% with improved success over compression baselines; small models gain "up to 46%" | Compared with other compressors | Compression guidelines can be optimised from failures instead of hand-written |
| Agentic Context Engineering (ACE). Zhang et al. 6 Oct 2025. https://arxiv.org/abs/2510.04618 | Peer-reviewed per arXiv listing (ICLR 2026; abstract only) | +10.6% on agent tasks, +8.6% on finance; names "brevity bias" and "context collapse" as failure modes of repeated rewriting | Abstract lacks cost figures | Evolving playbooks beat fixed prompts; aggressive brevity loses useful detail |
| Dynamic Cheatsheet. Suzgun et al. 10 Apr 2025. https://arxiv.org/abs/2504.07952 | Preprint (abstract only) | GPT-4o on Game of 24 from 10% to 99% after reusing a stored solution | Narrow tasks | Learned memory as an alternative to predefined blocks |
| MemGPT. Packer et al. 12 Oct 2023. https://arxiv.org/abs/2310.08560 | Preprint (abstract only) | Model-managed memory tiers | No numbers in abstract | Model-driven memory |
| Mem0. Chhikara et al. 28 Apr 2025. https://arxiv.org/abs/2504.19413 | Preprint by the product's builders (abstract only) | 26% relative gain over OpenAI memory on LOCOMO (LLM judge); 91% lower p95 latency and over 90% token saving versus full context | Self-evaluation; LLM-as-judge | Vendor numbers |
| A-MEM. Xu et al. 17 Feb 2025. https://arxiv.org/abs/2502.12110 | Peer-reviewed (NeurIPS 2025; abstract only) | Self-organising linked notes outperform baselines on six models | No numbers in abstract | Model-driven memory |
| Sleep-time Compute. Lin et al. (Letta, Berkeley). 17 Apr 2025. https://arxiv.org/abs/2504.13171 | Preprint (abstract only) | About 5× less test-time compute for equal accuracy; up to 13% and 18% accuracy gains; 2.5× lower cost per query when amortised | Works when queries are predictable | Precomputing context offline is another way to cut per-step cost |
| Learning Agent-Compatible Context Management (AdaCoM). Yi et al. 29 May 2026. https://arxiv.org/abs/2605.30785 | Preprint (abstract only) | Trains "an external LLM to manage the context of a frozen agent"; finds "agents with higher vanilla ReAct performance benefit from higher-fidelity context preservation" | No numbers in abstract | Closest work to an external context policy, and it is learned and LLM-based. Its trade-off says strong models are hurt by aggressive trimming |
| Memory as Action (MemAct). Zhang et al. 14 Oct 2025. https://arxiv.org/abs/2510.12635 | Preprint (abstract only) | Context edits as learned actions; a 14B model matches models 16× larger with 51% shorter average context | RL-trained specific model | Learned context policy inside the agent |

## 2.5 Dynamic instruction selection, optimisers and instruction-count limits

| Source | Type | Specific finding | Limitations | Relevance |
|---|---|---|---|---|
| How Many Instructions Can LLMs Follow at Once? (IFScale). Jaroslawicz et al. 15 Jul 2025. https://arxiv.org/abs/2507.11538 | Preprint (abstract only) | 20 models; "even the best frontier models only achieve 68% accuracy at the max density of 500 instructions"; primacy bias | One synthetic task (keyword inclusion in a report) | Supports fewer instructions per call. Says nothing about who should pick them |
| `AGENTS.md` outperforms skills in our agent evals. Jude Gao (Vercel). 27 Jan 2026. https://vercel.com/blog/agents-md-outperforms-skills-in-our-agent-evals | Vendor blog with evaluation | Next.js 16 evals: baseline 53%, skill (default) 53%, skill with explicit instructions 79%, static `AGENTS.md` docs index 100%. "In 56% of eval cases, the skill was never invoked." Index compressed from about 40KB to 8KB with no loss. Explanation offered: "there's no moment where the agent must decide" | Model and agent version not named; one framework; authors call skill triggering "fragile" and say the gap "may close" | Model-selected progressive disclosure has a large selection-miss rate. Supports removing the model's load decision, which a static prefix does and a host policy could also do |
| Evaluating AGENTS.md: Are Repository-Level Context Files Helpful for Coding Agents? Gloaguen et al. (ETH Zurich). 12 Feb 2026 (v3 Sep 2026). https://arxiv.org/abs/2602.11988 | Preprint (abstract only) | Context files do "not generally improve task success rates" and raise inference cost "by over 20%" on average; agents do follow the instructions; recommends minimal, non-standard-practice content only | Search results suggest versions differ on the direction of the success effect; I read the current abstract | Always-on instructions are not free and often do not help. Cuts against the "static prefix always wins" reading of the Vercel result |
| SkillsBench. Li et al. 13 Feb 2026 (v4 Jun 2026). https://arxiv.org/abs/2602.12670 | Preprint (abstract only) | 87 tasks, 8 domains, 18 model-harness configurations: curated skills raise average pass rate from 33.9% to 50.5% (+16.6 points); "Focused Skills with at most three modules outperform larger or exhaustive bundles" | Numbers differ across versions; the self-generated-skills result (search snippet: about −1.3 points) is **NOT VERIFIED** from the abstract | Focused, curated instruction blocks help. The best-supported pro-block result |
| Optimizing Instructions and Demonstrations for Multi-Stage Language Model Programs (MIPRO). Opsahl-Ong et al. 17 Jun 2024. https://arxiv.org/abs/2406.11695 | Peer-reviewed (EMNLP 2024; abstract only) | Beats baseline optimisers on five of seven programs, "up to 13% accuracy" with Llama-3-8B | Small model, 2024 | Optimised prompts as an alternative to hand-written blocks |
| GEPA: Reflective Prompt Evolution Can Outperform Reinforcement Learning. Agrawal et al. 25 Jul 2025. https://arxiv.org/abs/2507.19457 | Peer-reviewed (ICLR 2026 oral per arXiv listing; abstract only) | Beats GRPO by 6% on average and up to 20% with up to 35× fewer rollouts; beats MIPROv2 by over 10% | Six tasks | A hand-written block library should be compared against an optimised static prompt |
| Parlant. Emcie. Read 2026-11-20. https://github.com/emcie-co/parlant | Source repository README, vendor | Brings a policy into context "only when it's relevant", per turn; claims "20x–100x cheaper to run" than closed platforms | No evaluation; the page does not say how matching is done | A shipping product built on per-turn instruction selection, without published evidence |

I did not find a verified primary study of *retrieving instructions per step with a non-LLM selector* compared against the alternatives. That specific comparison appears to be unstudied.

## 2.6 Is "predefined instruction blocks selected by a non-LLM policy" a good design?

| Option | Evidence for | Evidence against | Cache behaviour |
|---|---|---|---|
| (a) Static cached prefix | Vercel: 100% against 53–79% for skills. Manus and all three vendors' caching guidance. Cheapest per step in my arithmetic when the library is around 10k tokens | ETH: context files do not generally improve success and add over 20% cost. IFScale: compliance falls as instruction count grows. Does not scale to very large libraries | Best |
| (b) Model-selected progressive disclosure (Skills) | SkillsBench +16.6 points for curated skills. About 100 tokens per skill up front. Loaded content is appended, so the cache survives | Vercel: skill never invoked in 56% of cases; triggering depends on wording | Good |
| (c) Retrieval per step | RAG-MCP and GitHub's embedding routing for tools | ToolRet: strong IR models retrieve tools poorly. No verified study for instructions | Good if appended at the tail, bad if inserted at the front |
| (d) Learned or optimised prompts | GEPA, MIPRO, ACE, ACON show gains over fixed prompts | Need training data and an evaluation loop; risk of overfitting to a benchmark | Same as (a) once fixed |
| (e) Non-LLM policy selects predefined blocks (Turnwise idea) | Removes the model's "should I load this?" decision, which Vercel identified as the failure point. Deterministic and auditable. StateFlow's per-state prompts gained 13–28% over ReAct at lower cost on 2024 baselines. Focused blocks are supported by SkillsBench and IFScale | No direct evidence. The selector's own miss rate is unmeasured and is exposed to out-of-scope and distribution-shift failures (CLINC150). AdaCoM: strong models prefer higher-fidelity context. Costs more than (a) in my arithmetic unless the selected block is a small fraction of the library | Depends entirely on placement: tail-append is safe, prefix rewrite is not |

**Judgement.** Option (e) is a reasonable hypothesis with indirect support and no direct evidence. Its plausible advantage over (b) is reliability of loading. Its plausible disadvantage against (a) is cost and selector error. It is only defensible when the block library is too large or too contradictory to keep in one static prefix; for a library of a few thousand tokens, (a) is cheaper and has no selector to get wrong.

**Evidence that would decide it.** One experiment, same model, tools, tasks and host across arms:

1. Arms: (a) static full prefix, cached; (a′) GEPA- or MIPRO-optimised static prefix; (b) model-selected skills; (c) embedding retrieval per step; (e-tail) policy-selected blocks appended at the tail; (e-front) policy-selected blocks rewritten into the prefix; plus an oracle-selection upper bound and a random-selection lower bound.
2. Tasks: held-out, independently authored, with a slice of out-of-scope and shifted requests, and library sizes varied (for example 2k, 10k, 50k tokens) because the answer should flip with size.
3. Metrics: task success with pass^k; instruction compliance per applicable block; selection precision and recall against labelled applicable blocks; loading-miss rate (the Vercel 56% analogue); billed cost with cache-read and cache-write tokens separated; TTFT and total latency; number of policy calls, retries and fallbacks.
4. Decision rule declared in advance: (e) is supported only if success is non-inferior to the best of (a), (a′), (b) within a stated margin and billed cost is lower, on the held-out and shifted slices. If (e) matches oracle selection only in-distribution, the selector is the weak point.

---

# Verdict

## Solved elsewhere (not a Turnwise contribution)

- **Host-owned authority.** Deterministic pre-execution policy checks, default deny, approval for writes: Google Layer 1, AgentCore Policy, Progent (AgentDojo ASR 39.9% to 1.0%), AgentSpec (over 90% of unsafe code executions prevented), Invariant, Microsoft's toolkit, CaMeL (77% of tasks with provable security).
- **"The model executes nothing."** Every client-side tool-calling API already works this way: the model emits a structured request and the host runs it. Turnwise's typed proposal restates that contract and inserts a policy hop.
- **Tool overload.** Deferred loading and tool search from both major vendors (85% token reduction, internal accuracy gains), embedding pre-selection (94.5% coverage at GitHub).
- **Schema-valid arguments.** Strict structured outputs.
- **Parallel reads and safe retries.** Native parallel tool calls; durable execution with idempotency keys.
- **Routing simple cases without an agent.** Documented as the routing workflow; small classifiers come within 2% of LLMs on in-scope intents.

## Contradicts or pressures Turnwise

- **Cache economics.** Prefix-match caching, vendor guidance and Manus all favour stable, append-only prompts. Rewriting the prefix per step while keeping history is 2× to 7× more expensive in my arithmetic. Cheaper cache reads (0.05×, 0.025×) widen the gap.
- **Orchestration is moving into model-written code.** Programmatic tool calling (37% fewer tokens in an internal test), Code Mode and CodeAct reduce model round trips. A policy re-invoked after every observation adds hops.
- **Minimal context can hurt strong models.** AdaCoM reports that higher-performing agents benefit from higher-fidelity context. Cognition argues that actions carry implicit decisions that a sliced context loses.
- **Simple nulls are strong.** Observation masking matched LLM summarisation at half the raw cost. Static `AGENTS.md` beat skills. This raises the bar for showing that a decision policy beats "simple host rules plus the same capable agent".
- **Rule-based control has a known utility cost.** The Action-Selector pattern "mostly loses the benefits of an LLM's fuzzy search abilities" and falsely blocks unanticipated benign requests. Google says static policies lack contextual understanding.
- **Small classifiers are brittle out of scope**, and multi-turn control, where Turnwise needs to win, is where they have no evidence.
- **Typed output envelopes may reduce reasoning quality** (Let Me Speak Freely), which bears on forcing model steps to return a rigid `StepOutcome`.

## Partial support for Turnwise

- Focused context and fewer instructions help (Chroma, NoLiMa, IFScale, SkillsBench's "at most three modules").
- Multi-turn drift is real (39% average drop), so consolidating state into a fresh prompt is a defensible idea.
- A non-LLM selector beat an LLM selector for tool shortlisting (GitHub).
- State-machine control improved on ReAct at lower cost (StateFlow), on dated baselines.
- Model-based defences fall to adaptive attacks (above 90%), which supports deterministic host checks.
- Removing the model's load decision fixed a 56% non-invocation problem (Vercel). A host policy also removes that decision.

## Open (no verified evidence either way)

- Whether a non-generative per-step policy beats host rules plus a native agent, a native agent with tool search and skills, or a checklist-prompted native agent on held-out multi-turn tasks, in success, pass^k, billed cost and latency.
- The billed cost of Turnwise's actual prompts under real caching.
- The accuracy of a non-LLM instruction-block selector under distribution shift and out-of-scope input.
- Whether long-context degradation results from 2023–2025 still hold at the same size on 2026 frontier models.
- Utility and attack success for Turnwise's host on AgentDojo or a similar suite.

## Surprising or contradictory points worth flagging

1. The two best-known "instructions in context" results disagree: Vercel found static context decisive (100% against 53%), ETH found context files generally do not improve success and cost over 20% more. They differ in task (new API knowledge versus general repository tasks), which suggests the value is in *missing knowledge*, not in instruction volume.
2. The largest code-orchestration token figures (98.7%, 99.9%) come with no accuracy evaluation. The one figure with a stated evaluation is far smaller (37%), with accuracy gains of about 3 to 5 points.
3. On BFCL single-turn calls, a 4B model is within one to three points of the top models, while multi-turn spreads from 22% to 68%. The "light model versus heavy model" decision matters for multi-turn state, not for picking a tool.
4. Manus, the loudest advocate of never touching the prefix, also runs a hand-built state machine that masks actions at decode time. A deterministic controller and a stable cached prompt are compatible if the controller constrains outputs instead of rewriting inputs.
5. Microsoft's governance toolkit claims full OWASP coverage in its description while its own badge encodes 7 full and 3 partial.
6. Realised caching savings in the one independent study (41–81% best mode) fall short of the theoretical figure, and full-context caching sometimes made latency worse. Cache arithmetic should be treated as an upper bound.

---

# Source table

V = opened and read on 2026-11-20. A = abstract page only. NV = not verified.

## Part 1

| # | Title | Authors / organisation | Date | Type | URL | Key number | Status |
|---|---|---|---|---|---|---|---|
| 1 | RAG-MCP | Gan, Sun | 2025-05-06 | Preprint | https://arxiv.org/abs/2505.03275 | 43.13% vs 13.62%; tokens −50%+ | A |
| 2 | Less is More (edge function calling) | Paramanayakam et al. | 2024-11-23 | DATE 2025 | https://arxiv.org/abs/2411.15399 | time −70%, power −40% | A |
| 3 | ToolRet | Shi et al. | 2025-03-03 | ACL 2025 | https://arxiv.org/abs/2503.01763 | 7.6k tasks, 43k tools | A |
| 4 | Introducing advanced tool use | Anthropic | 2025-11-24 | Vendor blog | https://www.anthropic.com/engineering/advanced-tool-use | −85% tokens; 49→74%, 79.5→88.1%; PTC −37% | V |
| 5 | Tool search tool | Anthropic | read 2026-11-20 | Official docs | https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool | degrades past 30–50 tools | V |
| 6 | Tool search | OpenAI | read 2026-11-20 | Official docs | https://developers.openai.com/api/docs/guides/tools-tool-search | no numbers | V |
| 7 | Function calling | OpenAI | read 2026-11-20 | Official docs | https://developers.openai.com/api/docs/guides/function-calling | fewer than 20 functions | V |
| 8 | Making GitHub Copilot smarter with fewer tools | GitHub | 2025-11-19 | Vendor blog | https://github.blog/ai-and-ml/github-copilot/how-were-making-github-copilot-smarter-with-fewer-tools/ | 94.5 / 87.5 / 69.0% coverage; 40→13 tools | V |
| 9 | Tool-space interference in the MCP era | Microsoft Research | 2025-09-11 | Vendor research blog | https://www.microsoft.com/en-us/research/blog/tool-space-interference-in-the-mcp-era-designing-for-agent-compatibility-at-scale/ | 1,470 servers; 775 collisions | V |
| 10 | Tool2Vec | Moon et al. | 2024-09-02 | Preprint | https://arxiv.org/abs/2409.02141 | Recall@K +27.28 / +30.5 | A |
| 11 | TinyAgent | Erdogan et al. | 2024-09-01 | EMNLP 2024 demo | https://arxiv.org/abs/2409.00608 | 1.1B and 7B models | A |
| 12 | Code execution with MCP | Anthropic | 2025-11-04 | Vendor blog | https://www.anthropic.com/engineering/code-execution-with-mcp | 150,000→2,000 tokens (illustrative) | V |
| 13 | Code Mode: the better way to use MCP | Cloudflare | 2025-09-26 | Vendor blog | https://blog.cloudflare.com/code-mode/ | no evaluation | V |
| 14 | Code Mode: an entire API in 1,000 tokens | Cloudflare | 2026-02-20 | Vendor blog | https://blog.cloudflare.com/code-mode-mcp/ | 1.17M→~1,000 tokens | V |
| 15 | CodeAct | Wang et al. | 2024-02-01 | ICML 2024 | https://arxiv.org/abs/2402.01030 | up to +20% success | A |
| 16 | What are agents? (smolagents) | Hugging Face | read 2026-11-20 | Official docs | https://huggingface.co/docs/smolagents/conceptual_guides/intro_agents | — | V |
| 17 | Programmatic tool calling | Anthropic | read 2026-11-20 | Official docs | https://platform.claude.com/docs/en/agents-and-tools/tool-use/programmatic-tool-calling | — | V |
| 18 | LLMCompiler | Kim et al. | 2023-12-07 | ICML 2024 | https://arxiv.org/abs/2312.04511 | 3.7× latency, 6.7× cost | A |
| 19 | ReWOO | Xu et al. | 2023-05-23 | Preprint | https://arxiv.org/abs/2305.18323 | 5× tokens, +4% | A |
| 20 | Speculative Actions | Ye et al. | 2025-10-05 | Preprint | https://arxiv.org/abs/2510.04371 | 55% prediction, −20% latency | A |
| 21 | Speculate with Memory | Li et al. | 2026-07-14 | Preprint | https://arxiv.org/abs/2607.12236 | +19–39% relative | A |
| 22 | Parallel tool use | Anthropic | read 2026-11-20 | Official docs | https://platform.claude.com/docs/en/agents-and-tools/tool-use/parallel-tool-use | — | V |
| 23 | semantic-router | aurelio-labs | read 2026-11-20 | Source repo | https://github.com/aurelio-labs/semantic-router | no accuracy numbers | V |
| 24 | CLINC150 | Larson et al. | 2019-09-04 | EMNLP-IJCNLP 2019 | https://arxiv.org/abs/1909.02027 | 150 intents | A |
| 25 | Intent Detection in the Age of LLMs | Arora et al. | 2024-10-02 | EMNLP 2024 Industry | https://arxiv.org/abs/2410.01627 | within 2%, −50% latency | A |
| 26 | Task-Oriented Dialogue with In-Context Learning | Bocklisch et al. (Rasa) | 2024-02-19 | Vendor preprint | https://arxiv.org/abs/2402.12234 | — | A |
| 27 | StateFlow | Wu et al. | 2024-03-17 | Preprint | https://arxiv.org/abs/2403.11322 | +13% / +28%; 5× / 3× cheaper | A |
| 28 | Structured outputs | OpenAI | read 2026-11-20 | Official docs | https://developers.openai.com/api/docs/guides/structured-outputs | — | V |
| 29 | JSONSchemaBench | Geng et al. | 2025-01-18 | Preprint | https://arxiv.org/abs/2501.10868 | 10K schemas | A |
| 30 | Let Me Speak Freely? | Tam et al. | 2024-08-05 | Preprint | https://arxiv.org/abs/2408.02442 | — | A |
| 31 | Building effective agents | Anthropic | 2024-12-19 | Vendor guidance | https://www.anthropic.com/engineering/building-effective-agents | — | V |
| 32 | 12-factor agents | Dex Horthy | 2025 | Practitioner guide | https://github.com/humanlayer/12-factor-agents | — | V |
| 33 | Activity definition | Temporal | read 2026-11-20 | Official docs | https://docs.temporal.io/activity-definition | — | V |
| 34 | Durable agents | Restate | read 2026-11-20 | Official docs | https://docs.restate.dev/ai/patterns/durable-agents | — | V |
| 35 | DBOS agent guidance | DBOS | — | — | — | — | NV |
| 36 | MCP specification: Tools | MCP project | 2025-06-18 | Specification | https://modelcontextprotocol.io/specification/2025-06-18/server/tools | — | V |
| 37 | MCP specification: Schema (ToolAnnotations) | MCP project | 2025-11-25 | Specification | https://modelcontextprotocol.io/specification/2025-11-25/schema | — | V |
| 38 | Google's Approach for Secure AI Agents | Díaz, Kern, Olive | 2025-05 | Vendor white paper | https://services.google.com/fh/files/misc/googles_approach_for_secure_ai_agents.pdf | — | V |
| 39 | Policy in Amazon Bedrock AgentCore | AWS | read 2026-11-20 | Official docs | https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy.html | — | V |
| 40 | Progent | Shi et al. | 2025-04-16 | Preprint | https://arxiv.org/abs/2504.11703 | ASR 39.9→1.0%; 70.3→3.9% | V |
| 41 | AgentSpec | Wang, Poskitt, Sun | 2025-03-24 | ICSE 2026 | https://arxiv.org/abs/2503.18666 | >90%; P 95.56%, R 70.96% | A |
| 42 | CaMeL | Debenedetti et al. | 2025-03-24 | Preprint | https://arxiv.org/abs/2503.18813 | 77% vs 84% | A |
| 43 | Design Patterns for Securing LLM Agents | Beurer-Kellner et al. | 2025-06-10 | Preprint | https://arxiv.org/abs/2506.08837 | six patterns | V |
| 44 | Agents Rule of Two | Meta | 2025-10-31 | Vendor blog | https://ai.meta.com/blog/practical-ai-agent-security/ | — | V |
| 45 | Invariant Guardrails | Invariant Labs | read 2026-11-20 | Source repo | https://github.com/invariantlabs-ai/invariant | — | V |
| 46 | Agent Governance Toolkit | Microsoft | read 2026-11-20 | Source repo | https://github.com/microsoft/agent-governance-toolkit | 10/10 claim vs 7+3 badge | V |
| 47 | ShieldAgent | Chen, Kang, Li | 2025-03-26 | Preprint | https://arxiv.org/abs/2503.22738 | recall 90.1% | A |
| 48 | GuardAgent | Xiang et al. | 2024-06-13 | ICML 2025 | https://arxiv.org/abs/2406.09187 | 98% / 83% | A |
| 49 | The Attacker Moves Second | Nasr et al. | 2025-10-10 | Preprint | https://arxiv.org/abs/2510.09023 | >90% vs 12 defences | A |
| 50 | OWASP Top 10 for Agentic Applications 2026 | OWASP | 2025-12-09 | Community standard | https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/ | categories NV | V (title, date) |
| 51 | AgentDojo | Debenedetti et al. | 2024-06-19 | Preprint | https://arxiv.org/abs/2406.13352 | 97 tasks, 629 cases | A |
| 52 | AgentDojo results | ETH SPY Lab | read 2026-11-20 | Benchmark site | https://agentdojo.spylab.ai/results/ | GPT-4o ASR 47.69% | V |
| 53 | τ-bench | Yao et al. (Sierra) | 2024-06-17 | Preprint | https://arxiv.org/abs/2406.12045 | 61.2% / 35.2%; pass^8 <25% | V |
| 54 | τ²-bench | Barres et al. (Sierra) | 2025-06-09 | Preprint | https://arxiv.org/abs/2506.07982 | — | A |
| 55 | τ-bench leaderboard | Sierra | read 2026-11-20 | Benchmark site | https://taubench.com/ | top 87.9% pass^1 | V |
| 56 | HAL: TAU-bench Airline | Princeton | read 2026-11-20 | Benchmark site | https://hal.cs.princeton.edu/taubench_airline | $11.36–$180.49 per run | V |
| 57 | ToolSandbox | Lu et al. (Apple) | 2024-08-08 | Preprint | https://arxiv.org/abs/2408.04682 | — | A |
| 58 | BFCL paper | Patil et al. | 2025 | ICML 2025 | https://proceedings.mlr.press/v267/patil25a.html | — | V |
| 59 | BFCL v4 data | UC Berkeley | read 2026-11-20 | Benchmark data | https://gorilla.cs.berkeley.edu/data_overall.csv | see section 1.8 | V |
| 60 | MCP-Universe | Luo et al. (Salesforce) | 2025-08-20 | Preprint | https://arxiv.org/abs/2508.14704 | GPT-5 43.72% | A |
| 61 | MCPMark | Wu et al. | 2025-09-28 | Preprint | https://arxiv.org/abs/2509.24002 | 52.56% pass@1, 33.86% pass^4 | A |
| 62 | MCP-Bench | Wang et al. (Accenture) | 2025-08-28 | Preprint | https://arxiv.org/abs/2508.20453 | 28 servers, 250 tools | A |
| 63 | AppWorld | Trivedi et al. | 2024-07-26 | ACL 2024 | https://arxiv.org/abs/2407.18901 | ~49% / ~30% | A |
| 64 | WorkArena | Drouin et al. (ServiceNow) | 2024-03-12 | Preprint | https://arxiv.org/abs/2403.07718 | 33 tasks | A |
| 65 | TheAgentCompany | Xu et al. | 2024-12-18 | Preprint | https://arxiv.org/abs/2412.14161 | 30% | A |
| 66 | CRMArena-Pro | Huang et al. (Salesforce) | 2025-05-24 | Preprint | https://arxiv.org/abs/2505.18878 | 58% / 35% | A |
| 67 | ST-WebAgentBench | Levy et al. (IBM) | 2024-10-09 | ICLR 2026 | https://arxiv.org/abs/2410.06703 | 222 tasks; CuP < 2/3 | A |
| 68 | ITBench | Jha et al. (IBM) | 2025-02-07 | Preprint | https://arxiv.org/abs/2502.05352 | 13.8% / 25.2% / 0% | A |
| 69 | Rigorous Agentic Benchmarks (ABC) | Zhu et al. | 2025-07-03 | Preprint | https://arxiv.org/abs/2507.02825 | up to 100% misestimate | A |
| 70 | AI Agents That Matter | Kapoor et al. | 2024-07-01 | Preprint | https://arxiv.org/abs/2407.01502 | — | A |

Affiliation note: the Accenture attribution for MCP-Bench (row 62) is from memory and was not on the abstract page; treat it as NV.

## Part 2

| # | Title | Authors / organisation | Date | Type | URL | Key number | Status |
|---|---|---|---|---|---|---|---|
| 71 | Lost in the Middle | Liu et al. | 2023-07-06 | TACL | https://arxiv.org/abs/2307.03172 | — | A |
| 72 | Context Rot | Chroma | 2025-07-14 | Vendor report | https://www.trychroma.com/research/context-rot | 18 models; 300 vs 113k tokens | V |
| 73 | NoLiMa | Modarressi et al. | 2025-02-07 | ICML 2025 | https://arxiv.org/abs/2502.05167 | 99.3→69.7% at 32K | A |
| 74 | LLMs Get Lost In Multi-Turn Conversation | Laban et al. | 2025-05-09 | Preprint | https://arxiv.org/abs/2505.06120 | −39% average | A |
| 75 | Effective context engineering for AI agents | Anthropic | 2025-09-29 | Vendor guidance | https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents | — | V |
| 76 | Managing context on the Claude Developer Platform | Anthropic | 2025-09-29 | Vendor blog | https://claude.com/blog/context-management | +39%, +29%, −84% tokens | V |
| 77 | Context editing | Anthropic | read 2026-11-20 | Official docs | https://platform.claude.com/docs/en/build-with-claude/context-editing | trigger 100,000 tokens | V |
| 78 | Agent Skills (blog) | Anthropic | 2025-10-16 | Vendor blog | https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills | — | V |
| 79 | Agent Skills (docs) | Anthropic | read 2026-11-20 | Official docs | https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview | ~100 tokens per skill; <5k body | V |
| 80 | Context Engineering for AI Agents: Lessons from Building Manus | Yichao Ji | 2025-07-18 | Vendor blog | https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus | 100:1; $0.30 vs $3 per MTok | V |
| 81 | Don't Build Multi-Agents | Walden Yan (Cognition) | 2025-06-12 | Vendor blog | https://cognition.com/blog/dont-build-multi-agents | — | V |
| 82 | Context Engineering | LangChain | 2025-07-02 | Vendor blog | https://www.langchain.com/blog/context-engineering-for-agents | — | V |
| 83 | How Long Contexts Fail | Drew Breunig | 2025-06-22 | Personal blog | https://www.dbreunig.com/2025/06/22/how-contexts-fail-and-how-to-fix-them.html | 46 vs 19 tools | V |
| 84 | Prompt caching | Anthropic | read 2026-11-20 | Official docs | https://platform.claude.com/docs/en/build-with-claude/prompt-caching | 1.25× / 2× / 0.1× | V |
| 85 | Tool use with prompt caching | Anthropic | read 2026-11-20 | Official docs | https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-use-with-prompt-caching | — | V |
| 86 | Prompt caching | OpenAI | read 2026-11-20 | Official docs | https://developers.openai.com/api/docs/guides/prompt-caching | 1.25× / 2.5× / 0.1× | V |
| 87 | Caching | Google Gemini | read 2026-11-20 | Official docs | https://aistudio.google.com/docs/caching | discount NV | V (mechanics) |
| 88 | Don't Break the Cache | Lumer et al. (PwC) | 2026-01-09 | Preprint | https://arxiv.org/html/2601.06007v2 | cost −41–81%; TTFT see table | V |
| 89 | Compaction | OpenAI | read 2026-11-20 | Official docs | https://developers.openai.com/api/docs/guides/compaction | — | V |
| 90 | Context compaction | Google ADK | read 2026-11-20 | Official docs | https://adk.dev/context/compaction/ | — | V |
| 91 | Dynamic context discovery | Cursor | 2026-01-06 | Vendor blog | https://cursor.com/blog/dynamic-context-discovery | −46.9% tokens | V |
| 92 | LLMLingua | Jiang et al. (Microsoft) | 2023-10-09 | EMNLP 2023 | https://arxiv.org/abs/2310.05736 | up to 20× | A |
| 93 | The Complexity Trap | Lindenbauer et al. (JetBrains) | 2025-08-29 | DL4C at NeurIPS 2025 | https://arxiv.org/abs/2508.21433 | cost roughly halved | A |
| 94 | ACON | Kang et al. | 2025-10-01 | ICML 2026 (per listing) | https://arxiv.org/abs/2510.00615 | −26–54% peak tokens | A |
| 95 | ACE | Zhang et al. | 2025-10-06 | ICLR 2026 (per listing) | https://arxiv.org/abs/2510.04618 | +10.6%, +8.6% | A |
| 96 | Dynamic Cheatsheet | Suzgun et al. | 2025-04-10 | Preprint | https://arxiv.org/abs/2504.07952 | 10→99% | A |
| 97 | MemGPT | Packer et al. | 2023-10-12 | Preprint | https://arxiv.org/abs/2310.08560 | — | A |
| 98 | Mem0 | Chhikara et al. | 2025-04-28 | Preprint | https://arxiv.org/abs/2504.19413 | +26% relative | A |
| 99 | A-MEM | Xu et al. | 2025-02-17 | NeurIPS 2025 | https://arxiv.org/abs/2502.12110 | — | A |
| 100 | Sleep-time Compute | Lin et al. | 2025-04-17 | Preprint | https://arxiv.org/abs/2504.13171 | ~5×; +13% / +18% | A |
| 101 | AdaCoM | Yi et al. | 2026-05-29 | Preprint | https://arxiv.org/abs/2605.30785 | — | A |
| 102 | Memory as Action | Zhang et al. | 2025-10-14 | Preprint | https://arxiv.org/abs/2510.12635 | −51% context | A |
| 103 | IFScale | Jaroslawicz et al. | 2025-07-15 | Preprint | https://arxiv.org/abs/2507.11538 | 68% at 500 instructions | A |
| 104 | AGENTS.md outperforms skills | Vercel | 2026-01-27 | Vendor blog | https://vercel.com/blog/agents-md-outperforms-skills-in-our-agent-evals | 100 / 79 / 53 / 53%; 56% not invoked | V |
| 105 | Evaluating AGENTS.md | Gloaguen et al. (ETH) | 2026-02-12 | Preprint | https://arxiv.org/abs/2602.11988 | cost +20% | A |
| 106 | SkillsBench | Li et al. | 2026-02-13 | Preprint | https://arxiv.org/abs/2602.12670 | 33.9→50.5% | A |
| 107 | MIPRO | Opsahl-Ong et al. | 2024-06-17 | EMNLP 2024 | https://arxiv.org/abs/2406.11695 | up to +13% | A |
| 108 | GEPA | Agrawal et al. | 2025-07-25 | ICLR 2026 (per listing) | https://arxiv.org/abs/2507.19457 | +6% avg vs GRPO; 35× fewer rollouts | A |
| 109 | Parlant | Emcie | read 2026-11-20 | Source repo | https://github.com/emcie-co/parlant | no evaluation | V |

## Items not verified or not found

- DBOS guidance for durable agents: no primary page opened.
- OWASP Agentic Top 10: the ten category names were not on the page I opened.
- Gemini cached-token discount rate: not on the page I opened.
- Speculate with Memory: restriction to read-only actions seen only in a search snippet.
- SkillsBench: self-generated-skills delta and task-regression counts seen only in search snippets; versions differ.
- Speculative Actions: ICLR 2026 acceptance seen only in search results.
- MCP-Bench author affiliation.
- AWS AgentCore Policy release status and date.
- Invariant Labs acquisition status.
- A neutral peer-reviewed 2026 study of MCP tool-count thresholds: not found.
- A direct comparison of non-LLM per-step instruction selection against static, model-selected and retrieved instructions: not found.
- 2026 replications of long-context degradation on current frontier models: not found.
- Benchmark running costs other than τ-bench and BFCL: unknown.
