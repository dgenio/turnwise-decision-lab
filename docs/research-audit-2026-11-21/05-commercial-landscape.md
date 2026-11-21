# Turnwise Decision Lab: commercial and competitive diligence

> **Status: dated external research note, archived 2026-11-21. Historical (accurate for its date).** Written by an AI research pass for the red-team review in [#94](https://github.com/dgenio/turnwise-decision-lab/issues/94). Research only: no model was called and no experiment was run by this repository. Verification flags are the author's own; the [audit index](README.md) says what was independently re-checked and lists known corrections. Do not rewrite this file; add a dated note instead.

Prepared 2026-11-20. Research only; nothing in any repository was modified, nothing was posted, nobody was contacted.

**How to read this.** Every factual claim carries a source number `[S#]` that maps to the Source table at the end. Sources marked **OPENED** were fetched and read during this session. Sources marked **NOT OPENED** are known only from a search-result summary or from a secondary page and must be treated as **NOT VERIFIED**. Vendor statements about their own traction (ARR, customers, savings) are **marketing claims** even when the page was opened; they are labelled as such. GitHub star counts were read from the repository pages on 2026-11-20 through an automated page summariser, are rounded as GitHub displays them, and are a weak proxy for adoption.

---

## 0. Bottom line

1. **No credible commercial moat exists for any of the nine product shapes.** Each is already shipped, generally available, by a hyperscaler, a model provider, or a company valued above $1B, and in the two shapes closest to the Turnwise thesis (model routing, runtime policy) the incumbent price is zero or near zero.
2. **The thesis itself is validated as a demand signal and invalidated as a product gap.** The best-funded conversational-agent vendors publicly say LLM-only control is not reliable enough and have shipped deterministic control alongside LLM reasoning (Salesforce Agent Script and Atlas as "a state machine executor", Rasa CALM, Sierra, Intercom Procedures, Decagon AOPs) [S39][S41][S45][S46][S42]. AWS and Microsoft ship deterministic policy engines that intercept every agent tool call [S24][S27]. The idea is right; it is also already built by people with distribution.
3. **Budget does exist in runtime policy and agent security, but a new entrant cannot reach it.** It flows through CISO channels to security platforms that bought the startups (Palo Alto Networks, Check Point, F5, Snyk, SentinelOne, OpenAI) or is bundled by hyperscalers at prices like $0.000025 per authorization request [S25]. A standalone authorization vendor (Oso Cloud) was sold in October 2026 for C$1.9M in assets at roughly $5.3M ARR while its team joined Temporal [S33].
4. **Routing is commoditised, and the market is trading up, not down.** Azure, AWS, GitHub, OpenRouter, Ramp and NVIDIA all route per request or per agent step; several charge nothing for the routing layer [S5][S4][S7][S12][S9][S10]. Meanwhile frontier models' share of enterprise spend rose from 35% to 63% in a year and small closed models' token share fell from 29% to 13% [S16].
5. **The rational outcome is a research contribution plus a plugin, not a company.** The least-crowded contributions are (a) an independent, pre-registered "step-necessity" audit methodology with mandatory null baselines, (b) a vendor-neutral control-ownership conformance test suite, and (c) adapters that express the Turnwise policy inside an existing framework. None has a commercial moat. This is consistent with the repository's own stated expected outcome of SHRINK/STOP when native frameworks do the same job.

---

## 1. Table: product shape to verdict

| # | Product shape | Direct competitors and substitutes | Maturity and funding | Evidence of willingness to pay | Plausible moat for a newcomer | Verdict |
|---|---|---|---|---|---|---|
| 1 | Independent decision-policy component | Salesforce Agent Script + Atlas (hybrid reasoning) [S39]; Rasa CALM flows [S41]; Sierra Agent SDK (declarative goals, deterministic guardrails) [S45]; Intercom/Fin Procedures [S46]; Decagon AOPs [S42]; Parlant (OSS, 18.3k stars) [S48]; LangGraph (45.2k stars) [S38]; Microsoft Agent Governance Toolkit (MIT) [S27]; AWS AgentCore Policy [S24] | GA at Salesforce (Feb 2026) [S39]; Sierra $950M round above $15B [S43]; Decagon $250M at $4.5B [S42]; Fin bought by Salesforce [S47] | Yes, but for the outcome (resolved tickets), not for a policy library. Sierra self-reports $400M+ ARR (marketing claim) [S44] | **None.** The pattern is a design choice any team implements in a few hundred lines; 17 of 20 case-study teams in the production-agent study built custom in-house [S57] | **No product.** Publish as a pattern and reference implementation |
| 2 | Agent optimisation middleware | LangSmith Engine and gateways [S36]; Arize Cost Agent (Enterprise beta) [S51]; Not Diamond prompt optimisation and routing [S13]; NVIDIA NeMo Switchyard (open source) [S10]; Ramp Router [S9]; Braintrust Loop [S62, NOT OPENED] | LangChain $300M at $3B [S36]; Braintrust $80M at $800M [S61, NOT OPENED] | Bundled feature of observability platforms; no evidence of standalone purchase | **None.** Whoever already holds the traces wins | **Feature, not a company** |
| 3 | Adaptive inference controller / model router | Azure Foundry Model Router (GA, 45 models, per agent step) [S5]; Bedrock Intelligent Prompt Routing (GA) [S4]; OpenRouter Auto and Auto Code [S12]; GitHub Copilot auto [S7]; GPT-5 in-product router [S8]; Ramp Router.com [S9]; NVIDIA Switchyard [S10]; Google API Gateway model routing (preview) [S14]; effort parameters [S15]; Not Diamond, Martian, Unify, Requesty, LiteLLM, Kong, Cloudflare | OpenRouter $113M Series B, then agreed sale to Stripe [S1][S2]; Portkey bought by Palo Alto Networks [S3]; Not Diamond and Martian small and re-positioning [S13][S66, NOT OPENED] | Routing layer itself is priced at or near zero: OpenRouter no router fee [S12], Ramp free through 2026 [S9], GitHub gives a 10% discount for using auto [S7]. Money is made on token volume, payments and security | **None.** Routers are trained on traffic a newcomer does not have ("billions of interactions") [S5] | **STOP.** Fully commoditised |
| 4 | Tool orchestration layer | LangGraph, CrewAI, OpenAI Agents SDK, Google ADK, PydanticAI, Mastra, Microsoft Agent Framework, Vercel AI SDK; Temporal, Restate, Inngest, DBOS; AgentCore Gateway; MCP gateways | Temporal $550M at $12.55B [S35]; LangChain $3B [S36]; Mastra $35M total [S37]; star counts in section 4 | Paid for durability and hosting (Temporal 4,300+ paying customers, marketing claim) [S35] | **None** | **STOP.** Also an explicit non-goal of the repo |
| 5 | Context-engineering infrastructure | Provider-native context editing, memory tool, compaction [S56][S70, NOT OPENED]; AgentCore Memory [S25]; Mem0 [S60]; Letta, Zep, Cognee, LangMem | Mem0 $24M, 69.3k stars [S60][S38]; hyperscaler GA | Some (Mem0 claims 186M API calls in Q3 2025, marketing claim) [S60] | **None**, and Turnwise has no context IP | **Not applicable** |
| 6 | Agent evaluation and diagnostics | LangSmith (7,000+ orgs, marketing claim) [S36]; Braintrust; Arize/Phoenix; Langfuse (ClickHouse) [S49]; W&B Weave (CoreWeave) [S63, NOT OPENED]; Promptfoo (OpenAI) [S29]; AgentCore Evaluations [S25]; HAL [S53]; Inspect | Heavy consolidation in 2025–2026; 84% of AI builders already use evals and observability [S16] | Yes, but incumbents hold the trace data and are being absorbed into platforms | **Weak.** Only independence and methodology | **Research contribution only** (see section 9) |
| 7 | Policy verification tooling | AgentCore Policy with automated-reasoning checks on policies [S24]; Bedrock Automated Reasoning checks [S71, NOT OPENED]; Microsoft AGT [S27]; Snyk/Invariant [S19]; Promptfoo into OpenAI Frontier [S29]; Zenity, Noma, Lakera, Protect AI, Prompt Security, CalypsoAI | Hyperscaler GA; security M&A wave; Zenity $125M Series C [S32] | Yes at CISO level; Gartner says under 1% of agentic budgets go to "guardian agents" today [S59] | **Weak.** A vendor-neutral conformance suite has reputational, not commercial, defensibility | **OSS test suite; not a company** |
| 8 | Cost/reliability optimisation service | Ramp Router [S9]; Stripe + OpenRouter [S2]; Not Diamond Code (waitlist) [S13]; Arize Cost Agent [S51]; LangSmith gateway budgets [S36][S52]; provider caching and effort knobs [S15][S16] | Distribution owned by fintechs, gateways and observability vendors | Rising: enterprises spent about 2.5x plan in 2026 on average [S16]. But the buyers' first fixes are caching, discounts and free routers | **None** | **Consulting at most** |
| 9 | Research benchmarking platform | HAL (Princeton, ICLR 2026) [S53]; Inspect (UK AISI) [S72, NOT OPENED]; LangChain Deep Agents evals [S11]; Not Diamond "interactive benchmarks" [S13]; academic work on trace compilation [S54][S55] | Academic and grant funded | Essentially none | Reputation and rigour only | **The realistic home for this work**: contribute tasks and method to an existing harness |

---

## 2. Model routing and adaptive inference

**What exists.**

- **Azure Foundry Model Router** is generally available (version `2025-11-18`). As of 2026-11-18 it routes across 45 models from OpenAI, Anthropic, Microsoft AI, xAI, DeepSeek, Meta and Fireworks, with Balanced, Quality and Cost modes. Microsoft's documentation states it is "built for agents and coding tools" and that "each step of an agent ... can get a different model", with session affinity in preview to protect prompt-cache hits. Pricing is a routing fee per 1M input tokens plus the selected model's usage. `Auto` (no deployment) is in preview [S5]. The fee amount could not be verified because the pricing page rendered `$-` [S6].
- **Amazon Bedrock Intelligent Prompt Routing** has been generally available since 2025-04-22, routing within a model family (Claude, Llama, Nova) [S4].
- **OpenRouter Auto Router** selects both a model and a reasoning effort per request using a "fast decision model"; there is no extra router fee. A sibling `Auto Code` router targets coding agents [S12].
- **GitHub Copilot auto model selection** evaluates each prompt individually, offers Efficiency, Balance and Intelligence tiers (2026-09-14), bills by the model selected, and gives paid subscribers a 10% discount for using it [S7].
- **OpenAI** shipped an in-product "real-time router" with GPT-5 on 2025-08-07, choosing between a fast and a reasoning model from conversation type, complexity, tool needs and explicit intent [S8]. Whether the API exposes the same router was not verified.
- **Effort knobs** make "light versus heavy call" a parameter on a single model. Anthropic's `effort` is a stable feature with levels `low` to `max`, and can be changed per message while preserving the prompt cache [S15].
- **NVIDIA NeMo Switchyard** (announced 2026-08-11, described by NVIDIA as fully open source) routes at each step of a multi-turn agent task with a stage router and an escalation router, and lets developers "bring their own routing algorithms". Named integrators include LangChain, Ramp, Cognition, LiteLLM and Kong [S10].
- **Ramp Router.com** (2026-08-19) offers free routing through 2026 and claims customers save 40% (marketing claim) [S9].
- **Google Cloud API Gateway model routing** entered public preview on 2026-08-04, but it is rule-based mapping of requested model names, not learned routing [S14].

**Funding, exits and pivots 2024–2026.**

- **OpenRouter**: $113M Series B led by CapitalG on 2026-05-26, reported at about $1.3B (valuation attributed by TechCrunch to the New York Times, not disclosed by the company) [S1]. On 2026-08-19 **Stripe announced an agreement to acquire OpenRouter**; the price is not in Stripe's announcement and closing was not verified [S2]. Press figures of "more than $7B" or "$8B" are **NOT VERIFIED**.
- **Portkey**: Palo Alto Networks closed its acquisition on 2026-05-29 and made Portkey the AI gateway for Prisma AIRS; price not stated [S3]. A $15M Series A three months earlier is reported by secondary sources only [S64, NOT OPENED].
- **Not Diamond**: no funding or customer announcement on its blog in 2026; its 2026 output is prompt optimisation (GA 2026-01-20), then coding-agent routing with "Not Diamond Code" on a waitlist [S13]. Its only round reported by aggregators is a $2.3M pre-seed in July 2024 [S65, NOT OPENED].
- **Martian**: $9M seed in November 2023; third-party profiles say it now presents itself as a research organisation [S66, NOT OPENED].
- **Unify, Requesty, LiteLLM**: no primary funding pages were opened; treat all reported figures as NOT VERIFIED [S67, NOT OPENED]. LiteLLM's repository shows 63.6k stars [S38].

**Has routing been commoditised?** Yes, on three independent lines of evidence.

1. *Price.* The routing layer is free at OpenRouter [S12] and Ramp [S9], discounted at GitHub [S7], and a small per-token fee at Azure [S5].
2. *Absorption.* The two best-known independent gateway and routing startups were bought within three months of each other, one by a payments company and one by a security company [S2][S3]. Neither buyer is paying for a routing algorithm; they are buying traffic, billing and a policy enforcement point.
3. *Demand direction.* Menlo Ventures' 2026 report (a VC with stakes in Anthropic and OpenRouter; a survey of nearly 400 US enterprise decision-makers plus a bottom-up model) finds frontier models' share of enterprise spend rose from 35% to 63% and of tokens from 18% to 42% between Q3 2025 and Q3 2026, while small closed models' token share fell from 29% to 13%. Its conclusion: buyers "continue to prioritize capability over cost in model selection" [S16].

**One uncomfortable data point for the "light model for easy steps" thesis.** LangChain's own Switchyard benchmark (145 multi-step tasks, five runs) found routed execution cut cost 74% against frontier-only at a six-point accuracy loss, but the routed arm scored only 2.3 points above the cheap model alone, inside the 2.7-point run-to-run noise, so the authors state they cannot claim routing beat the cheap model. The LLM judge consumed 21.2% of routed spend [S11]. A non-LLM policy would remove the judge cost, which is the one place the Turnwise idea has a measurable technical angle; it is not a commercial angle, because Switchyard already accepts custom routers [S10].

---

## 3. Agent guardrails, runtime policy and authorization

**The claim to test: "this is where budget actually exists." Confirmed, with a qualification that matters.**

**Hyperscaler products (GA unless stated).**

- **AWS Bedrock AgentCore Policy**: GA on 2026-03-03 in 13 regions [S23]. The developer guide describes "deterministic policies" evaluated at the Gateway "at the boundary outside of agent's code", authored in Cedar or in natural language that is translated to Cedar and checked with automated reasoning for over-permissive, over-restrictive or unsatisfiable policies. It also supports "Dogwood" policies with session-aware temporal conditions, with AWS's own examples being "requiring that an approval was granted before a transfer, blocking an action after it has run a set number of times, or keeping a running total under a budget" [S24]. That is, almost word for word, the Turnwise host-authority invariant (writes held for approval, budgets enforced by the host). Price: $0.000025 per authorization request [S25].
- **Microsoft Agent 365**: GA on 2026-05-01 at $15 per user per month, also bundled in Microsoft 365 E7 at $99 [S26]. Entra Agent ID GA status is from secondary sources only [S68, NOT OPENED].
- **Microsoft Agent Governance Toolkit**: MIT-licensed, announced 2026-04-02, a stateless policy engine that "intercepts every agent's action before execution" with a claimed latency under 0.1 ms p99, accepting YAML, OPA Rego and Cedar, with adapters for LangGraph, OpenAI Agents SDK, PydanticAI, LlamaIndex and others [S27]; 6.6k stars [S28].
- **Google AP2 (Agent Payments Protocol)**: announced 2025-09-16 with more than 60 partner organisations; cryptographically signed "mandates" as proof of user authority. An open protocol, not a GA product [S34]. Model Armor and Agent Engine governance were **not verified**.
- **Claude Agent SDK**: tool calls pass through hooks, deny rules, ask rules, permission mode, allow rules, then a `canUseTool` callback; a `PreToolUse` hook denial applies even in bypass mode [S31]. "Model proposes, host decides" is therefore a documented default of a major vendor's SDK.
- **OpenAI**: Guardrails shipped with AgentKit on 2025-10-06, but OpenAI's own page now carries a notice dated 2026-06-03 that it is "winding down the Agent Builder and Evals products", unavailable from 2026-11-30, pointing users to the Agents SDK and ChatGPT Workspace Agents [S30].

**Acquisitions (verified from primary announcements unless stated).**

| Target | Acquirer | Date and status | Price | Source |
|---|---|---|---|---|
| Invariant Labs | Snyk | 2025-06-24, acquired | not disclosed | [S19] |
| Protect AI | Palo Alto Networks | 2025-07-22, completed | not stated | [S21] |
| Prompt Security | SentinelOne | 2025-08-05, definitive agreement | not stated in the summary | [S69, NOT OPENED: page returned HTTP 429 twice] |
| CalypsoAI | F5 | 2025-09-11, intent to acquire, close expected by 2025-09-30 | $180M | [S22] |
| Lakera | Check Point | 2025-09-16, agreement signed, close expected Q4 2025 | not stated (press estimate about $300M is NOT VERIFIED) | [S20] |
| Promptfoo | OpenAI | 2026-03-09, announced, subject to closing | not disclosed | [S29] |
| Portkey | Palo Alto Networks | 2026-05-29, closed | not stated | [S3] |
| Oso Cloud (assets) | Tiny | reported 2026-10-08 | C$1.9M at about $5.3M ARR; team to Temporal | [S33] |

Other deals reported only in secondary roundups (Proofpoint and Acuvity, Cyera and Oasis, Cato and Aim, CrowdStrike and Pangea, a claimed "40 AI-security deals in the first three quarters of 2026") are **NOT VERIFIED** [S73, NOT OPENED].

**Funding.** Zenity raised a $125M Series C led by Norwest on 2026-08-03, with 230 employees, valuation and revenue undisclosed [S32]. Noma's $100M Series B (July 2025) is from search summaries only [S74, NOT OPENED]. Lasso and Pillar were not researched to a verifiable standard.

**Market size signals.** Gartner's 2026-08-26 release reportedly forecasts the market for securing AI at about $2.8B in 2026 and $4.8B in 2027, with "AI governance platforms" only $275M in 2026 [S75, NOT OPENED: page returned HTTP 403]. Gartner's Avivah Litan is quoted saying businesses spend "less than 1% of their agentic AI budget on guardian agents today", rising to 5–7% by 2028 [S59].

**Assessment.**

- The budget is real, and it is where the acquirers are. But the pattern in the table is an **acqui-hire and tuck-in market**: every target was absorbed into a security platform or a model provider within roughly two years of founding.
- The enforcement primitive Turnwise demonstrates (deterministic host check on every tool call) is now a **$25-per-million-requests hyperscaler feature** [S25] and an MIT-licensed Microsoft library [S27].
- The Oso outcome is the cautionary case: an established, well-regarded authorization company pivoting to "authorization for agents" ended as an asset sale below its reported ARR [S33].
- Policy languages (Cedar, Rego) and standards work in OpenID AuthZEN are public goods; Permit.io and Cerbos MCP-gateway offerings are from search summaries only [S76, NOT OPENED].

---

## 4. Agent frameworks, orchestration and durable execution

**Is there room for another runtime? No.**

| Project | Evidence (dated) | Source |
|---|---|---|
| LangChain / LangGraph / LangSmith | $300M Series C at $3B on 2026-11-13, led by CapitalG; "more than 7,000 organizations" on LangSmith (marketing claim); now positioned as runtime, improvement and governance, with LLM and tool gateways. LangGraph 45.2k stars | [S36][S38] |
| Temporal | $550M Series E at $12.55B on 2026-09-14; 4,300+ paying customers; OpenAI, Snap, NVIDIA named (marketing claims). 24.5k stars. Hired Oso's team to build agent access controls | [S35][S38][S33] |
| CrewAI | 61.1k stars. Funding ($18M, October 2024) from secondary sources only | [S38][S77, NOT OPENED] |
| OpenAI Agents SDK (Python) | 30.8k stars; OpenAI now directs Agent Builder users to it | [S38][S30] |
| Mastra | $22M Series A on 2026-04-09, $35M total; 29.7k stars | [S37][S38] |
| Google ADK (Python) | 22.3k stars | [S38] |
| PydanticAI | 21.3k stars. Pydantic's $12.5M Series A from secondary sources only | [S38][S77, NOT OPENED] |
| LlamaIndex, Microsoft Agent Framework, Vercel AI SDK, Restate, Inngest, DBOS | Not verified from primary sources in this session | NOT VERIFIED |

Two further facts close the question. First, the Berkeley-led "Measuring Agents in Production" study found 85% of its 20 case-study teams built custom in-house implementations rather than adopting a framework, while 61% of survey respondents used one, led by LangChain/LangGraph at 25% [S57]. Teams that care about control write their own loop. Second, Menlo's 2026 infrastructure map lists exactly two names under "agent frameworks" (LangChain, Mastra) and three under "durable execution" (Temporal, Restate, Inngest) [S16]. The category has settled.

---

## 5. Deterministic-first conversational agents (the closest product analogue)

This cluster is the strongest evidence that the Turnwise thesis describes a real need, and the strongest evidence that incumbents already ship it.

**What they say publicly.**

- **Salesforce.** The architecture guide for the new Agentforce ("GA since February 2026") states the product "shifts from purely probabilistic LLM reasoning to a hybrid model", that "if you can express a decision as code, it should be written as logic", and that "the Atlas Reasoning Engine is a state machine executor" which runs deterministic nodes as code and calls the LLM only where prompt instructions exist [S39]. The Decoder, citing The Information, quotes SVP Sanjna Parulekar: "We all had more confidence in LLMs a year ago" (2025-12-25; the underlying Information article is paywalled and was not opened) [S40]. Salesforce then bought Fin (formerly Intercom), completing on 2026-09-10 [S47]; the roughly $3.6B price comes from the June announcement, which was not opened [S78, NOT OPENED].
- **Rasa (CALM).** "LLMs keep the conversation fluent but don't guess your business logic"; the LLM outputs discrete commands and flows execute, which Rasa says makes behaviour debuggable [S41]. This is the nearest published statement of "models propose, the host executes".
- **Sierra.** Since 2024-06-03: declarative goals plus "deterministic guardrails" so that "business logic is strictly and deterministically enforced"; the same post says LLM agents "hallucinate and go haywire" about 10% of the time (vendor assertion, no data) [S45]. Sierra raised $950M above $15B on 2026-05-04 [S43] and self-reports $400M+ ARR on 2026-10-30 (marketing claim, unaudited) [S44].
- **Intercom / Fin.** "Natural language is flexible, but some steps need to be exact"; code snippets where "absolute accuracy is essential", checkpoints for approval (2026-02-25) [S46].
- **Decagon.** Agent Operating Procedures; $250M Series D at $4.5B (2026-01-27) [S42]. The description of AOPs as natural language "compiled into code" is from secondary sources [NOT VERIFIED].
- **Parlant.** Open-source (Apache 2.0, 18.3k stars): on each turn it selects the relevant policies and procedures and gives only those to the model [S48]. An open-source, per-turn, policy-selecting conversational framework already exists.
- **Cognigy (NICE), PolyAI, Kore.ai, ServiceNow.** NICE closed its Cognigy acquisition on 2025-09-08 per search summaries of the press release; nothing else was verified [S79, NOT OPENED].

**Independent corroboration.** In the production-agent study, 80% of case studies used structured, predefined workflows rather than open-ended planning, and the authors conclude organisations "deliberately trade capability for controllability to maintain reliability" [S57].

**Reading.** Demand for deterministic control alongside LLM reasoning is established beyond reasonable doubt. Willingness to pay is also established, but it attaches to a full-stack customer-service product sold on outcomes with forward-deployed engineers [S16], not to a control library. The difference between Turnwise and Atlas or CALM (a typed non-LLM policy re-invoked after *every* observation, including model output) is an architectural nuance that no buyer in this market is asking for by name.

---

## 6. Agent evaluation, observability and diagnostics

**Consolidation, verified.**

- Langfuse acquired by ClickHouse, 2026-01-16; stays open source [S49]. 37.7k stars [S38].
- Humanloop: Anthropic acqui-hired the team (2025-08-13) and "did not acquire Humanloop's assets or its intellectual property" [S50].
- Promptfoo: OpenAI announced the acquisition on 2026-03-09 (subject to closing), to integrate into OpenAI Frontier; "trusted by over 25 percent of Fortune 500 companies" (marketing claim); open source continues [S29].
- OpenAI is winding down its own Evals product by 2026-11-30 [S30].
- Helicone acquired by Mintlify (2026-03-03) and W&B by CoreWeave (2025-05-05): search summaries only [S63, NOT OPENED]. Braintrust $80M Series B at $800M (2026-02-17): search summaries only [S61, NOT OPENED]. Galileo and Patronus: not verified.

**Adoption is already near saturation.** LangChain's survey (1,340 self-selected respondents, 2025-11-18 to 2025-12-02, skewed to technology companies and small firms) reports 89% have some observability and 52.4% run offline evals [S58]. Menlo reports 84% of AI builders use evals and observability, the second most adopted infrastructure category after databases [S16].

**Does anyone quantify "which steps needed a frontier model"?** Yes. This is the most important negative finding for the "trajectory audit" idea.

- LangChain published a post titled **"How many of your agent's calls actually need a frontier model?"** on 2026-08-11, answering it with NVIDIA Switchyard on its own evaluation suite: Opus handled 7% of model calls and 68.4% of spend [S11].
- Azure's Model Router has a Monitor tab that "compares your cost with single-model baselines" [S5].
- Arize's Cost Agent (Enterprise beta, September 2026) reads traces, ranks spans by spend, correlates cost with quality, and opens a pull request. In its published case study it found "no frontier model misuse"; the waste was in tool payloads, missing prompt caching and re-ingested history [S51]. That is a caution: on real traces, model choice may not be where the money is.
- LangSmith normalises cost across six coding tools and plans gateway routing to open-source models [S52].

**Agent compilation and workflow distillation.** This is active research, not yet a visible product category.

| Work | Date | Finding | Source |
|---|---|---|---|
| Agent Workflow Memory (Wang et al.) | 2024-09-11 | Induces reusable workflows from trajectories; +24.6% and +51.1% relative success on Mind2Web and WebArena | [S80] |
| Agentic Plan Caching (Zhang et al., NeurIPS 2025) | 2025-06-17, rev. 2026-01-26 | Reuses plan templates; cost down 50.31%, latency down 27.28% on average | [S81] |
| TraceCompiler (EPFL, Binome) | 2026-08-03 | Compiles trace clusters into "mostly deterministic" workflows; refuses to compile when an irreversible side effect is under-determined; makes no net-efficiency claim | [S54] |
| ReTrace | 2026-11-10 | Turns an SOP plus a few logged runs into a planner-free workflow; on a production platform 93.8% completion versus 96.8% for the agent at 24% lower cost | [S55] |

An open-source project (`etchplan`) and several essays on "agent compilers" surfaced in search but were not opened [NOT VERIFIED]. No funded startup whose core product is trace-to-workflow compilation was found; absence of evidence from two searches is not evidence of absence.

**Benchmarks.** HAL (Princeton, ICLR 2026) is a third-party, cost-aware leaderboard that plots accuracy against cost and states "agents can be 100x more expensive while only being 1% better"; 9 benchmarks, 26,597 rollouts [S53]. It is the natural host for any cost-versus-control methodology.

---

## 7. Context-engineering infrastructure

Commoditised by providers, and not an area where Turnwise holds anything.

- Anthropic shipped context editing and a memory tool in public beta on 2025-09-29, claiming a 39% improvement on an internal agentic-search evaluation and an 84% token reduction in a 100-turn test (vendor figures) [S56]. Server-side compaction and OpenAI's `/responses/compact` are from search summaries only [S70, NOT OPENED].
- AWS prices AgentCore Memory as a utility: $0.75 per 1,000 long-term records per month, $0.50 per 1,000 retrievals [S25].
- Mem0 raised $24M (2025-10-28), reports 186M API calls in Q3 2025 and an exclusive memory-provider arrangement with an AWS agent SDK (marketing claims) [S60]; 69.3k stars [S38].
- Cognee ($7.5M seed, February 2026), Graphon ($35M Series A, November 2026), Letta, Zep, LangMem: NOT VERIFIED [S82, NOT OPENED].
- Menlo notes that cache reads can be 95% or more of an agent's tokens, which is why blended agent prices are low [S16]. Provider caching, not third-party context compression, is doing the cost work.

---

## 8. What enterprises actually struggle with

| Source | Method and caveats | Finding |
|---|---|---|
| Pan et al., "Measuring Agents in Production" (arXiv 2512.04123, v1 2025-12-02, v4 2026-06-04) [S57] | 20 interview case studies plus 306 survey responses, filtered to 86 deployed systems; sub-samples as small as N=53. Self-selected; data collected April–November 2025, before the late-2025 agent inflection | 68% of deployed agents run at most 10 steps before human intervention (47% fewer than 5); 80% of case studies use predefined workflows; 70% use off-the-shelf models; 74% rely on human evaluation; reliability is the top challenge; "runtime costs remain negligible compared to alternative expert labor costs"; 59% use multiple models, partly for cost |
| LangChain "State of Agent Engineering" [S58] | 1,340 self-selected respondents from LangChain's audience, 2025-11-18 to 2025-12-02; 63% technology sector, 49% under 100 employees. Vendor-run | Quality is the top barrier (about 32%); latency second (20%); security second among 2,000+ employee firms (24.9%); "cost is less frequently cited as a concern than in previous years" |
| Menlo Ventures "2026: The State of Enterprise AI" (2026-11-03) [S16] | Nearly 400 US enterprise decision-makers (Morning Consult, 2026-09-08 to 2026-09-26) plus a bottom-up model; figures are annualised run rates; Menlo is an investor in Anthropic, OpenRouter and others named | Deployment spend $176.8B run rate, up 5.4x; average enterprise spent 4.7x last year against a planned 1.9x (median 2.2x against 1.8x); 74% of builders use agents |
| a16z CIO survey (2026-01-30) [S83] | 100 executives at Global 2000 companies chosen from a vendor database, not random; a16z is an OpenAI investor | Average LLM spend about $7M, expected about $11.6M; 81% use three or more model families; routing across models noted as replacing fine-tuning |
| Gartner (2025-06-25), via Reuters [S84] | Analyst prediction, not measurement | Over 40% of agentic AI projects cancelled by end of 2027, citing escalating costs and unclear business value; about 130 "real" agentic vendors |
| Gartner (August 2026), via VentureBeat [S18] | Analyst forecast | Inference cost per agentic workflow to rise more than fivefold through 2028; agents use 5–30x the tokens of chatbots; recommends "inference tiering" |
| MIT NANDA "GenAI Divide" (July 2025) | **NOT VERIFIED**: neither the report nor the critique was opened [S85] | Headline "95% of pilots show no return"; search summaries say critics found the figure under-explained and the sample small (reported as 52 interviews and 153 survey responses) |
| McKinsey "State of AI" 2025 and 2026 | **NOT VERIFIED**: page returned HTTP 503 [S86] | Search summaries: about 39% then 37% report enterprise EBIT impact; 40% of large organisations scaling agents in 2026 |

**Is inference cost a top-three pain?**

- **Through 2025: no.** Both practitioner studies put reliability and quality first; one says cost is negligible against labour, the other says cost concern declined [S57][S58].
- **In the second half of 2026: it is rising fast, especially for coding agents,** as spend overran plans by about 2.5x on average [S16] and Gartner forecasts per-workflow cost increases [S18]. Anecdotes of exhausted annual AI budgets appear in a LangChain vendor post and were not independently verified [S52].
- **But the market's response is not "use cheaper models".** Buyers traded up to frontier models [S16], and the cost tooling that is winning is free or bundled (caching, effort knobs, free routers, gateway budgets).
- **Ranking on the evidence opened here:** reliability and quality first; security and governance second for large enterprises; integration (custom in-house builds) third; cost fourth and climbing. No 2026 practitioner survey ranking these was opened, so the 2026 ordering is judgement.

---

## 9. Price dynamics

- **Per-unit prices fall steeply at fixed capability.** Epoch AI (2026-09-22) estimates the price for a given level of benchmark performance fell about 47% per quarter since 2023, roughly 13x per year, with a range of 42.9–58.0% per quarter depending on method; no standard errors; benchmark performance is not useful work; the frontier analysis assumes users always switch to the cheapest adequate model, "which real users do not" [S17]. The a16z "LLMflation" estimate of about 10x per year was not opened [S87, NOT OPENED].
- **List prices of what people actually buy went up.** Menlo: a year ago the most popular models were Claude Sonnet 4.5 ($3/$15 per million tokens) and GPT-5 ($1.25/$10); today they are Claude Opus 5.5 ($4/$20) and GPT-6 Astra ($10/$60) [S16].
- **Blended realised price fell modestly.** Closed-source average price per million tokens fell 24% to $0.70; open-source fell 3.3x to $0.13 [S16].
- **Total spend rose much faster than price fell.** Token volume up 13.2x year on year to an estimated 15.2 quadrillion per month; enterprise deployment spend up 5.4x [S16]. OpenRouter went from 5 trillion tokens a week to 25 trillion in six months [S1] and to 160 trillion-plus by late September 2026, with agents about 80% of tokens [S16].
- **Implication for Turnwise.** The claim "per-step routing saves money" is true and already productised. The claim "enterprises will pay a third party to do it" is not supported: the savings lever that dominates agent bills today is prompt caching, and routing must be session-affine so as not to destroy it [S5][S16].

---

## 10. The least-crowded niches, stated plainly

**Plain statement first.** No credible commercial moat exists for something derived from this repository. Its evidence is synthetic, it has no production users, and every product shape is occupied by firms with distribution, traffic data and capital. The rational outcomes are a research contribution or a plugin to an existing framework. The three items below are the least-crowded places such a contribution could land; none is a venture-scale business.

1. **An independent, pre-registered "step-necessity" audit methodology** (research contribution).
   - *What it is.* A protocol and open task set that takes real or replayed agent trajectories and measures, per step, whether a deterministic rule, a light call or a frontier call was sufficient, scored on cost per accepted task, with the mandatory nulls the repo already names (simple host rules plus the same agent, the native agent, a checklist-prompted native agent).
   - *Why it is less crowded than it looks.* The question is being asked only by vendors on their own suites. LangChain's version is a single workload on a saturated benchmark where routing was not distinguishable from the cheap model alone [S11]; Arize's case study found the waste was not in model choice at all [S51]. Nobody has published an independent, cost-controlled, null-baselined answer. HAL exists as a neutral host [S53].
   - *Why it is not a business.* The trace owners (LangSmith, Arize, Azure) can ship the dashboard as a feature the moment the method is public.

2. **A vendor-neutral control-ownership conformance suite** (open-source test kit).
   - *What it is.* Tests that assert architecture properties against a configured agent harness: the model never executes a tool directly; every tool call passes a host check; writes are held; budgets and terminal acceptance are enforced; the controller regains control after each observation. Target harnesses: LangGraph, OpenAI Agents SDK, Claude Agent SDK hooks [S31], AgentCore Policy [S24], Microsoft AGT [S27].
   - *Why it is less crowded.* Existing tools test prompts adversarially (Promptfoo, now going to OpenAI [S29]) or enforce policy at runtime (AWS, Microsoft). A neutral suite that checks whether a deployment's *control flow* matches its stated policy is not something a single vendor is motivated to publish about competitors.
   - *Why it is not a business.* Standards bodies and the framework vendors' own test suites will absorb it; the paying buyer is a CISO who buys from an existing security platform.

3. **Adapters that express the Turnwise policy inside existing runtimes** (plugin).
   - *What it is.* The typed policy as a custom router for NVIDIA Switchyard, which explicitly supports bring-your-own routing [S10]; as a `PreToolUse` hook for the Claude Agent SDK [S31]; as a LangGraph node; as a policy adapter for Microsoft AGT [S27].
   - *Why it is the honest distribution path.* It lets the hypothesis be tested on other people's workloads without building a runtime, which the repo forbids itself from doing.
   - *The one technical angle worth measuring.* A non-LLM policy removes the per-turn LLM judge, which was 21.2% of routed spend and about 700 ms per turn in LangChain's test [S11]. Whether a typed policy matches an LLM judge's escalation accuracy is an open empirical question, not a product.

---

## 11. Claims I could not verify

1. **Stripe's price for OpenRouter** ("more than $7B", "$8B", "about $10B"): not in Stripe's announcement; press and Sacra figures conflict. Whether the deal has closed is also unverified.
2. **OpenRouter revenue** (Sacra estimates of $50M to $160M annualised): third-party estimates, not opened.
3. **Prices for Portkey, Protect AI, Lakera, Prompt Security, Invariant Labs, Promptfoo**: none stated in the primary pages opened. Whether the Lakera, CalypsoAI, Prompt Security and Promptfoo deals closed was not checked.
4. **SentinelOne and Prompt Security**: the primary page returned HTTP 429 twice; only a search summary of the press release was seen.
5. **Salesforce's $3.6B price for Fin**: from a search summary of the 2026-06-15 press release, not opened. Completion on 2026-09-10 was verified.
6. **Gartner's securing-AI market forecast** ($2.8B in 2026, $4.8B in 2027) and **Gartner's original 40% cancellation release**: Gartner pages returned HTTP 403; figures come from search summaries and a Reuters reprint.
7. **MIT NANDA "GenAI Divide"** and its critiques: not opened.
8. **McKinsey State of AI 2025 and 2026**: page returned HTTP 503.
9. **The PitchBook article "Everyone is building AI routers. Are they a dead end?"**, the Dark Reading count of 40 AI-security deals, The New Stack on Stripe, GeekWire on Temporal and Oso, HPCwire on Menlo: all returned HTTP 403.
10. **Azure Model Router routing fee**: pricing page rendered `$-`.
11. **Funding for Not Diamond, Martian, Unify, Requesty, LiteLLM, CrewAI, LlamaIndex, Pydantic, Noma, Braintrust, Arize, Galileo, Patronus, Cognee, Graphon, Letta, Zep, Rasa, Kore.ai, PolyAI, Coval**: aggregator or search-summary figures only.
12. **Temporal's "$250M annualised revenue"**: from press coverage; Temporal's own post says only that run-rate revenue grew more than 200%.
13. **Microsoft Entra Agent ID GA, Foundry guardrails and control plane, Google Model Armor and Agent Engine governance, Vertex AI Model Optimizer status, Kong and Cloudflare AI gateway routing features, the MCP gateway vendor count (42), Permit.io and Cerbos MCP offerings**: search summaries only.
14. **Cursor, Windsurf "auto" modes**: only Cursor forum posts surfaced; nothing verified. Windsurf not found.
15. **Whether OpenAI's API (as opposed to ChatGPT) exposes the GPT-5 router**: not verified.
16. **Helicone to Mintlify, W&B to CoreWeave, NICE and Cognigy**: search summaries of primary pages; pages not opened.
17. **Inspect (UK AISI) adoption**: nothing found.
18. **Anecdotes in the LangChain cost post** (a company exhausting its 2026 AI budget in four months; a $300M model bill): vendor blog citing unnamed reports.
19. **GitHub star counts**: read on 2026-11-20 via an automated summariser from rendered pages; rounded; not cross-checked against the API (the API was not available in this session).
20. **"Dogwood" policy language**: taken from AWS's AgentCore Policy developer guide as fetched; not independently corroborated.
21. **Decagon AOPs "compiled into code"**, Intercom Procedures "managed availability", Decagon and Fin ARR figures: secondary sources.
22. **Existence of a funded startup whose core product is trace-to-workflow compilation**: none found in two searches; not a proof of absence.

---

## Source table

Type key: PR = company press release or announcement; DOC = official documentation or pricing page; BLOG = company engineering or product blog; NEWS = journalism; PAPER = academic paper; REPORT = analyst or VC report; REPO = GitHub repository page.

| # | Title | Organisation / author | Date | URL | Type | Specific fact used | Status |
|---|---|---|---|---|---|---|---|
| S1 | OpenRouter more than doubles valuation to $1.3B in a year | TechCrunch | 2026-05-26 | https://techcrunch.com/2026/05/26/openrouter-more-than-doubles-valuation-to-1-3b-in-a-year | NEWS | $113M Series B led by CapitalG; ~$1.3B per NYT; 25T tokens/week, up 5x in six months; 8M users | OPENED |
| S2 | Stripe agrees to acquire OpenRouter to help businesses optimize token routing and usage | Stripe | 2026-08-19 | https://stripe.com/newsroom/news/stripe-agrees-to-acquire-openrouter | PR | Agreement signed; no price; 400+ models, 80+ providers; NVIDIA, Zoom, Lovable named | OPENED |
| S3 | Palo Alto Networks Completes Acquisition of Portkey to Secure AI Agents | Palo Alto Networks | 2026-05-29 | https://www.paloaltonetworks.com/company/press/2026/palo-alto-networks-completes-acquisition-of-portkey-to-secure-ai-agents | PR | Closed; Portkey becomes AI gateway for Prisma AIRS; no price | OPENED |
| S4 | Amazon Bedrock Intelligent Prompt Routing is now generally available | AWS | 2025-04-22 | https://aws.amazon.com/about-aws/whats-new/2025/04/amazon-bedrock-intelligent-prompt-routing-generally-available | PR | GA; routes within Claude, Llama, Nova families | OPENED |
| S5 | What is model router in Microsoft Foundry? | Microsoft Learn | ms.date 2026-11-18 | https://learn.microsoft.com/en-us/azure/ai-services/openai/concepts/model-router | DOC | 45 models; modes; per-agent-step routing; routing fee plus model usage; Auto and session affinity in preview; Monitor tab baselines | OPENED |
| S6 | Model router pricing | Microsoft Azure | accessed 2026-11-20 | https://azure.microsoft.com/en-us/pricing/details/ai-foundry-models/model-router/ | DOC | Price rendered as `$-`; fee not verifiable | OPENED |
| S7 | Configure cost and quality in Copilot auto model selection | GitHub Changelog | 2026-09-14 | https://github.blog/changelog/2026-09-15-configure-cost-and-quality-in-copilot-auto-model-selection | PR | Three tiers; per-prompt selection; billed by selected model; 10% discount | OPENED |
| S8 | Introducing GPT-5 | OpenAI | 2025-08-07 | https://openai.com/index/introducing-gpt-5/ | PR | "Real-time router" and its training signals | OPENED |
| S9 | Router launch | Ramp | 2026-08-19 | https://ramp.com/blog/router-launch | BLOG | Router.com; free routing through 2026; 40% saving claim; Switchyard strategy | OPENED |
| S10 | Route AI agent workloads across models with NVIDIA NeMo Switchyard | NVIDIA | 2026-08-11 | https://developer.nvidia.com/blog/route-ai-agent-workloads-across-models-with-nvidia-nemo-switchyard | BLOG | Open source; stage and escalation routers; custom routers; partners | OPENED |
| S11 | How many of your agent's calls actually need a frontier model? | LangChain (Tangedipalli, Singh) | 2026-08-11 | https://langchain.com/blog/switchyard-agent-routing-benchmark | BLOG | 145 tasks; 86.0% / 80.0% / 77.7%; 74% cheaper; judge 21.2% of spend; within-noise caveat | OPENED |
| S12 | Auto Router | OpenRouter docs | accessed 2026-11-20 | https://openrouter.ai/docs/guides/routing/routers/auto-router | DOC | Picks model and reasoning effort; no router fee; Auto Code | OPENED |
| S13 | Blog index | Not Diamond | accessed 2026-11-20 | https://www.notdiamond.ai/blog | BLOG | 2026 post list; prompt optimisation GA 2026-01-20; Not Diamond Code waitlist; no funding news | OPENED |
| S14 | A unified API for AI model routing | Google Developers Blog | 2026-08-04 | https://developers.googleblog.com/a-unified-api-for-ai-model-routing/ | BLOG | API Gateway model routing in public preview; rule-based | OPENED |
| S15 | Effort | Anthropic (Claude Platform docs) | accessed 2026-11-20 | https://platform.claude.com/docs/en/build-with-claude/effort | DOC | Stable; levels low to max; per-message change preserves cache | OPENED |
| S16 | 2026: The State of Enterprise AI | Menlo Ventures (Tully, Redfern, Das, Xiao) | 2026-11-03 | https://menlovc.com/wp-content/uploads/2026/11/menlo_ventures_enterprise_ai_report-2026-110326.pdf | REPORT | $176.8B run rate; frontier share 35%→63%; small-model token share 29%→13%; prices; 4.7x vs 1.9x plan; 84% evals adoption; market map; methodology and conflicts | OPENED (PDF read, 21 pages) |
| S17 | The plunging price of thought | Epoch AI (Emberson, Roodman) | 2026-09-22 | https://epoch.ai/publications/the-plunging-price-of-thought | REPORT | ~47% per quarter, ~13x per year; caveats | OPENED |
| S18 | Gartner says agent costs will rise fivefold by 2028 even as tokens get cheaper | VentureBeat | 2026-10-16 | https://venturebeat.com/ai/gartner-says-agent-costs-will-rise-fivefold-by-2028-even-as-tokens-get-cheaper-here-is-how-to-keep-them-in-check | NEWS | Gartner forecast; 5–30x tokens; inference tiering | OPENED |
| S19 | Snyk Acquires Invariant Labs to Accelerate Agentic AI Security Innovation | Snyk | 2025-06-24 | https://snyk.io/news/snyk-acquires-invariant-labs-to-accelerate-agentic-ai-security-innovation | PR | Acquired; Guardrails; MCP scanning; no price | OPENED |
| S20 | Check Point Acquires Lakera to Deliver End-to-End AI Security for Enterprises | Check Point | 2025-09-16 | https://www.checkpoint.com/press-releases/check-point-acquires-lakera-to-deliver-end-to-end-ai-security-for-enterprises/ | PR | Agreement; close expected Q4 2025; no price | OPENED |
| S21 | Palo Alto Networks Completes Acquisition of Protect AI | Palo Alto Networks | 2025-07-22 | https://www.paloaltonetworks.com/company/press/2025/palo-alto-networks-completes-acquisition-of-protect-ai | PR | Completed; no price | OPENED |
| S22 | F5 to acquire CalypsoAI to bring advanced AI guardrails to large enterprises | F5 | 2025-09-11 | https://f5.com/company/news/press-releases/f5-to-acquire-calypsoai-to-bring-advanced-ai-guardrails-to-large-enterprises | PR | $180M; intent to acquire | OPENED |
| S23 | Policy in Amazon Bedrock AgentCore is now generally available | AWS | 2026-03-03 | https://aws.amazon.com/about-aws/whats-new/2026/03/policy-amazon-bedrock-agentcore-generally-available | PR | GA; 13 regions; outside agent code; natural language to Cedar | OPENED |
| S24 | Policy in Amazon Bedrock AgentCore: Control Agent Interactions | AWS developer guide | accessed 2026-11-20 | https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy.html | DOC | Deterministic enforcement at Gateway; Cedar; Dogwood temporal conditions (approval, counts, budgets); automated reasoning on policies | OPENED |
| S25 | Amazon Bedrock AgentCore pricing | AWS | accessed 2026-11-20 | https://aws.amazon.com/bedrock/agentcore/pricing/ | DOC | Policy $0.000025 per authorization request; Memory and Evaluations unit prices | OPENED |
| S26 | Microsoft 365 E7 and Agent 365 are now generally available | Microsoft Tech Community | 2026-05-01 | https://techcommunity.microsoft.com/blog/microsoft_365blog/microsoft-365-e7-and-agent-365-are-now-generally-available/4516295 | PR | GA; Agent 365 $15/user/month; E7 $99 | OPENED |
| S27 | Introducing the Agent Governance Toolkit | Microsoft Open Source blog | 2026-04-02 | https://opensource.microsoft.com/blog/2026/04/02/introducing-the-agent-governance-toolkit/ | BLOG | MIT; intercepts every action; <0.1 ms p99 claim; YAML, Rego, Cedar; adapters | OPENED |
| S28 | microsoft/agent-governance-toolkit | GitHub | 2026-11-20 | https://github.com/microsoft/agent-governance-toolkit | REPO | 6.6k stars; MIT | OPENED |
| S29 | OpenAI to acquire Promptfoo | OpenAI | 2026-03-09 | https://openai.com/index/openai-to-acquire-promptfoo/ | PR | Subject to closing; Frontier integration; 25% of Fortune 500 claim; OSS continues | OPENED |
| S30 | Introducing AgentKit (with wind-down notice) | OpenAI | 2025-10-06; notice 2026-06-03 | https://openai.com/index/introducing-agentkit/ | PR | Agent Builder and Evals unavailable from 2026-11-30 | OPENED |
| S31 | Configure permissions (Agent SDK) | Anthropic (Claude Code docs) | accessed 2026-11-20 | https://code.claude.com/docs/en/agent-sdk/permissions | DOC | Six-step evaluation order; hook denial applies in bypass mode | OPENED |
| S32 | SoftBank, Hitachi, LG back Zenity's $125 million round to police AI agents | Fortune | 2026-08-03 | https://fortune.com/2026/08/03/softbank-hitachi-lg-back-zenitys-125-million-round-to-police-ai-agents/ | NEWS | $125M Series C, Norwest; 230 employees; valuation undisclosed | OPENED |
| S33 | Tiny buys Oso Cloud's assets for $1.9 million | BetaKit | 2026-10-08 | https://betakit.com/tiny-buys-oso-clouds-assets-for-1-9-million/ | NEWS | C$1.9M; ~$5.3M ARR; team incl. CEO to Temporal | OPENED |
| S34 | Announcing Agent Payments Protocol (AP2) | Google Cloud | 2025-09-16 | https://cloud.google.com/blog/products/ai-machine-learning/announcing-agents-to-payments-ap2-protocol | BLOG | Open protocol; mandates; 60+ organisations | OPENED |
| S35 | Temporal raises $550M at a $12.55B valuation | Temporal | 2026-09-14 | https://temporal.io/blog/temporal-raises-usd550m-series-e-at-usd12-55b-valuation-ai | PR | Round; 4,300+ paying customers; OpenAI, Snap, NVIDIA | OPENED |
| S36 | Series C announcement | LangChain | 2026-11-13 | https://www.langchain.com/blog/series-c | PR | $300M at $3B; CapitalG; 7,000+ organisations; runtime, improvement, governance; gateways | OPENED |
| S37 | We raised a $22M Series A | Mastra | 2026-04-09 | https://mastra.ai/blog/series-a | PR | $22M, Spark Capital; $35M total | OPENED |
| S38 | Repository pages: langchain-ai/langgraph (45.2k), crewAIInc/crewAI (61.1k), openai/openai-agents-python (30.8k), google/adk-python (22.3k), pydantic/pydantic-ai (21.3k), mastra-ai/mastra (29.7k), BerriAI/litellm (63.6k), NVIDIA/NeMo-Guardrails (7.5k), langfuse/langfuse (37.7k), mem0ai/mem0 (69.3k), temporalio/temporal (24.5k) | GitHub | 2026-11-20 | https://github.com/ (each repository) | REPO | Star counts as displayed, rounded | OPENED (via page summariser) |
| S39 | Hybrid reasoning with Agentforce Builder and Agent Script | Salesforce Architects | undated; states "GA since February 2026" | https://architect.salesforce.com/docs/architect/fundamentals/guide/hybrid-reasoning-agentforce-builder-agent-script | DOC | "If you can express a decision as code..."; "state machine executor" | OPENED |
| S40 | Salesforce executives signal declining trust in large language models | The Decoder (citing The Information) | 2025-12-25 | https://the-decoder.com/salesforce-executives-signal-declining-trust-in-large-language-models/ | NEWS | Parulekar quote; move toward rule-based automation | OPENED (partly paywalled) |
| S41 | Thinking CALMly | Rasa docs | accessed 2026-11-20 | https://rasa.com/docs/rasa-pro/building-assistants/thinking-calmly | DOC | "LLMs ... don't guess your business logic" | OPENED |
| S42 | Series D announcement | Decagon | 2026-01-27 | https://decagon.ai/resources/series-d-announcement | PR | $250M at $4.5B; Coatue, Index; AOPs | OPENED |
| S43 | Sierra raises $950M as the race to own enterprise AI gets serious | TechCrunch | 2026-05-04 | https://techcrunch.com/2026/05/04/sierra-raises-950m-as-the-race-to-own-enterprise-ai-gets-serious | NEWS | $950M above $15B; ARR milestones; 40% of Fortune 50 | OPENED |
| S44 | Our customers' ambition is accelerating our growth | Sierra | 2026-10-30 | https://sierra.ai/blog/our-customers-ambition-is-accelerating-our-growth | BLOG | $400M+ ARR (self-reported) | OPENED |
| S45 | The Agent Development Life Cycle | Sierra | 2024-06-03 | https://sierra.ai/blog/agent-development-life-cycle | BLOG | Declarative goals; deterministic guardrails; 10% claim | OPENED |
| S46 | Announcing major updates to Procedures and Simulations | Intercom (Chris Dalley) | 2026-02-25 | https://intercom.com/blog/procedures-simulations-updates | BLOG | "Natural language is flexible, but some steps need to be exact" | OPENED |
| S47 | Salesforce Completes Acquisition of Fin | Salesforce | 2026-09-10 | https://www.salesforce.com/news/press-releases/2026/09/10/salesforce-completes-acquisition-of-fin/ | PR | Completed; 30,000+ customers; 76% resolution rate claim | OPENED |
| S48 | emcie-co/parlant | GitHub | 2026-11-20 | https://github.com/emcie-co/parlant | REPO | 18.3k stars; per-turn policy selection | OPENED |
| S49 | Langfuse joins ClickHouse | Langfuse | 2026-01-16 | https://langfuse.com/blog/joining-clickhouse | PR | Acquired; stays open source | OPENED |
| S50 | Anthropic nabs Humanloop team | TechCrunch | 2025-08-13 | https://techcrunch.com/2025/08/13/anthropic-nabs-humanloop-team-as-competition-for-enterprise-ai-talent-heats-up | NEWS | Acqui-hire; no IP acquired | OPENED |
| S51 | Agent cost management is about more than the model | Arize (Laurie Voss) | September 2026 | https://arize.com/blog/using-managed-agents-to-optimize-llm-costs/ | BLOG | Cost Agent in Enterprise beta; "no frontier model misuse" case | OPENED |
| S52 | Fix your coding agent bill | LangChain (Amy Ru) | 2026-07-02 | https://www.langchain.com/blog/fix-your-coding-agent-bill | BLOG | Cross-tool cost tracing; gateway caps; planned OSS routing; anecdotes | OPENED |
| S53 | Holistic Agent Leaderboard | Princeton SAgE | accessed 2026-11-20 | https://hal.cs.princeton.edu/ | DOC | Cost-aware; "100x more expensive while only being 1% better"; 9 benchmarks | OPENED |
| S54 | TraceCompiler | El Yadouni (EPFL), Li (Binome) | 2026-08-03 | https://arxiv.org/abs/2608.02680 | PAPER | Trace clusters to mostly deterministic workflows; no net-efficiency claim | OPENED (abstract page) |
| S55 | ReTrace: Distilling Tool-Using Agents into Planner-Free Workflows | Hou et al. | 2026-11-10 | https://arxiv.org/abs/2611.14492 | PAPER | 93.8% vs 96.8% completion at 24% lower cost | OPENED (abstract page) |
| S56 | Managing context on the Claude Developer Platform | Anthropic | 2025-09-29 | https://claude.com/blog/context-management | BLOG | Context editing and memory tool in public beta; 39% / 29% / 84% | OPENED |
| S57 | Measuring Agents in Production | Pan et al. (25 authors) | v1 2025-12-02; v4 2026-06-04 | https://arxiv.org/abs/2512.04123 and https://arxiv.org/html/2512.04123v3 | PAPER | 68% ≤10 steps; 80% predefined workflows; 85% custom builds; reliability top; cost negligible vs labour | OPENED (abstract and first half of HTML) |
| S58 | State of Agent Engineering | LangChain | survey 2025-11-18 to 2025-12-02 | https://langchain.com/state-of-agent-engineering | REPORT | 1,340 responses; quality 32%; latency 20%; cost cited less; 89% observability | OPENED |
| S59 | Guardian agents are here and ready to disrupt the market | IT Brew | 2026-03-06 | https://www.itbrew.com/stories/2026/03/06/guardian-agents-are-here-and-ready-to-disrupt-the-market | NEWS | Gartner: under 1% of agentic budget today; 5–7% by 2028 | OPENED |
| S60 | Mem0 raises $24M | TechCrunch | 2025-10-28 | https://techcrunch.com/2025/10/28/mem0-raises-24m-from-yc-peak-xv-and-basis-set-to-build-the-memory-layer-for-ai-apps | NEWS | $24M; 186M API calls Q3 2025; AWS arrangement | OPENED |
| S61 | Braintrust Series B | Axios Pro, SiliconANGLE, Braintrust blog | 2026-02-17 | https://www.braintrust.dev/blog/announcing-series-b | PR/NEWS | $80M at $800M | NOT OPENED |
| S62 | Braintrust Loop; LangSmith Insights | vendor pages | 2026 | https://www.braintrust.dev/ | DOC | Product descriptions | NOT OPENED |
| S63 | CoreWeave completes acquisition of Weights & Biases; Helicone joins Mintlify | CoreWeave; Helicone | 2025-05-05; 2026-03-03 | https://coreweave.com/blog/coreweave-completes-acquisition-of-weights-biases ; https://helicone.ai/blog/joining-mintlify | PR | Acquisitions | NOT OPENED |
| S64 | Portkey Series A | Portkey blog and press | 2026-02-19 | https://portkey.ai/blog/series-a-funding/ | PR | $15M led by Elevation | NOT OPENED |
| S65 | Not Diamond funding | aggregators (CB Insights, Caplight) | 2024-07 | https://www.cbinsights.com/company/not-diamond | NEWS | $2.3M pre-seed | NOT OPENED |
| S66 | Martian seed and positioning | TechCrunch; third-party profiles | 2023-11-15; 2026 | https://techcrunch.com/2023/11/15/martians-tool-automatically-switches-between-llms-to-reduce-costs/ | NEWS | $9M seed; research positioning | NOT OPENED |
| S67 | Unify, Requesty, LiteLLM funding | aggregators | various | https://www.requesty.ai/blog/requesty-raises-3m | NEWS | Reported rounds | NOT OPENED |
| S68 | Entra Agent ID GA | secondary coverage | 2026-05 | https://redmondmag.com/articles/2026/05/01/microsoft-agent-365-goes-live-as-company-unveils-e7-suite.aspx | NEWS | GA claim | NOT OPENED |
| S69 | SentinelOne to Acquire Prompt Security | SentinelOne | 2025-08-05 | https://www.sentinelone.com/press/sentinelone-to-acquire-prompt-security/ | PR | Definitive agreement | NOT OPENED (HTTP 429) |
| S70 | Compaction guides | OpenAI; Anthropic | 2026 | https://developers.openai.com/api/docs/guides/compaction ; https://platform.claude.com/docs/en/build-with-claude/compaction | DOC | Server-side compaction | NOT OPENED |
| S71 | Automated Reasoning checks is now available in Amazon Bedrock Guardrails | AWS | 2025-08-06 | https://aws.amazon.com/about-aws/whats-new/2025/08/automated-reasoning-checks-amazon-bedrock-guardrails | PR | GA | NOT OPENED |
| S72 | Inspect AI | UK AI Security Institute | n/a | https://inspect.aisi.org.uk/ | DOC | Existence only | NOT OPENED |
| S73 | AI Scramble Drives Cybersecurity M&A Boom; M&A roundups | Dark Reading; Infosecurity Magazine; SecurityWeek | 2026 | https://www.darkreading.com/cybersecurity-analytics/ai-scramble-cybersecurity-ma-boom | NEWS | Deal counts; Acuvity, Oasis, Aim, Pangea | NOT OPENED (HTTP 403) |
| S74 | Noma Security raises $100M | SecurityWeek, SiliconANGLE | 2025-07-31 | https://www.securityweek.com/noma-security-raises-100-million-for-ai-security-platform/ | NEWS | Series B | NOT OPENED |
| S75 | Gartner Forecasts the Market for Securing AI Will Reach $4.8 Billion in 2027 | Gartner | 2026-08-26 | https://www.gartner.com/en/newsroom/press-releases/2026-08-26-gartner-forecasts-the-market-for-securing-ai-will-reach-almost-5-billion-in-2027 | PR | Market forecast | NOT OPENED (HTTP 403) |
| S76 | Permit.io MCP Gateway; Cerbos MCP authorization | vendor pages | 2026 | https://cerbos.dev/blog/mcp-authorization | BLOG | Product claims | NOT OPENED |
| S77 | CrewAI, Pydantic, LlamaIndex funding | TechCrunch, aggregators | 2024–2025 | https://techcrunch.com/2024/10/22/crewai-uses-third-party-models-to-automate-business-tasks | NEWS | Reported rounds | NOT OPENED |
| S78 | Salesforce Signs Definitive Agreement to Acquire Fin | Salesforce | 2026-06-15 | https://www.salesforce.com/news/press-releases/2026/06/15/salesforce-signs-definitive-agreement-to-acquire-fin | PR | ~$3.6B | NOT OPENED |
| S79 | NiCE Closes Acquisition of Cognigy | NICE | 2025-09-08 | https://www.nice.com/press-releases/press-releases-nice-closes-acquisition-of-cognigy-transforming-customer-experience-with-best-in-class-data-driven-cx-ai-platform | PR | Closed | NOT OPENED |
| S80 | Agent Workflow Memory | Wang, Mao, Fried, Neubig | 2024-09-11 | https://arxiv.org/abs/2409.07429 | PAPER | Workflow induction; +24.6% / +51.1% relative | OPENED (abstract page) |
| S81 | Agentic Plan Caching: Test-Time Memory for Fast and Cost-Efficient LLM Agents | Zhang, Wornow, Wan, Olukotun | 2025-06-17; rev. 2026-01-26 | https://arxiv.org/abs/2506.14852 | PAPER | Cost −50.31%, latency −27.28% | OPENED (abstract page) |
| S82 | Cognee, Graphon, Letta, Zep funding | Dealroom, press | 2026 | https://www.cognee.ai/blog/cognee-news/cognee-raises-seven-million-five-hundred-thousand-dollars-seed | NEWS | Reported rounds | NOT OPENED |
| S83 | Leaders, gainers and unexpected winners in the Enterprise AI arms race | a16z (Wang, Kahl, Xu) | 2026-01-30 | https://a16z.com/leaders-gainers-and-unexpected-winners-in-the-enterprise-ai-arms-race/ | REPORT | 100 executives; LLM spend ~$7M → ~$11.6M; 81% use 3+ model families | OPENED |
| S84 | Over 40% of agentic AI projects will be scrapped by 2027, Gartner says | Reuters via The Star | 2025-06-25 | https://www.thestar.com.my/tech/tech-news/2025/06/25/over-40-of-agentic-ai-projects-will-be-scrapped-by-2027-gartner-says | NEWS | Gartner prediction; ~130 real vendors | OPENED (reprint; Gartner original returned HTTP 403) |
| S85 | The GenAI Divide: State of AI in Business 2025; critique coverage | MIT NANDA; HPCwire/BigDATAwire | 2025-07; 2025-09-04 | https://www.hpcwire.com/bigdatawire/2025/09/04/mit-report-flags-95-genai-failure-rate-but-critics-say-it-oversimplifies/ | REPORT/NEWS | 95% claim and criticism | NOT OPENED (HTTP 403) |
| S86 | The state of AI | McKinsey | 2025; 2026 | https://www.mckinsey.com/capabilities/quantumblack/our-insights/the-state-of-ai | REPORT | EBIT and scaling figures | NOT OPENED (HTTP 503) |
| S87 | Welcome to LLMflation | a16z (Appenzeller) | 2024-11 | https://a16z.com/llmflation-llm-inference-cost/ | REPORT | ~10x per year | NOT OPENED |
