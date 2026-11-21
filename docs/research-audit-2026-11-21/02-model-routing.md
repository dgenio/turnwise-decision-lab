# Model routing, cascades and adaptive inference: what is known, and what it means for per-step routing in agents

> **Status: dated external research note, archived 2026-11-21. Historical (accurate for its date).** Written by an AI research pass for the red-team review in [#94](https://github.com/dgenio/turnwise-decision-lab/issues/94). Research only: no model was called and no experiment was run by this repository. Verification flags are the author's own; the [audit index](README.md) says what was independently re-checked and lists known corrections. Do not rewrite this file; add a dated note instead.

Skeptical literature review for the adversarial review of Turnwise Decision Lab.
Compiled 2026-11-20. Every pricing or product page cited below was read on 2026-11-20.

## How to read this report

Verification flags used throughout:

- **[F]** opened the paper's full text / HTML, or the official page itself (long pages are truncated by the fetch tool at about 100k characters, so late appendices may be unread).
- **[A]** opened the arXiv abstract page only. Numbers are the abstract's numbers; methodology not checked.
- **[S]** opened a secondary source (news article) reporting on a primary source.
- **[NV]** NOT VERIFIED: seen only in a search-result summary, or the page could not be opened.

Other conventions: "vendor claim" marks numbers published by the party selling the thing. "Reviewer arithmetic" marks numbers I derived from list prices; they are not measurements. Many 2026 items are unreviewed preprints, some single-author or workshop papers; this is flagged where it matters.

One caution about the evidence base as a whole: most of the directly relevant agent-level studies appeared between May and November 2026, are preprints, and mostly use SWE-bench Verified. The picture is consistent but young.

---

## 0. Bottom line

1. **Per-query routing is a mature, saturating field with modest realizable gains.** Simple methods (kNN, a task-type lookup table) match sophisticated learned routers; all sit 10 to 30 points below the oracle; commercial routers do not reliably beat the best single model; routers trained on one distribution perform at chance on another.
2. **Per-step routing inside agents has now been tested end to end with real models and cache-aware billing, and the results are mostly unfavourable to naive step-level switching.** Mid-trajectory escalation recovers less than half of the quality gap and can cost more than running the frontier model alone; rule-based step routers failed 38 to 39 of 40 SWE-bench trajectories in one benchmark; delegation to cheaper models raised cost in half the settings in another.
3. **The savings Turnwise targets are being competed away from three directions:** prompt caching (frontier cached-read prices are now 2.5% to 5% of list input), single-model effort knobs that can change per message without breaking the cache, and price decline of roughly 13x per year at constant capability.
4. **Providers already ship per-step routing for agents, with cache-aware stickiness** (Microsoft Foundry model router, Cursor Router, GitHub Copilot auto, OpenRouter Auto), and escalation patterns (Anthropic advisor tool, Claude Code `opusplan`, Aider architect mode).
5. **What remains open is narrower than the Turnwise claim:** whether a non-LLM typed policy can hold loop control without losing end-to-end success, and whether deterministic operations can remove model turns (turn count, not model tier, is the dominant cost driver in the one study that measured it).

---

## 1. Core routing and cascade literature

### 1.1 Foundational results (the optimistic canon)

| Work | Headline claim (as stated) | Data / setting | Limitation that matters here |
|---|---|---|---|
| **FrugalGPT** (Chen, Zaharia, Zou; arXiv 2305.05176, 9 May 2023) [F via PDF text] | "up to 98% cost reduction" matching the best individual LLM, or +4% accuracy over GPT-4 at the same cost. Table 3: cost savings 98.3% (HEADLINES), 73.3% (OVERRULING), 59.2% (COQA). | Three classification/QA datasets (HEADLINES n=10,000; OVERRULING n=2,400; COQA n=7,982). Cascade with a DistilBERT scoring function. | Authors' own words: "we need some labeled examples ... the training examples should be from the same or similar distribution as the test examples." Single-turn tasks; 2023 models; the 98% figure is one narrow financial-headline classification task. |
| **Hybrid LLM** (Ding et al.; arXiv 2404.14618; ICLR 2024) [F] | "up to 40% fewer calls to the large model, with no drop in response quality". | MixInstruct; DeBERTa-v3-large router; quality = BART score. | The "no drop" result holds only for the small-gap pair (Llama-2 7b to 13b: 0.0 to 0.2% drop at 40%). For the medium gap (Llama-2 13b to GPT-3.5) the drop at 40% is 2.9 to 3.5%; for the large gap (FLAN-T5 800m to Llama-2 13b) it is 10.3 to 13.8%, and the basic routers "perform marginally better than the random routing baseline". Generalisation degrades when quality-gap correlation is low (r = 0.06). |
| **RouteLLM** (Ong et al.; arXiv 2406.18665, v4 Feb 2025) [F] | Cost reduced "by over 2 times in certain cases" without compromising quality. MT Bench: 3.66x at CPT(50%), 2.49x at CPT(80%); matrix-factorisation APGR 0.802 vs 0.500 random. | Trained on about 65k Chatbot Arena comparisons, plus about 120K GPT-4-judged samples (about $700) and about 1,500 MMLU gold labels. Two-model routing only. | Without in-domain augmentation the routers are at chance out of distribution: on MMLU "all routers perform poorly at the level of the random router" (APGR 0.473 to 0.524); on GSM8K all routers fall below random (APGR 0.438 to 0.475). MMLU savings are 1.41x at 92% of GPT-4 quality; GSM8K 1.49x at 87%. Authors advise collecting "a small amount of in-domain data". |
| **AutoMix** (Aggarwal, Madaan et al.; arXiv 2310.12963; NeurIPS 2024) [F] | "over 50%" computational cost reduction for comparable performance. | Five context-grounded datasets (qasper, quality, coqa, mutual, diplomat); few-shot self-verification plus a POMDP router trainable on as few as 50 examples. | Designed for context-grounded reasoning only; authors exclude factual QA and commonsense reasoning. Self-verification described as "often noisy and ill-calibrated"; verifier poorly calibrated on two of five datasets. |
| **RouterBench** (Hu et al.; arXiv 2403.12031) [F] | 405,467 inference outcomes, 11 models, 8 datasets. Oracle on MMLU: 0.957 at cost 0.297 vs GPT-4 0.828 at cost 4.086; "GPT-4 is seldom chosen" by the oracle. | Predictive routers (kNN, MLP) and simulated cascades. | "none of the routing algorithms significantly outperform the baseline Zero router" (linear interpolation between models). Cascades only win "when the router's judge has an error rate of up to 0.1"; above 0.2 performance "may deteriorate rapidly". |
| **A Unified Approach to Routing and Cascading** (Dekoninck, Baader, Vechev; arXiv 2410.10347, v5 Oct 2026) [F] | Proves optimal strategies; "cascade routing" improves AUC by up to 8% over cascading and up to 12% over routing in noise sweeps; SWE-Bench 54.12 vs 40.47 (routing) vs 40.51 (linear interpolation). | RouterBench with simulated estimator noise; SWE-Bench with cost = latency. | The paper's own conclusion: "good quality estimators" are "the critical factor". On SWE-Bench plain routing equals linear interpolation (40.47 vs 40.51) because ex-ante estimates are poor; the SWE-Bench gain relies on post-hoc quality from ground-truth tests, which a deployed agent does not have. |
| **MixLLM** (Wang et al.; arXiv 2502.18482; NAACL 2025) [A] | "97.25% of GPT-4's quality at 24.18% of the cost under the time constraint". | Contextual-bandit router with per-model quality/cost predictors. | Abstract only; single-turn. |
| **GraphRouter** (Feng, Shen, You; arXiv 2410.03834) [A] | "minimum performance improvement of 12.3%" over prior routers. | Heterogeneous graph over tasks, queries, LLMs. | In independent evaluation (RouterArena) it scores 57.0% accuracy, below a kNN router's 58.7%. |
| **Cost-of-Pass** (Erol et al.; arXiv 2504.13359, v2 Feb 2026) [A] | Lightweight models are most cost-effective for basic quantitative tasks, large models for knowledge-intensive tasks, reasoning models for complex quantitative tasks; frontier cost-of-pass for complex quantitative tasks "roughly halved every few months". | Economic framework; expected cost per correct solution. | Finds that inference-time techniques (majority vote, self-refinement) with "marginal performance gains rarely justify the costs". Per-task, not per-step. |

### 1.2 Sobering and negative results

These are the results an adversarial reviewer should lead with.

- **Routers converge on a plateau far below the oracle.** *The Routing Plateau* (Lu et al., arXiv 2606.07587, v2 Sep 2026) [F via PDF text]: 21 routing methods, 5 benchmarks. "on RouterBench, the top 15 routers differ by only 0.23 percentage points"; kNN "ranks among the top-2 methods on all five benchmarks"; "the best router trails the Oracle by 10–30 pp". Scaling training data tenfold (to 302,371 labelled queries), larger encoders and end-to-end fine-tuning together add 1.24 pp on average (max 2.13 pp). Their explanation is a "correctness-prediction bottleneck": routers learn global model capability, not per-query correctness. They suggest progress "may require ... partial output trajectories".
- **Simple kNN is competitive.** *Rethinking Predictive Modeling for LLM Routing: When Simple kNN Beats Complex Learned Routers* (Yang Li, arXiv 2505.12601) [F]. Text-average utility AUC: kNN 52.68, Linear 53.14, MLP 51.71, Graph 51.82; oracle 64.91, random 40.35. Caveat: the title overstates; in selection-based tables some learned routers beat kNN. Single-author preprint.
- **Routers often fail to beat the best single model, including a commercial router.** *LLMRouterBench* (Li et al., arXiv 2601.07206) [F]: 21 datasets, 33 models, about 392k instances. Top methods reach "up to a 4% average accuracy gain" over Best Single and up to 31.7% cost reduction at matched performance, but "several routers fail to outperform the Best Single"; OpenRouter's auto router shows a -24.7% performance change relative to Best Single. Swapping the embedding backbone for much weaker encoders made no significant difference.
- **Most of the routable gap is task type.** *Most of the LLM Routing Gap Is Task Type* (Janghoon Lee, arXiv 2608.23023) [A]: 14 models, 294 questions. Re-running the identical experiment flipped 5.37% of 4,116 model-question pairs; under a both-runs-correct rule only 29 questions are improvable by routing, and a static task-type table captures 21 of them. Static table: 262/294 at $3.33 vs best single model 245/294 at $7.69. Caveat stated by the author: fitted and scored on the same 294 questions, no holdout; single-author preprint. Relevance: a lookup table, which is exactly "simple host rules", may capture most of what any router can.
- **Oracle headroom is not realizable headroom.** *Opportunity Is Not Realizability* (Shihab et al., arXiv 2608.08265) [A]: certified oracle gap of 9.7 to 30.7 points, but "the strongest deployable prompt router recovers only 7.5 to 14.4% of that gap", and the simultaneous interval for the best of eleven policies has a lower limit of zero.
- **Routers over-select expensive models.** *When LLM Routers Overpay* (Lai, Chen, Ye; arXiv 2602.03478; listed as accepted to NeurIPS 2026) [A]: as budgets loosen, routers increasingly pick the most expensive model even when cheaper ones have equal utility. RouterArena [F] reports the same for a commercial router (NotDiamond ranked last overall for picking expensive models).
- **Independent leaderboard: no router dominates.** *RouterArena* (Lu et al., Rice; arXiv 2510.00202 v3; ICLR 2026 per conference listing [NV for venue]) [F]: about 8,400 queries. Accuracy / cost per 1k queries: GPT-5 (internal router) 74.0% / $14.02; Azure model router 68.1% / $0.54; NotDiamond 68.0% / $9.34; vLLM-SR 67.3% / $1.67; CARROT 67.2% / $2.06; MLP 61.6% / $4.83; kNN 58.7% / $4.27; GraphRouter 57.0% / $0.34; RouteLLM 47.0% / $0.27. "No router ranks at the top across all metrics." Robustness is "uniformly low" across commercial and academic routers. On hard queries most routers score below 10%.
- **Out-of-distribution generalisation.** *Large Language Model Routing with Benchmark Datasets* (Shnitzer et al., arXiv 2309.15789) [F]: correctness predictors average 0.59 accuracy on held-out HELM tasks; the best practical router scores 0.694 vs 0.688 for the best model on average (a 0.006 gain) and picks that best-average model in 48% of cases; oracle 0.773. "major challenge of LLM routing is OOD generalization of correctness predictors". *Embedding Geometry Shapes LLM Routing* (Torti et al., arXiv 2610.19198) [A]: semantic-embedding routers "struggle to generalize to unseen tasks". (A search summary also attributed to this paper the statement that no router beat best-single-model out of distribution at zero cost penalty; I could not confirm that sentence in the abstract: [NV].)
- **Even RL-trained LLM routers learn trivial policies.** *xRouter* (Qian et al., Salesforce; arXiv 2510.08439) [F]: reaches roughly 80 to 90% of GPT-5 accuracy at a fraction of cost on math benchmarks (for example MATH-500 0.94 at $0.0022 vs GPT-5 0.97 at $0.0212), but the authors report the router "consistently converges to disappointingly simple patterns" and "learns to avoid failure rather than to excel"; sophisticated orchestration did not emerge.

### 1.3 Robustness and adversarial rerouting

*Rerouting LLM Routers* (Shafran, Schuster, Ristenpart, Shmatikov; arXiv 2501.01818) [F]: query-independent "confounder gadgets" force routing to the strong model. White-box upgrade rates on MT-Bench 100% for three of four RouteLLM-style routers (73% for the LLM classifier); black-box transfer 39 to 100% (MT-Bench), 16 to 82% (MMLU), 60 to 99% (GSM8K). Commercial: Unify 79 to 91% upgrades (cost about 1.7x); OpenRouter cost from $0.03 to an average $0.25 ("a greater than 8x increase"). "perplexity-based filtering is not an effective defense." A follow-up defence (RerouteGuard, arXiv 2601.21380) is [NV].

Relevance to Turnwise: in an agent loop the routed "query" includes tool outputs, which are attacker-controllable. A learned step router inherits this attack surface; a rule-based typed policy that never reads free text for its tier decision would not, which is one of the few places the literature leaves room for a Turnwise-style advantage. No paper I found tests this.

### 1.4 Surveys

- *Dynamic Model Routing and Cascading for Efficient LLM Inference: A Survey* (Moslem, Kelleher; arXiv 2603.04445; accepted to TMLR 2026 per arXiv comments) [A]. Claims well-designed routing "can outperform the strongest single model while improving efficiency"; names generalisation across architectures, modalities and applications as open.
- *Doing More with Less: A Survey on Routing Strategies...* (Varangot-Reille et al., arXiv 2502.00409 v3, July 2025) [F]. "A significant limitation of existing routing systems is that they are static"; "The field lacks a standardised framework for evaluating routing strategies"; verbalised confidence is unreliable because "LLMs tend to be overconfident".
- *Adaptive Computation in the LLM Era: A Unified Survey of Routing, Cascades, and Test-Time Scaling* (Cambridge listing, June 2026) [NV]; a search summary says it lists "step-level deferral with guarantees" as an open problem.

### 1.5 Reading for Turnwise

The per-query literature supports only a weak form of the economic premise: an oracle rarely needs the most expensive model (RouterBench), but deployable routers recover a small fraction of that headroom (7.5 to 14.4% in one certified estimate), need labelled in-domain data, and a static task-type table gets most of it. Turnwise's "tiny trained router on synthetic data" sits squarely in the regime the literature says does not transfer: RouteLLM's routers were at or below random on MMLU and GSM8K until given in-domain labels.

---

## 2. Per-step routing inside agents (the central question)

### 2.1 Direct evidence: step-level or mid-trajectory model switching, measured end to end

**The Handoff Tax: Continuing Non-Native Trajectories in LLM Agents** (Ganz, Shpigel Nacson, Kalyanpur, Litman; arXiv 2608.24358, 25 Aug 2026; preprint) [F]. The most rigorous direct test I found.

- Setting: SWE-bench Verified, all 500 instances, mini-SWE-agent; 58 configurations per model family, 58,000 runs. Pairs: Claude Haiku 4.5 (LC) / Claude Opus 4.7 (HC); GPT-5.6 Luna (LC) / GPT-5.6 Sol (HC). Costs reconstructed from provider-reported input, cache and output tokens with cache-aware price cards.
- Escalation (start cheap, switch to strong), averaged over seven switch points:

| Strategy | Claude pass % | Claude $/task | GPT pass % | GPT $/task |
|---|---|---|---|---|
| LC only | 60.7 | 0.40 | 58.7 | 0.06 |
| HC only | 79.2 | 0.72 | 83.7 | 0.47 |
| Abort, restart HC fresh | 79.2 | 0.90 | 83.7 | 0.51 |
| Raw trajectory handoff | 69.2 | 1.61 | 67.5 | 0.36 |
| Compaction by prefix model | 71.8 | 0.75 | 68.8 | 0.27 |
| Drop trajectory, keep edits | 72.4 | 0.81 | 79.7 | 0.50 |

- Stated conclusion: full-trajectory escalation "recovers less than half of the LC-to-HC quality gap" at a substantial cost premium. For Claude, raw escalation is strictly dominated by simply restarting with the strong model ($1.61 and 69.2% vs $0.90 and 79.2%). No escalation interface beats HC-only on both axes.
- Downshift (start strong, switch to cheap) is the favourable direction: Claude raw 65.6% at $0.51 vs HC-only 75.8% at $0.85; GPT raw 81.0% at $0.41 vs 85.8% at $0.47. It still loses 5 to 10 points.
- Side observation (reviewer arithmetic): the Claude LC:HC cost-per-task ratio is only 1.8x ($0.40 vs $0.72) although the list-price ratio between those two models is 5x. Weak models spend more steps.
- Limits: two model pairs; one main benchmark; one run per task-configuration; switch points fixed in advance, not chosen by a policy. A smart policy might do better than fixed switch points, but the handoff penalty itself is policy-independent.

**ShadowPrefill: Keeping Your Next Model Warm for Per-Step Model Routing in Agentic LLM Serving** (Qiu, Mahapatra, Fonseca, Russinovich; Microsoft Azure Research; arXiv 2611.13176, 9 Nov 2026; preprint) [F]. Names and quantifies the "model switch tax".

- Mechanism: prefix caching is per model; "KV is a function of the model's weights, so the cache cannot be shared across models."
- Measured: prefix hit rate 80 to 89% on same-model calls vs 44 to 65% on switch calls; a switch call takes 1.5 to 3.2x as long; 19 to 33% of calls switch model; sessions switch 2.0 to 4.1 times on average and about 11 to 13 times on SWE-bench (the paper is internally inconsistent: 10.9 in a table, 13 in text).
- Economics: without mitigation, routing saves 28 to 44% of the always-expensive cost; with their cache pre-warming, 49 to 56%. That is a serving-side fix available to an operator who owns the GPUs, not to an API customer.
- End-to-end on SWE-bench (50-task cohort, open models): always SWE-agent-LM-32B resolves 42.0%; the 7B/32B per-step router resolves 32.0%; always-7B 16.0%. The router loses 10 points to always-large; the paper does not discuss this. With a different large model (Qwen2.5-72B, 14.0% alone) the router scores 14.0%.
- Limits: mostly simulation; 50 tasks; the router's training labels "measure model agreement, not task success". The positive accuracy claims (router 6.6 to 13.6 points above "always expensive") come from simulated QA-style workloads.

**TwinRouterBench** (Yang, Chen, Shi et al.; arXiv 2605.18859 v5, Oct 2026; preprint) [F]. A step-level routing benchmark that labels each step with the cheapest tier that still lets the whole trajectory pass.

- How much of a trajectory is "easy": of 970 labelled steps (520 instances over SWE-bench, BFCL, mtRAG, QMSum, PinchBench), 689 (about 71%) have a low-tier target; 170 need the high tier, and SWE-bench accounts for 168 of those 170. Labels are "execution-verified estimates", derived from successful strong-model trajectories by greedy search, with an 11-model pool.
- Error compounding is visible: on the SWE-bench static slice "every router has negative cost savings there, because one under-routed step fails the whole trajectory." Two rule-based routers fail 38 of 40 and 39 of 40 SWE trajectories. Opus 4.6 used as the router predicted "high" for only 7 of 147 verified-high steps and all 40 SWE trajectories failed.
- Live track (100 non-random SWE-bench Verified instances, single run): a trained router resolved 75/100 at $25.66 total API cost vs unrouted Opus 4.6 at 74/100 and $54.73 (53.1% cheaper); a kNN router 75/100 at $55.61 (no saving); the rule-based version of the same router 73/100 at $172.56 (3.2x more expensive than no routing).
- Limits: the one clearly positive result comes from the only router fitted on the benchmark's own static-track labels; 100 hand-locked instances (18 Astropy, 82 Django); no repeated runs; execution "not fully repeatable" by the authors' own audit.

**SWE-Router** (Son et al., UCL; arXiv 2607.00053; preprint) [F]. Lets a weak model run K turns, then a value head on the partial trajectory decides whether to continue or restart with the strong model from the original prompt.

- Endpoints on SWE-bench Verified: gpt-5-mini 55.6% at $16.6; deepseek-v3.2 62.4% at $22.6; gemini-3-pro-preview 70.4% at $391.3.
- Prompt-only routers are near useless here (best prompt-only Route-AUC 0.476 to 0.565); conditioning on two turns of trajectory lifts Route-AUC to 0.780 (deepseek pair).
- The design deliberately avoids mid-trajectory handoff, citing the observation that conditioning a strong model on a weak model's reasoning biases it toward the weak model's mistakes. This is task-level routing with a probe, not per-step routing. Results are inconsistent across splits; two model pairs.

**AgentRouter: Heterogeneous Model Routing for Cost-Optimal Multi-Step Agentic Workflows** (Paul, Nandy; arXiv 2609.22951; AgenticUQ workshop at ICML 2026) [F via PDF text]. The most optimistic step-level result, and the weakest evidence.

- Claims: 71.8% cost reduction at 97.3% of frontier-only quality; per-step RouteLLM 31.4% saving at 94.2%, FrugalGPT cascade 44.1% at 96.8%. "only 14.2% of steps genuinely require frontier models, yet those steps consume 48.3% of the remaining cost"; the minimal tier covers 35.3% of steps and 10.8% of cost.
- Why it does not settle anything: evaluated on the authors' own 2,400 trajectories of 4 to 12 steps; the "frontier" tier is GPT-4o with Llama-3-8B at the bottom; cost is priced on tokens with no prompt-cache accounting that I could find; and the authors state that the method "assumes the step sequence is known or estimable at routing time" and that fully online agentic scenarios "fall outside the current scope". Unseen framework: 6 to 9% accuracy degradation. The claim that frontier-only routing wastes "60–80% of inference budget" is asserted in the abstract, not measured on a public benchmark.
- Note on the name: other papers also use "AgentRouter" (for example a knowledge-graph router for multi-agent QA); I verified only this one.

**TurnCost: Turns, Not Observations: Cache-Aware Loop Engineering for Coding Agents** (Kumar, Pandey; arXiv 2610.15093; preprint) [A]. 600 public coding-agent trajectories, two scaffolds, two models.

- "98.6% of input tokens are served from a prefix cache"; flat input pricing "overestimates loop cost by roughly 7x on average".
- Derives a closed-form break-even for delegating turns to a cheaper model; "Delegation increased cost in half of the evaluated settings".
- "Turn count explains 84% of the variance in log trajectory cost", versus 4% for mean observation size.
- Limits: abstract only; re-scoring of existing trajectories, so it does not show that turns can be removed at fixed success (the authors say so).

**Other step-level or escalation work**

- *TACIT-Switch* (Lei, Huang; arXiv 2608.27911) [A]: learns a permanent weak-to-strong handoff point from trajectory evidence; +7.4 to 11.1 points over task-level, step-level and fixed-prefix routing baselines in simulation; ALFWorld 48.5%, DABench 73.1%. The abstract reports no always-strong baseline.
- *SWE-Protégé* (Kon et al.; arXiv 2602.22124) [A]: a post-trained Qwen2.5-Coder-7B that learns when to ask an expert reaches 42.4% on SWE-bench Verified with about 4 expert calls per task and about 11% of tokens from the expert. Here the small model itself, not an external policy, decides when to escalate, and it had to be fine-tuned with RL to stop looping.
- *New Model, Old Habits* (Choi et al.; arXiv 2610.19712) [A]: "behavior transfer" - a recipient model adopts the reasoning and action patterns of the model that wrote its history; strongest with raw-history transfer, reduced by summarisation.
- *Evaluating Performance Drift from Model Switching in Multi-Turn LLM Systems* (Khraishi et al.; arXiv 2603.03111) [A]: a single mid-conversation switch moves Multi-IF strict success by -8 to +13 points and CoQA F1 by about 4, comparable to the gap between GPT-5-nano and GPT-5-mini.

### 2.2 Position papers and efficiency studies

- **Small Language Models are the Future of Agentic AI** (Belcak et al., NVIDIA; arXiv 2506.02153; v1 June 2025, v3 Sep 2026) [A, and F for v2]. A position paper. It contains no experiments. The often-quoted replaceability figures (MetaGPT about 60%, Open Operator about 40%, Cradle about 70% of LLM calls) are author estimates with no measurement procedure. The "10–30x cheaper" serving claim cites secondary sources. The authors concede that the centralised-LLM-is-cheaper view is "a valid view" and "the jury is still out". I found no formal published critique; the authors invite correspondence on an NVIDIA page I did not open. Treat it as a hypothesis statement, not evidence.
- **Efficient Agents** (Wang et al.; arXiv 2508.02694; "work in progress") [F]. GAIA only. Retains 96.7% of OWL's performance while cutting cost; cost-of-pass improves 28.4%. Backbones: Claude 3.7 Sonnet 61.82% at cost-of-pass 3.54; GPT-4.1 53.33% at 0.98. Best-of-N from 1 to 4 adds 0.6 points for a third more tokens. It does not test mixed-model configurations at all; the savings come from removing scaffold complexity. Single runs; tables conflict with text.
- **BudgetMLAgent** (Gandhi et al.; arXiv 2411.07464; AIMLSystems 2024) [A]. Gemini base with GPT-4 in a cascade and as an occasional "expert" for planning: cost per run $0.931 to $0.054 (94.2% reduction) and success 22.72% to 32.95% on MLAgentBench. An early positive result for planner-escalation, with 2024 models, a free-tier base model, and a low absolute success rate.
- **MasRouter** (Yue et al.; arXiv 2502.11133) [A]: routes collaboration mode, roles and LLMs in multi-agent systems; +1.8 to 8.2% on MBPP, up to 52.07% lower overhead on HumanEval. Code benchmarks of the pre-agentic kind.
- **Router-R1** (Zhang, Feng, You; arXiv 2506.09033; NeurIPS 2025) [A]: an LLM router trained with RL for multi-round routing on seven QA benchmarks. The router is itself a generative LLM, which is the opposite of the Turnwise design.
- **TREACLE** (Zhang et al.; arXiv 2404.13082) [A]: RL policy picking model and prompt under a budget; "up to 85%" savings on GSM8K, CSQA, LLC. Single-question reasoning, not agents.
- **Agent S2** (Agashe et al.; arXiv 2504.00906) [A]: delegates grounding and planning to different generalist and specialist models; relative gains of 18.9% and 32.7% on OSWorld. This is a fixed role split (a workflow), not a per-step router, and is motivated by accuracy, not cost.

### 2.3 What products already do (commoditisation)

| Product / pattern | What it does | Evidence and caveats |
|---|---|---|
| **Microsoft Foundry model router** (official docs dated 2026-11-18) [F] | A trained non-LLM routing model ("It's a purpose-built machine learning model") picks among 45 models per request. "By default, model router repeats these steps for every request, so the turns of one conversation can go to different models." Marketed as "Built for agents and coding tools. Each step of an agent ... can get a different model". Works as the model behind LangGraph, OpenAI Agents SDK, Claude Agent SDK, Claude Code and others. | Session affinity (preview): in `adaptive` mode it keeps the previous model when "that model's prompt cache is likely still warm" and its expected quality is within the routing mode's band; `sticky` holds for 30 minutes. A routing fee per million input tokens applies (the public price page showed "$-"; fee not verified). No quantified savings are published; Microsoft tells customers to evaluate on their own prompts. In RouterArena it scored 68.1% at $0.54 per 1k queries. |
| **Cursor Router** (docs; blog 6 Aug 2026) [F] | "runs a classifier on each agent request and routes it based on task type and complexity"; per turn, using current-turn signals plus recent tool calls. | Vendor claims: Auto Balance beats Opus 4.8 on user satisfaction at 41% lower cost; Auto Intelligence "above Fable-level user satisfaction at 68% lower cost". Quality is a behavioural proxy (whether the user moves on or corrects the agent), not task correctness. The blog says the cost data captures "cache misses caused by switching models". |
| **GitHub Copilot auto model selection** (docs) [F] | Combines system health with task complexity; "For each prompt, the model is selected by considering cost, quality, and latency"; routing happens at "natural cache boundaries and large drifts in conversation complexity". 10% discount on model costs. | No published accuracy or savings data. |
| **OpenRouter Auto Router** (docs) [F] | A "fast decision model rates eleven aspects of the request"; picks model and reasoning effort. Avoids frequent switching because "Switching models costs extra while the new model rebuilds the prompt cache." | The docs say the current default policy "costs more per task than the previous generation". LLMRouterBench measured an earlier version at -24.7% vs best single model. |
| **Amazon Bedrock Intelligent Prompt Routing** (user guide; product page) [F] | Routes between exactly two models of one family per request, using a predicted "response quality difference". | Vendor claim: "can reduce costs by up to 30% without compromising on accuracy". Documented limits: "only optimized for English prompts"; "can't adjust routing decisions or responses based on application-specific performance data". |
| **OpenAI GPT-5 real-time router in ChatGPT** (system card) [F] | Routes between fast and thinking models "based on conversation type, complexity, tool needs, and explicit intent"; "continuously trained on real signals, including when users switch models". | On 11 Dec 2025 OpenAI's release notes announced "removing automatic model switching for reasoning in ChatGPT" for Free and Go users, who now default to GPT-5.2 Instant [S: Gizmodo, 16 Dec 2025]. Reports that the router hurt engagement are attributed to WIRED sources and are [NV]. |
| **Claude Code `opusplan`** (docs) [F] | "uses `opus` during plan mode, then switches to `sonnet` for execution". | The same docs warn: "each plan-mode toggle is a model switch and starts a fresh cache." |
| **Anthropic advisor tool** (blog 9 Apr 2026; Claude Code docs) [F] | A cheaper executor runs the loop and consults a stronger model at decision points; "the timing is model-driven rather than rule-based". | Vendor claims: Sonnet 4.6 + Opus 4.6 advisor +2.7 points on SWE-bench Multilingual with cost per task down 11.9%; Haiku 4.5 + Opus advisor 41.2% vs 19.7% on BrowseComp. Caveats in the post itself: arms differ in thinking settings and system prompt. "The advisor model's own read of the conversation is not cached. Each advisor call processes the full transcript anew." Experimental. |
| **Aider architect/editor** (blog 26 Sep 2024) [F] | A reasoning model plans, a second model writes edits. | Own benchmark: o1-preview + o1-mini or DeepSeek 85.0% vs o1-preview solo 79.7%; Claude 3.5 Sonnet paired with itself 80.5% vs 77.4% solo. Gains appear even when both roles use the same model, so the benefit is the two-pass workflow, not routing. |
| **Amp "oracle"** (docs) [F, limited] | A second-opinion subagent the main agent may consult. | The docs page I opened does not state which model tier it uses. Model details [NV]. |
| **Windsurf auto modes** | Not found in a primary source. | [NV] |

The pattern across vendors: per-turn routing exists, is run by non-LLM classifiers trained on very large proprietary interaction logs, and has converged on cache-aware stickiness. None publishes task-success evidence; all the savings numbers are marketing or behavioural proxies.

### 2.4 HAL and "AI Agents That Matter"

- **Holistic Agent Leaderboard** (Kapoor, Stroebl et al.; arXiv 2510.11977) [F]: 21,730 rollouts, 9 models, 9 benchmarks, about $40,000. Gemini 2.0 Flash is on the cost-accuracy Pareto frontier in 7 of 9 benchmarks, GPT-5 in 4, o4-mini Low in 4; "In only 1 of 9 benchmarks do we observe the most costly model run on the Pareto frontier." Higher reasoning effort gave equal or lower accuracy in 21 of 36 model-agent-benchmark combinations. This supports "the most expensive setting is often not needed", but as a whole-task model choice, not per-step routing.
- **AI Agents That Matter** (Kapoor et al.; arXiv 2407.01502) [F]: on HumanEval, simple baselines match or beat complex agents at a fraction of the cost (warming GPT-4 93.2% at $2.45 vs LATS 88.0% at $134.50). A task-level "escalation" baseline (cheap model first, escalate on test failure) reaches 85.0% at $0.27 vs GPT-4 89.6% at $1.93. Joint cost-accuracy optimisation on HotPotQA cut variable cost 53% (GPT-3.5) and 41% (Llama-3-70B) at similar accuracy. Message for Turnwise: cost must be on the Pareto plot, and trivially simple baselines are strong; any Turnwise result needs them as nulls.

### 2.5 Does error compounding erase per-step savings? Where does the money sit?

- **Compounding is real and asymmetric.** TwinRouterBench: one under-routed step fails the trajectory, giving every router negative savings on the SWE-bench slice. Handoff Tax: escalation after a weak prefix recovers under half the gap. *The Illusion of Diminishing Returns* (Sinha et al.; arXiv 2509.09677; ICLR 2026) [A]: small per-step accuracy differences compound into large differences in executable task length; models "self-condition" on earlier errors in context; this is not fixed by model size, but is mitigated by thinking. A cheap model's mistakes therefore tax later strong-model steps.
- **Where the tokens are.** *How Do AI Agents Spend Your Money?* (Bai et al.; arXiv 2604.22750, v3 Oct 2026; NeurIPS 2026 per listing [NV for venue]) [A]: on SWE-bench Verified with eight frontier models, input tokens rather than output tokens drive cost; runs on the same task differ by up to 30x in total tokens; "accuracy often peaks at intermediate cost"; models predict their own token use poorly (correlation up to 0.39). Together with TurnCost (98.6% of input tokens are cache reads) this means the bulk of a coding agent's token volume is re-read context billed at the cached rate.
- **How much is "easy".** By step count, a lot: about 71% of steps low-tier-sufficient (TwinRouterBench, conditional on a successful strong trajectory), 35% minimal-tier (AgentRouter's own data). By cost, much less: AgentRouter's frontier-needed steps are 14.2% of steps but 48.3% of cost; TwinRouterBench notes a 20k-token warm step saves about 2 cents when downgraded versus about 61 cents for a 100k cold step. Easy steps are numerous and cheap; the expensive steps are the ones that need the strong model.
- **I found no measurement** of the share of trajectory dollars sitting in steps that need no model at all (the Turnwise "answer directly / deterministic tool / fixed workflow" operations). That number is unknown.

---

## 3. Things that compete with routing for the same savings

### 3a. Prompt caching

**Official pricing, read 2026-11-20.**

Anthropic ([pricing](https://platform.claude.com/docs/en/about-claude/pricing), [prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)) [F], USD per million tokens:

| Model | Input | 5-min cache write | 1-h cache write | Cache read | Output |
|---|---|---|---|---|---|
| Claude Fable 5.2 | 8 | 10 | 16 | 0.20 (0.025x) | 40 |
| Claude Opus 5.5 | 4 | 5 | 8 | 0.20 (0.05x) | 20 |
| Claude Sonnet 5.5 | 2 | 2.50 | 4 | 0.10 (0.05x) | 10 |
| Claude Haiku 5.5, prompt up to 100k tokens | 0.10 | 0.125 | 0.20 | 0.01 | 0.50 |
| Claude Haiku 5.5, prompt over 100k tokens | 0.50 | 0.625 | 1 | 0.05 | 2.50 |
| Claude Opus 5 / 4.8 / 4.7 / 4.6 / 4.5 | 5 | 6.25 | 10 | 0.50 | 25 |
| Claude Sonnet 4.6 | 3 | 3.75 | 6 | 0.30 | 15 |
| Claude Haiku 4.5 | 1 | 1.25 | 2 | 0.10 | 5 |

Write premium 1.25x (5-minute TTL) or 2x (1-hour TTL); read 0.1x on most models, 0.05x on Opus 5.5 and Sonnet 5.5, 0.025x on Fable 5.2 and 5.1. The 5-minute cache "is refreshed for no additional cost each time the cached content is used". Minimum cacheable prefix 512 to 4,096 tokens depending on model. Caches are isolated per organisation and, on the first-party API, per workspace.

OpenAI ([pricing](https://developers.openai.com/api/docs/pricing), [prompt caching guide](https://developers.openai.com/api/docs/guides/prompt-caching)) [F], standard tier:

| Model | Input | Cached input | Output |
|---|---|---|---|
| gpt-6.2-astra | 8.00 | 0.40 | 40.00 |
| gpt-6.2-sol | 2.00 | 0.10 | 10.00 |
| gpt-6.1-terra | 1.00 | 0.05 | 5.00 |
| gpt-6-luna | 0.10 | 0.01 | 0.50 |
| gpt-5.5 | 5.00 | 0.50 | 30.00 |
| gpt-5.4-mini | 0.75 | 0.075 | 4.50 |
| gpt-5-mini | 0.25 | 0.025 | 2.00 |
| gpt-5-nano | 0.05 | 0.005 | 0.40 |

Cached input "discounted up to 95%". For GPT-5.6 and later, cache reads cost 0.1x (0.05x on the GPT-6.1/6.2 flagship models) and cache writes now carry a premium: 1.25x for the default 30-minute lifetime or 2.5x for 12 hours. Earlier models: in-memory retention "around 5 to 10 minutes of inactivity, up to one hour", with a 24-hour option. Caching is automatic. Caches are "not shared across organizations". The guide says the cache stores KV tensors and that "a different model can use different weights and caching behavior"; it does not contain an explicit sentence that caches are per-model.

Google ([pricing](https://aistudio.google.com/docs/pricing), [caching](https://aistudio.google.com/docs/caching)) [F], standard paid tier:

| Model | Input | Output (incl. thinking) | Cached input |
|---|---|---|---|
| Gemini 4 Carbon / Argon | 2.00 (4.00 from 1 Dec 2026) | 10.00 (20.00) | 0.10 (0.20) |
| Gemini 4 Neon | 3.00 | 15.00 | 0.15 |
| Gemini 4 Hydrogen | 1.50 | 7.50 | 0.075 |
| Gemini 3.1 Pro Preview (prompts up to 200k) | 2.00 | 12.00 | 0.20 |
| Gemini 3.8 Flash | 0.75 (1.50 from 1 Jan 2027) | 3.75 (7.50) | 0.075 (0.15) |
| Gemini 3.5 Flash-Lite | 0.30 | 2.50 | 0.03 |

Implicit caching is on by default for Gemini 2.5 and newer, with a 4,096-token minimum on Gemini 3.x and 4; explicit caches are not supported for Gemini 4 models. Explicit cache storage is charged per million tokens per hour ($4.50 for Gemini 3.1 Pro). The caching page I read does not state TTL defaults or per-model scope.

**Are caches per-model? Verified statements.**

- Claude Code docs [F]: "Each model has its own cache. Switching models recomputes the entire request even when the content is identical." And for `opusplan`: "each plan-mode toggle is a model switch and starts a fresh cache."
- Anthropic engineering blog, 30 Apr 2026 [F]: "Prompt caches are unique to models"; "if you're 100k tokens into a conversation with Opus and want to ask a question that is fairly easy to answer, it would actually be more expensive to switch to Haiku than to have Opus answer, because we would need to rebuild the prompt cache for Haiku." Their recommendation: "If you need to switch models, the best way to do it is with subagents." They "run alerts on our prompt cache hit rate and declare SEVs if they're too low."
- Microsoft Foundry docs [F]: "A cache hit happens when the same model serves consecutive requests with overlapping prompt prefixes."
- OpenRouter docs [F] and ShadowPrefill [F]: quoted above.
- The Anthropic API prompt-caching page (first 100k characters) and the Google and OpenAI pages do not state it in one sentence; the mechanism (KV state tied to weights, exact prefix match) implies it.

One nuance (my inference from the Claude Code docs, which say two requests share a cache only when "model, speed, and prefix match", and that an older entry can be re-read within its lifetime): switching away does not destroy the first model's cache; it lives until its TTL lapses. Alternating between two models therefore maintains two caches, each paying its own writes, and the frontier cache silently expires if the cheap model runs for longer than the TTL.

**Reviewer arithmetic: one "easy" step, list prices above, 1,000 new input tokens and 300 output tokens.**

| Context already cached on the frontier model | Stay on warm Opus 5.5 | Switch to Haiku 5.5, cold | Switch to Haiku 5.5, already warm | Switch to Haiku 4.5, cold | Opus 5.5 cache lapsed, full rewrite |
|---|---|---|---|---|---|
| 50k tokens | $0.021 | $0.0065 (0.31x) | $0.0014 (0.06x) | $0.065 (3.1x) | $0.261 |
| 150k tokens | $0.041 | $0.095 (2.3x) | $0.012 (0.29x) | $0.190 (4.6x) | $0.761 |

Reading: (i) with the previous small tier (Haiku 4.5) a cold switch always cost more than staying, which is what Anthropic's blog describes; (ii) with Haiku 5.5 a cold switch is cheaper below 100k tokens of context but 2.3x more expensive above it, because Haiku 5.5 is priced by prompt length; (iii) a single lapse of the frontier model's cache costs as much as the savings from 12 to 25 warm cheap steps (12 to 41 across Opus 5.5, Fable 5.2 and Sonnet 5.5 as the heavy model); (iv) Sonnet 5.5's cached read ($0.10) equals Haiku 5.5's fresh input price ($0.10), and Opus 5.5's and Fable 5.2's cached read ($0.20) is twice it. On the dominant token class in an agent loop, the frontier is already nearly as cheap as the small model's uncached rate. The remaining lever for routing is output tokens (20x to 80x cheaper on the small tier) and warm small-model reads. These are derivations, not measurements.

**Measurements of caching in agent loops.**

- *Don't Break the Cache* (Lumer et al., PwC; arXiv 2601.06007 v2) [F]: DeepResearch Bench, 10,000-token system prompt, over 500 sessions. Cost savings versus no cache: GPT-5.2 79.3 to 81.4%; Claude Sonnet 4.5 77.8 to 78.5%; Gemini 2.5 Pro 27.8 to 41.4%; GPT-4o 45.9 to 47.8%. Time-to-first-token improvements 6 to 31%, with regressions in some configurations. It does not test model switching.
- TurnCost [A] and ShadowPrefill [F] as above: 98.6% of input tokens cached; switch calls hit 44 to 65% vs 80 to 89%.
- Handoff Tax [F] is the only study I found that measures task success and cache-aware dollars together under model switching.

A provider that already delivers about 80% off through caching with zero quality risk leaves a routing layer to fight over the remaining 20%, while routing itself destroys cache hits.

### 3b. Reasoning-effort knobs: routing without switching models

- Anthropic effort ([docs](https://platform.claude.com/docs/en/build-with-claude/effort)) [F]: levels low, medium, high, xhigh, max; "You can trade off between response thoroughness and token efficiency with a single model"; effort "affects all tokens in the response", including tool calls; `low` is suggested for "Simpler tasks that need the best speed and lowest costs, such as subagents". Adaptive thinking is always on for current models, and at lower effort the model "can skip thinking entirely for simpler problems". Crucially for this review: "A per-message effort change keeps the prompt cache", available on Fable 5.1 and later, Opus 5 and 5.5, Sonnet 5.5 and Haiku 5.5. The docs also say `max` is "prone to overthinking".
- OpenAI ([reasoning guide](https://developers.openai.com/api/docs/guides/reasoning)) [F]: `reasoning.effort` values up to `max`, model-dependent; "Lower effort favors speed and lower token usage"; the model adapts, "using fewer tokens for simpler tasks and thinking harder for complex tasks"; a `configuration_update` item is recommended for mid-conversation changes because it "preserves the original prompt prefix".
- Google ([thinking](https://aistudio.google.com/docs/thinking)) [F]: `thinking_level` low to xhigh; "Gemini models engage in dynamic thinking by default"; "pick the lowest `thinking_level` that meets your quality bar"; xhigh "can cause overthinking".
- Evidence that the knob matters: HAL found higher effort gave equal or lower accuracy in 21 of 36 combinations.

All three vendors now offer difficulty-adaptive spend inside one model, and two document a cache-preserving way to vary it per step. This is the most direct substitute for LIGHT/HEAVY routing, and none of the step-routing papers above includes "same frontier model, lower effort" as a baseline. Any Turnwise experiment must.

### 3c. Price trends and current tier ratios

- **a16z "LLMflation"** (Appenzeller, 12 Nov 2024; investor blog) [F]: for equivalent performance "the cost is decreasing by 10x every year"; MMLU-42 capability from $60 to $0.06 per million tokens in three years; GPT-4-level about 62x cheaper since March 2023. Caveats in the post: MMLU contamination, averaged input/output pricing.
- **Epoch AI, "LLM inference prices have fallen rapidly but unequally across tasks"** (Cottier et al., 12 Mar 2025) [F]: declines of 9x to 900x per year depending on the performance milestone; 40x per year for GPT-4-level on PhD-level science questions; the fastest drops are recent and "less clear ... will persist".
- **Epoch AI, "The plunging price of thought"** (Emberson, Roodman, 22 Sep 2026) [F]: the cost of a given performance level has fallen about 47% per quarter, 13x per year, since 2023 across five benchmarks; near-frontier levels fall fastest (about 75x per year when first state of the art, 4.7x per year two years later). Caveat stated: the analysis assumes users always pick the cheapest sufficient model, which they do not.
- **Current small-to-frontier list-price ratios** (from the tables above; reviewer arithmetic): Anthropic Opus 5.5 to Haiku 5.5 40x (Fable 5.2 to Haiku 5.5 80x; Sonnet 5.5 to Haiku 5.5 20x); the previous generation was 5x (Opus 4.x to Haiku 4.5). OpenAI gpt-6.2-astra to gpt-6-luna 80x; gpt-6.2-sol to gpt-6-luna 20x; gpt-5.5 to gpt-5-nano 100x on input. Google Gemini 4 Carbon to 3.5 Flash-Lite 6.7x on input, rising to about 13x on 1 Dec 2026.
- Two observations. First, the tier spread has widened in the current generation, which raises the theoretical upside of routing on uncached and output tokens; that is a point in the hypothesis's favour. Second, a 47% per-quarter decline means a one-off 30 to 50% routing saving is worth roughly one quarter of waiting (reviewer inference; it holds only for a fixed capability level). Third, not all prices fall: Google lists scheduled doublings for Gemini 4 Carbon/Argon and Gemini 3.8 Flash, and Anthropic notes its newer tokenizer produces about 30% more tokens for the same text.

### 3d. Batch and flex tiers

- Anthropic Batch API: "50 percent discount on both input and output tokens"; stacks with caching; not available for Managed Agents sessions, and fast mode is excluded [F].
- OpenAI: Batch is half the standard price across the table; Flex is also half price but the page says it will not be added to new models (gpt-6.2 is not listed for Flex); priority processing was renamed Fast mode and costs 2x [F].
- Google: Batch and Flex at half the standard price; Priority at 1.8x [F].
- Relevance: batch and flex are asynchronous or latency-tolerant, so they do not fit an interactive per-step loop, but for offline agent workloads a flat 50% with no quality risk is another null a routing claim must beat.

---

## 4. Learned versus rule-based policies

- **Bandits with online feedback.** *PILOT* (Panda et al.; arXiv 2508.21141; EMNLP 2025 Findings per listing [NV for venue]) [F]: LinUCB with a preference prior; 93% of GPT-4 performance at 25% of cost on RouterBench. It needs a ChatArena-pretrained prior plus roughly 32,000 online learning samples (10:1 learning-to-deployment split of 36,497), and its margin over plain LinUCB is small (0.63 vs 0.60 reward at $1; plain LinUCB is slightly ahead at one hyperparameter setting). Single-turn only, stated by the authors. *MetaLLM* (arXiv 2407.10834) [A] and *LLM Bandit* (arXiv 2502.02743) [A] frame selection as multi-armed bandits for classification and multiple-choice QA; abstracts give no numbers. *MixLLM* [A] as above. *ParetoBandit* (arXiv 2604.00136) [NV].
- **Data requirements seen in the opened papers:** RouteLLM about 65k human comparisons plus about 120k judged samples; Routing Plateau: going from about 30k to 302k labelled queries buys about 1 point; AgentRouter 50,000 annotated steps obtained by executing every step with every tier; Cursor "hundreds of thousands of turns from live Cursor traffic"; Microsoft "billions of interactions"; AutoMix as few as 50 examples but only because the signal comes from a verifier, not the query. A learned step router is a data business; a lab with 46 synthetic turns is not in it.
- **Do learned deferral rules beat thresholds?** *When Does Confidence-Based Cascade Deferral Suffice?* (Jitkrittum et al.; arXiv 2307.02764; NeurIPS 2023) [A]: plain confidence thresholding "often works remarkably well in practice"; learned post-hoc deferral helps mainly under specialist downstream models, label noise, or distribution shift. *Language Model Cascades: Token-level uncertainty and beyond* (Gupta et al.; arXiv 2404.10136) [A]: for generation, sequence-level confidence "suffers from the length bias problem" and learned rules on token-level uncertainty do better. Both need access to model internals (logits, embeddings) that hosted frontier APIs largely do not expose, and neither is about agents.
- **Rule-based routers in agents.** The only direct test I found is TwinRouterBench: the rule-based routers failed nearly every SWE trajectory in the static track, and the rule-based configuration cost 3.2x more than no routing in the live track, while its trained counterpart halved cost. On the per-query side, a static task-type table captured 21 of 29 improvable questions (Lee 2026). So rules work when the routing signal is coarse task type and fail when it is step-level difficulty inside a coding trajectory.
- **Conformal and guarantee-bearing cascades** (Conformal Cascade arXiv 2607.25018; C3PO; RouteNLP arXiv 2604.23577; Gatekeeper arXiv 2502.19335; "Cost-Saving LLM Cascades with Early Abstention" arXiv 2502.09054): all [NV]; seen only in search summaries. The surveys agree that verbalised confidence is overconfident and that cascade guarantees are per-query, not per-trajectory.

Net: there is no evidence that a learned step router beats a well-tuned threshold or lookup by a wide margin, and there is some evidence that naive rules fail badly inside coding trajectories. Both findings cut against a small typed policy doing model selection; neither speaks to a typed policy doing operation selection (tool, workflow, clarify, hold), which the routing literature does not study.

---

## 5. Test-time compute allocation

- **Limits of resampling.** *Inference Scaling fLaws* / *The Limits of Inference Scaling Through Resampling* (Stroebl, Kapoor, Narayanan; arXiv 2411.17501, v3 Mar 2026) [A]: with an imperfect verifier, resampling has an accuracy ceiling; "no amount of inference scaling of weaker models can enable them to match" a sufficiently strong model's single-sample accuracy; weaker models have higher false-positive rates; "optimal sampling attempts are often fewer than 10". This bears directly on any "LIGHT first, verify, escalate" pattern: the host's verifier decides the ceiling, and false positives from the light model pass through.
- **Adaptive sampling works when agreement is a good signal.** *Adaptive-Consistency* (Aggarwal et al.; arXiv 2305.11860; EMNLP 2023) [A]: sample budget cut "by up to 7.9 times" with an average accuracy drop "less than 0.1%" across 17 reasoning and code datasets.
- **Learned allocation.** *Learning How Hard to Think* (Damani et al.; arXiv 2410.04707) [A]: predicting the marginal value of extra computation per input cuts computation by up to 50% at equal quality or improves quality by up to 10% at a fixed budget, for best-of-k and for routing between a cheap and an expensive decoding procedure.
- **Surveys.** *Reasoning on a Budget* (Alomrani et al.; arXiv 2507.02076) [A]: distinguishes controllable (fixed budget) from adaptive (difficulty-scaled) test-time compute; notes models overthink easy problems and underthink hard ones.
- **Evidence from agents.** HAL: more reasoning effort was not better in 21 of 36 runs. Efficient Agents: best-of-N adds 0.6 points for about a third more tokens. Cost-of-Pass: marginal-gain techniques "rarely justify the costs". Sinha et al.: thinking mitigates self-conditioning on errors over long horizons, so cutting thinking on "easy" steps is not free in long tasks.
- **Productised.** Adaptive thinking is on by default at all three major providers (section 3b). The "spend more only when needed" decision has largely moved inside the model.

Implication: difficulty-adaptive spend is real and useful, but the reliable signals are post-hoc (agreement between samples, a verifier, partial trajectories), not ex-ante features of the step. A policy that decides before the model runs, from typed state alone, is using the weakest class of signal identified in this literature.

---

## 6. Verdict

### What is solved, commoditised, contradicted, or open

**Solved, or at least well characterised**

- Per-query routing between known models with in-domain labels: modest savings, saturated at kNN-level methods, 10 to 30 points below oracle.
- The theory of optimal routing and cascading, and the fact that estimator quality is the binding constraint.
- Caching mechanics and their size: roughly 40 to 80% cost reduction in agent loops with no quality risk.

**Commoditised by providers**

- Per-turn routing for agents and coding tools, by non-LLM classifiers, with cache-aware stickiness (Foundry model router, Cursor Router, Copilot auto, OpenRouter Auto, Bedrock IPR).
- Planner/executor and escalation patterns (`opusplan`, architect mode, the advisor tool, oracle subagents), and cheap-model subagents.
- Difficulty-adaptive reasoning inside one model, including per-message effort changes that keep the cache.
- Batch and flex discounts.

**Contradicted or undercut**

- "Per-step savings add up at equal task quality": contradicted for mid-trajectory escalation (Handoff Tax), for a per-step router on SWE-bench (ShadowPrefill, 32% vs 42%), and by negative cost savings for every router on TwinRouterBench's SWE slice.
- "A small classifier or rules can tell which steps need the strong model": undercut by the routing plateau, by realizability estimates of 7.5 to 14.4% of oracle headroom, by chance-level out-of-distribution routing, and by rule-based step routers failing 38 to 39 of 40 trajectories.
- "Many steps do not need a frontier model, so most cost is avoidable": true by step count, false by dollar share. The easy steps are the cheap ones, and cached frontier input is already priced near small-model fresh input.
- "Switching models is free": contradicted by every provider's own documentation.

**Genuinely open**

1. Whether a typed, non-generative policy can own loop control (choose tool, workflow, clarify, hold, finish) without losing end-to-end success against a native agent. I found no study of this. It is the architectural half of the Turnwise hypothesis and is separable from the economic half.
2. Whether removing model turns altogether (deterministic tool calls and fixed workflows in place of model calls) cuts cost at equal success. TurnCost's finding that turn count explains 84% of cost variance suggests this is the larger lever, and its authors say explicitly that it is untested.
3. Downshift after the hard part (strong model plans and localises, cheap model finishes): the one switching direction with a favourable trade in Handoff Tax, still 5 to 10 points short.
4. Trajectory-conditioned signals (a few turns of evidence before deciding), which both the Routing Plateau and SWE-Router point to.
5. Cache-aware, end-to-end, held-out evidence outside SWE-bench. Almost everything above is coding.
6. Robustness of step-level routing to adversarial tool output.

### Strongest evidence that per-step model routing is not worth building

Ranked by how directly it bears on the claim:

1. **Handoff Tax** (58,000 real runs, cache-aware billing): no mid-trajectory escalation strategy beats simply running the strong model; raw escalation on the Claude pair costs 2.2x the strong model alone and loses 10 points.
2. **The vendors' own engineering guidance**: Anthropic states that switching to the small model deep in a session costs more than letting the large model answer, and treats cache-hit-rate drops as incidents. Microsoft, OpenRouter, GitHub and Cursor have all added stickiness to stop their routers from switching.
3. **TurnCost and Bai et al.**: 98.6% of input tokens are cache reads, input dominates cost, delegation raised cost in half the tested settings, and turn count rather than per-turn price explains cost.
4. **Routing Plateau, Opportunity-is-not-Realizability, RouteLLM's out-of-distribution table**: the routing signal available before the model runs is weak, does not improve with ten times the data, and does not transfer.
5. **Commoditisation**: a per-step router for agents, trained on billions of interactions and callable as a model name from the frameworks Turnwise's demo uses, already exists. A lab cannot out-collect that data.
6. **Price decline of about 13x per year**: a 30 to 50% saving is roughly one quarter's worth of price movement at fixed capability.

Counter-evidence that keeps the question alive: TwinRouterBench's trained router (53% cheaper at equal resolve rate on 100 instances); AgentRouter (72% at 97.3%, on its own short-trajectory benchmark with no cache accounting); Cursor's production claims (41 to 68% lower cost on a satisfaction proxy); the advisor tool (+2.7 points and -11.9% cost, vendor evals with unequal arms); the widened 40x to 80x tier spread. None of these is an independent, held-out, cache-aware, end-to-end result.

### The minimal experiment that would settle it

A two-stage design, the first of which costs nothing.

**Stage 0: offline ceiling check (no inference, no spend).** Take public agent trajectories with per-call token usage (the HAL logs, 2.5B tokens, are released; TurnCost releases a re-scoring tool). Re-price them under current cache-aware price cards for (a) the model actually used, (b) a hindsight-oracle per-step policy that downgrades every step a cheaper tier could plausibly serve, charging cache writes on every switch and a rewrite on every TTL lapse, and (c) the same model at lower effort. If the oracle's cache-aware saving over (a) is below the pre-declared margin, stop: no deployable policy can beat its own oracle. This directly tests the premise that a material share of trajectory dollars sits in avoidable model calls, which is currently unknown.

**Stage 1: pre-registered, executed, held-out comparison** (needs explicit owner authorisation under the project's paid-provider rules). One coding benchmark and one non-coding tool-use benchmark, at least 300 held-out tasks, at least 3 seeds per task (run-to-run token variance is up to 30x and about 5% of outcomes flip on rerun). Same tools, host, permissions and prompts in every arm:

1. Always-frontier, default effort, caching on (the reference).
2. Always-frontier with the effort knob lowered or adaptive, using cache-preserving per-message effort.
3. Always-small.
4. Small executor with a frontier advisor (provider-native).
5. A provider-native router with session affinity.
6. Simple host rules: a static step-type-to-model table.
7. Random mixing at the same light-model fraction as arm 8 (the "Zero router" null from RouterBench).
8. The Turnwise typed policy.
9. Turnwise with model selection disabled (frontier for every model call) to isolate the value of deterministic operations from the value of model routing.

Primary metrics: end-to-end task success; billed dollars computed from provider usage fields including cache reads and writes; wall-clock latency. Report every policy call, switch, retry and fallback, and the cache hit rate per arm. Decision rule, fixed in advance: Turnwise is supported only if arm 8 is non-inferior on success (say within 2 points) and at least 15% cheaper than the best of arms 1, 2, 5, 6 and 7. If arm 9 delivers the saving and arm 8 adds nothing over it, the model-routing half of the hypothesis is falsified while the turn-reduction half survives. If arm 2 or arm 6 matches arm 8, the expected outcome under the project's own rules is SHRINK or STOP.

Arms 2, 7 and 9 are the ones missing from every paper reviewed here and from the project's current list of mandatory nulls.

---

## Source table

Type key: PR = peer-reviewed venue (as stated on the page opened); PP = preprint; OD = official documentation or pricing page; VB = vendor blog or marketing; NB = investor or think-tank report; NEWS = press.

| # | Title | Authors / organisation | Date | URL | Type | Flag | Key finding used | Main limitation |
|---|---|---|---|---|---|---|---|---|
| 1 | FrugalGPT | Chen, Zaharia, Zou (Stanford) | 9 May 2023 | https://arxiv.org/abs/2305.05176 | PP (v1 opened) | F | Cost savings 98.3 / 73.3 / 59.2% on three datasets | Needs labelled same-distribution data; single-turn |
| 2 | Hybrid LLM | Ding et al. (Microsoft, UBC) | 22 Apr 2024 | https://arxiv.org/abs/2404.14618 | PR (ICLR 2024) | F | 40% fewer large-model calls with 0.0-0.2% drop, small-gap pair only | 10-14% drop for large gap; near-random routers |
| 3 | RouteLLM | Ong et al. (Berkeley, Anyscale) | 26 Jun 2024, v4 Feb 2025 | https://arxiv.org/abs/2406.18665 | PP | F | 3.66x on MT Bench; random-level on MMLU/GSM8K without augmentation | Two models; needs in-domain data |
| 4 | AutoMix | Aggarwal, Madaan et al. | 19 Oct 2023, v5 Jan 2025 | https://arxiv.org/abs/2310.12963 | PR (NeurIPS 2024) | F | Over 50% cost reduction; trainable on 50 examples | Context-grounded tasks only; noisy verifier |
| 5 | RouterBench | Hu et al. (Martian, Berkeley) | 18 Mar 2024 | https://arxiv.org/abs/2403.12031 | PP | F | No router significantly beats the Zero router; oracle rarely picks GPT-4 | Simulated cascades; 2024 models |
| 6 | A Unified Approach to Routing and Cascading for LLMs | Dekoninck, Baader, Vechev (ETH) | 14 Oct 2024, v5 Oct 2026 | https://arxiv.org/abs/2410.10347 | PP | F | Quality estimators are the critical factor; routing = linear interpolation on SWE-Bench | Simulated noise; ground-truth post-hoc signal |
| 7 | MixLLM | Wang et al. (NEC Labs) | 9 Feb 2025 | https://arxiv.org/abs/2502.18482 | PR (NAACL 2025) | A | 97.25% of GPT-4 quality at 24.18% of cost | Abstract only |
| 8 | GraphRouter | Feng, Shen, You (UIUC) | 4 Oct 2024 | https://arxiv.org/abs/2410.03834 | PP | A | At least 12.3% over prior routers | Below kNN in RouterArena |
| 9 | RouterArena | Lu et al. (Rice) | v3 27 Nov 2025 | https://arxiv.org/abs/2510.00202 | PP (ICLR 2026 per listing, venue NV) | F | No router dominates; table of 12 routers; robustness low | One dataset of about 8,400 queries |
| 10 | Cost-of-Pass | Erol et al. (Stanford) | 17 Apr 2025, v2 Feb 2026 | https://arxiv.org/abs/2504.13359 | PP | A | Tier best-suited differs by task type; marginal inference-time techniques rarely pay | Abstract only |
| 11 | Dynamic Model Routing and Cascading: A Survey | Moslem, Kelleher | 23 Feb 2026 | https://arxiv.org/abs/2603.04445 | PR (TMLR 2026 per arXiv) | A | Generalisation is the open challenge | Abstract only |
| 12 | Doing More with Less (survey) | Varangot-Reille et al. | v3 21 Jul 2025 | https://arxiv.org/abs/2502.00409 | PP | F | Routers are static; no standard evaluation; overconfident verbalised confidence | Pre-2026 |
| 13 | Rethinking Predictive Modeling for LLM Routing (kNN) | Yang Li | 19 May 2025 | https://arxiv.org/abs/2505.12601 | PP | F | kNN within a point of learned routers on utility AUC | Title overstates; single author |
| 14 | Large Language Model Routing with Benchmark Datasets | Shnitzer et al. (IBM, MIT) | 27 Sep 2023 | https://arxiv.org/abs/2309.15789 | PP | F | Router 0.694 vs best-average model 0.688; OOD is the bottleneck | 2023 models |
| 15 | Rerouting LLM Routers | Shafran, Schuster, Ristenpart, Shmatikov | 3 Jan 2025 | https://arxiv.org/abs/2501.01818 | PP | F | Confounder gadgets: up to 100% upgrade rate; over 8x cost on one commercial router | Per-query routers only |
| 16 | LLMRouterBench | Li et al. (Shanghai AI Lab) | 12 Jan 2026 | https://arxiv.org/abs/2601.07206 | PP | F | Several routers below Best Single; OpenRouter -24.7% | No long-context or agent tasks |
| 17 | The Routing Plateau | Lu et al. (Rice) | 27 May 2026, v2 Sep 2026 | https://arxiv.org/abs/2606.07587 | PP | F | Top 15 routers within 0.23 pp; 10-30 pp below oracle; 10x data adds 1.24 pp | Per-query |
| 18 | Most of the LLM Routing Gap Is Task Type | Janghoon Lee | 24 Aug 2026 | https://arxiv.org/abs/2608.23023 | PP | A | Static task-type table gets 21 of 29 improvable questions | 294 questions, no holdout, single author |
| 19 | Opportunity Is Not Realizability | Shihab et al. | 8 Aug 2026 | https://arxiv.org/abs/2608.08265 | PP | A | Best prompt router recovers 7.5-14.4% of oracle gap | Abstract only |
| 20 | When LLM Routers Overpay | Lai, Chen, Ye | 3 Feb 2026 | https://arxiv.org/abs/2602.03478 | PR (NeurIPS 2026 per arXiv) | A | Routers over-select expensive models under loose budgets | Abstract only |
| 21 | Embedding Geometry Shapes LLM Routing | Torti et al. (MIT) | 13 Oct 2026 | https://arxiv.org/abs/2610.19198 | PP | A | Semantic-embedding routers struggle on unseen tasks | Abstract only |
| 22 | xRouter | Qian et al. (Salesforce) | 9 Oct 2025 | https://arxiv.org/abs/2510.08439 | PP | F | Near-GPT-5 accuracy at about one-tenth cost on math; converges to simple patterns | Router is an LLM; non-agentic tasks |
| 23 | Router-R1 | Zhang, Feng, You | 10 Jun 2025 | https://arxiv.org/abs/2506.09033 | PR (NeurIPS 2025) | A | LLM router with multi-round routing on QA | No numbers in abstract |
| 24 | TREACLE | Zhang et al. | 17 Apr 2024 | https://arxiv.org/abs/2404.13082 | PP | A | Up to 85% savings on GSM8K, CSQA, LLC | Non-agentic |
| 25 | PILOT: Adaptive LLM Routing under Budget Constraints | Panda et al. (Fujitsu) | v2 9 Sep 2025 | https://arxiv.org/abs/2508.21141 | PP (EMNLP Findings per listing, venue NV) | F | 93% of GPT-4 at 25% cost; about 32k online samples; small edge over LinUCB | Single-turn |
| 26 | MetaLLM | Nguyen et al. | 15 Jul 2024 | https://arxiv.org/abs/2407.10834 | PP | A | Bandit routing for classification and MCQ | No numbers in abstract |
| 27 | LLM Bandit | Yang Li | 4 Feb 2025 | https://arxiv.org/abs/2502.02743 | PP | A | Preference-conditioned bandit routing | No numbers in abstract |
| 28 | When Does Confidence-Based Cascade Deferral Suffice? | Jitkrittum et al. (Google) | 6 Jul 2023 | https://arxiv.org/abs/2307.02764 | PR (NeurIPS 2023) | A | Thresholding often suffices; learned deferral helps under shift, noise, specialists | Classification cascades |
| 29 | Language Model Cascades: Token-level uncertainty and beyond | Gupta et al. (Google) | 15 Apr 2024 | https://arxiv.org/abs/2404.10136 | PP | A | Sequence confidence has length bias; learned token-level rules help | Needs logits |
| 30 | ShadowPrefill | Qiu, Mahapatra, Fonseca, Russinovich (Microsoft) | 9 Nov 2026 | https://arxiv.org/abs/2611.13176 | PP | F | Switch calls: 44-65% cache hit vs 80-89%; SWE-bench router 32% vs always-large 42% | Mostly simulation; 50 tasks |
| 31 | The Handoff Tax | Ganz et al. | 25 Aug 2026 | https://arxiv.org/abs/2608.24358 | PP | F | Escalation recovers under half the gap; dominated by restart on Claude pair | Two pairs; fixed switch points |
| 32 | TwinRouterBench | Yang, Chen, Shi et al. | v5 Oct 2026 | https://arxiv.org/abs/2605.18859 | PP | F | 71% of steps low-tier-sufficient; every router negative savings on SWE slice; trained router 53% cheaper on 100 instances | Small live track; router fit on benchmark labels |
| 33 | SWE-Router | Son et al. (UCL) | 30 Jun 2026 | https://arxiv.org/abs/2607.00053 | PP | F | Prompt-only routers near useless; trajectory-conditioned Route-AUC 0.78 | Task-level, restarts instead of handing off |
| 34 | AgentRouter | Paul, Nandy | 19 Sep 2026 | https://arxiv.org/abs/2609.22951 | Workshop (AgenticUQ, ICML 2026) | F | 71.8% saving at 97.3% quality; 14.2% of steps need frontier and hold 48.3% of cost | Own benchmark; GPT-4o as frontier; steps known up front; no cache accounting found |
| 35 | TurnCost | Kumar, Pandey | 10 Oct 2026 | https://arxiv.org/abs/2610.15093 | PP | A | 98.6% of input tokens cached; delegation raised cost in half of settings; turns explain 84% of cost variance | Abstract only; re-scoring study |
| 36 | How Do AI Agents Spend Your Money? | Bai et al. (Stanford, OpenHands) | 24 Apr 2026, v3 Oct 2026 | https://arxiv.org/abs/2604.22750 | PP (NeurIPS 2026 per listing, venue NV) | A | Input tokens drive cost; 30x run variance; accuracy peaks at intermediate cost | Abstract only |
| 37 | SWE-Protégé | Kon et al. | 25 Feb 2026 | https://arxiv.org/abs/2602.22124 | PP | A | 7B model with learned expert calls: 42.4% SWE-bench Verified, expert about 11% of tokens | Requires fine-tuning the small model |
| 38 | TACIT-Switch | Lei, Huang | 28 Aug 2026 | https://arxiv.org/abs/2608.27911 | PP | A | Learned permanent handoff beats step-level routing baselines in simulation | No always-strong baseline in abstract |
| 39 | New Model, Old Habits | Choi et al. | 14 Oct 2026 | https://arxiv.org/abs/2610.19712 | PP | A | Behaviour transfer across model swaps; summarisation reduces it | No numbers in abstract |
| 40 | Evaluating Performance Drift from Model Switching | Khraishi et al. | 3 Mar 2026 | https://arxiv.org/abs/2603.03111 | PP | A | One switch: -8 to +13 points on Multi-IF | Not agentic |
| 41 | Small Language Models are the Future of Agentic AI | Belcak et al. (NVIDIA) | 2 Jun 2025, v3 Sep 2026 | https://arxiv.org/abs/2506.02153 | PP (position) | F (v2) | 40-70% of calls replaceable (author estimates) | No experiments |
| 42 | Efficient Agents | Wang et al. (OPPO) | 24 Jul 2025 | https://arxiv.org/abs/2508.02694 | PP | F | 96.7% of OWL performance, cost-of-pass -28.4% | GAIA only; no mixed-model test; inconsistent tables |
| 43 | BudgetMLAgent | Gandhi et al. (TCS) | 12 Nov 2024 | https://arxiv.org/abs/2411.07464 | PR (AIMLSystems 2024) | A | Cost $0.931 to $0.054, success 22.72% to 32.95% | 2024 models; abstract only |
| 44 | MasRouter | Yue et al. | 16 Feb 2025 | https://arxiv.org/abs/2502.11133 | PP | A | Up to 52.07% lower overhead on HumanEval | Non-agentic code benchmarks |
| 45 | Holistic Agent Leaderboard | Kapoor, Stroebl et al. (Princeton) | 13 Oct 2025 | https://arxiv.org/abs/2510.11977 | PP | F | Most costly model on Pareto frontier in 1 of 9 benchmarks; more effort not better in 21 of 36 | Task-level model choice |
| 46 | AI Agents That Matter | Kapoor et al. (Princeton) | 1 Jul 2024 | https://arxiv.org/abs/2407.01502 | PP | F | Simple baselines and escalation are Pareto-competitive; 41-53% lower cost via joint optimisation | HumanEval, HotPotQA |
| 47 | Agent S2 | Agashe et al. (Simular) | 1 Apr 2025 | https://arxiv.org/abs/2504.00906 | PP | A | Generalist/specialist role split improves OSWorld | Accuracy-motivated workflow, not routing |
| 48 | The Illusion of Diminishing Returns | Sinha et al. | 11 Sep 2025, v3 Mar 2026 | https://arxiv.org/abs/2509.09677 | PR (ICLR 2026) | A | Per-step errors compound; self-conditioning; thinking mitigates | Synthetic execution task |
| 49 | Separating code reasoning and editing (architect mode) | Aider | 26 Sep 2024 | https://aider.chat/2024/09/26/architect.html | VB | F | 85.0% paired vs 79.7% solo | Own benchmark; gains also with same model twice |
| 50 | The advisor strategy | Anthropic | 9 Apr 2026 | https://claude.com/blog/the-advisor-strategy | VB | F | +2.7 points, -11.9% cost (Sonnet + Opus advisor) | Vendor evals; unequal arms |
| 51 | Escalate hard decisions with the advisor tool | Anthropic (Claude Code docs) | read 2026-11-20 | https://code.claude.com/docs/en/advisor | OD | F | Advisor reads are uncached; timing is model-driven | Experimental |
| 52 | Model configuration (opusplan, effort) | Anthropic (Claude Code docs) | read 2026-11-20 | https://code.claude.com/docs/en/model-config | OD | F | Opus plans, Sonnet executes | - |
| 53 | How Claude Code uses prompt caching | Anthropic (Claude Code docs) | read 2026-11-20 | https://code.claude.com/docs/en/prompt-caching | OD | F | "Each model has its own cache" | - |
| 54 | Lessons from building Claude Code: Prompt caching is everything | Thariq Shihipar, Anthropic | 30 Apr 2026 | https://claude.dev/blog/lessons-from-building-claude-code-prompt-caching-is-everything/ | VB (engineering) | F | Switching to Haiku at 100k tokens costs more than staying on Opus | Qualitative |
| 55 | Pricing; Prompt caching; Effort | Anthropic | read 2026-11-20 | https://platform.claude.com/docs/en/about-claude/pricing ; https://platform.claude.com/docs/en/build-with-claude/prompt-caching ; https://platform.claude.com/docs/en/build-with-claude/effort | OD | F | Price tables; 1.25x/2x write, 0.025-0.1x read; per-message effort keeps cache | List prices |
| 56 | API pricing; Prompt caching; Reasoning | OpenAI | read 2026-11-20 | https://developers.openai.com/api/docs/pricing ; https://developers.openai.com/api/docs/guides/prompt-caching ; https://developers.openai.com/api/docs/guides/reasoning | OD | F | Price tables; cache write premium on GPT-5.6+; effort levels | List prices |
| 57 | Gemini API pricing; Caching; Thinking | Google | read 2026-11-20 | https://aistudio.google.com/docs/pricing ; https://aistudio.google.com/docs/caching ; https://aistudio.google.com/docs/thinking | OD | F | Price tables with scheduled doublings; implicit caching; thinking levels | Page truncated at 100k characters |
| 58 | What is model router; How model router works | Microsoft | 18 Nov 2026 | https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/model-router ; https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/model-router-how-it-works | OD | F | Per-request routing across 45 models; adaptive session affinity for cache | No savings data; routing fee not verified |
| 59 | Intelligent prompt routing | AWS | read 2026-11-20 | https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-routing.html ; https://aws.amazon.com/bedrock/intelligent-prompt-routing/ | OD + VB | F | Two models, one family; "up to 30%" | Marketing figure; English only |
| 60 | GPT-5 system card | OpenAI | Aug 2025 | https://openai.com/index/gpt-5-system-card | OD | F | Real-time router description | - |
| 61 | OpenAI defaults free users to cheapest model | Gizmodo | 16 Dec 2025 | https://gizmodo.com/openai-defaults-free-users-to-cheapest-model-to-cut-back-on-costs-2000700346 | NEWS | S | Router removed for Free and Go users | Secondary |
| 62 | Cursor Router docs; How Cursor Router works | Cursor | docs read 2026-11-20; blog 6 Aug 2026 | https://cursor.com/docs/cursor-router ; https://cursor.com/blog/how-cursor-router-works | OD + VB | F | Per-turn classifier; 41-68% lower cost on satisfaction proxy | Vendor claim; proxy metric |
| 63 | Auto model selection | GitHub | read 2026-11-20 | https://docs.github.com/en/copilot/concepts/auto-model-selection | OD | F | Routes at natural cache boundaries; 10% discount | No data |
| 64 | Auto Router | OpenRouter | read 2026-11-20 | https://openrouter.ai/docs/features/model-routing | OD | F | Avoids switching because of cache rebuild cost | No data |
| 65 | Amp tools (oracle) | Sourcegraph Amp | read 2026-11-20 | https://ampcode.com/docs/tools | OD | F (limited) | Oracle is a reviewing subagent | Model tier not stated |
| 66 | Don't Break the Cache | Lumer et al. (PwC) | v2 31 Jan 2026 | https://arxiv.org/abs/2601.06007 | PP | F | Caching saves 41-80% in agent sessions | One benchmark; no switching |
| 67 | Welcome to LLMflation | Appenzeller (a16z) | 12 Nov 2024 | https://a16z.com/llmflation-llm-inference-cost/ | NB | F | 10x per year at constant capability | MMLU-based |
| 68 | LLM inference prices have fallen rapidly but unequally across tasks | Cottier et al. (Epoch AI) | 12 Mar 2025 | https://epoch.ai/data-insights/ai-inference-price-trends | NB | F | 9x to 900x per year | Truncated page |
| 69 | The plunging price of thought | Emberson, Roodman (Epoch AI) | 22 Sep 2026 | https://epoch.ai/publications/the-plunging-price-of-thought | NB | F | 47% per quarter, 13x per year | Assumes cheapest-sufficient model choice |
| 70 | Inference Scaling fLaws / The Limits of Inference Scaling Through Resampling | Stroebl, Kapoor, Narayanan | 26 Nov 2024, v3 Mar 2026 | https://arxiv.org/abs/2411.17501 | PP | A | Weak models cannot resample their way to a strong model with an imperfect verifier | HumanEval, MBPP |
| 71 | Adaptive-Consistency | Aggarwal et al. | 19 May 2023 | https://arxiv.org/abs/2305.11860 | PR (EMNLP 2023) | A | Up to 7.9x fewer samples, under 0.1% accuracy drop | Non-agentic |
| 72 | Learning How Hard to Think | Damani et al. (MIT) | 7 Oct 2024 | https://arxiv.org/abs/2410.04707 | PP | A | Up to 50% less computation at equal quality | Non-agentic |
| 73 | Reasoning on a Budget (survey) | Alomrani et al. (Huawei) | 2 Jul 2025 | https://arxiv.org/abs/2507.02076 | PP | A | Controllable vs adaptive test-time compute taxonomy | Abstract only |

### Not verified, or not found

- Windsurf "auto" or adaptive modes: no primary source opened.
- Amp oracle's underlying model: not stated on the page opened.
- WIRED's reporting that ChatGPT's router reduced engagement: seen only in search summaries.
- Microsoft model router routing fee: the public price page displayed no figure.
- RerouteGuard (arXiv 2601.21380), ParetoBandit (arXiv 2604.00136), Conformal Cascade (arXiv 2607.25018), C3PO, RouteNLP (arXiv 2604.23577), Gatekeeper (arXiv 2502.19335), Cost-Saving LLM Cascades with Early Abstention (arXiv 2502.09054), HM-Router (arXiv 2609.32213), RSI-Router (arXiv 2609.34712), RouterEval (arXiv 2503.10657), "Adaptive Computation in the LLM Era" survey: search summaries only.
- A formal published critique of the NVIDIA small-language-models position paper: none found.
- Venue claims taken from search listings rather than the opened page are marked "venue NV" in the table.
- The price arithmetic in section 3a was produced by the short script reproduced in the appendix at the end of this file. Extracted paper text used for three PDFs was not archived.


---

## Appendix: price arithmetic script (section 3a)

Reviewer arithmetic from list prices read on 2026-11-20. It derives the table in section 3a; it measures nothing.

```python
# Prices per MTok read from official pricing pages on 2026-11-20
M = 1e6
models = {
 "opus55":   dict(inp=4.0,  w=5.0,   r=0.20, out=20.0),
 "fable52":  dict(inp=8.0,  w=10.0,  r=0.20, out=40.0),
 "sonnet55": dict(inp=2.0,  w=2.5,   r=0.10, out=10.0),
 "haiku55_short": dict(inp=0.10, w=0.125, r=0.01, out=0.50),
 "haiku55_long":  dict(inp=0.50, w=0.625, r=0.05, out=2.50),
 "haiku45":  dict(inp=1.0,  w=1.25,  r=0.10, out=5.0),
}
def stay(m, P, n, o):  # warm cache on m
    return (P*m["r"] + n*m["w"] + o*m["out"])/M
def cold(m, P, n, o):  # nothing cached on m
    return ((P+n)*m["w"] + o*m["out"])/M
def warm_other(m, P, n, o, d):  # m has prefix except d tokens
    return ((P-d)*m["r"] + (d+n)*m["w"] + o*m["out"])/M
n, o, d = 1000, 300, 5000
for P in (50_000, 150_000):
    light = "haiku55_short" if P + n <= 100_000 else "haiku55_long"
    print(f"--- prefix {P} tokens, new {n}, out {o}; light={light}")
    for heavy in ("opus55", "fable52", "sonnet55"):
        s = stay(models[heavy], P, n, o)
        c = cold(models[light], P, n, o)
        w = warm_other(models[light], P, n, o, d)
        hc = cold(models[heavy], P, n, o)
        c45 = cold(models["haiku45"], P, n, o)
        print(f"{heavy}: stay_warm=${s:.4f} | light_cold=${c:.4f} ({c/s:.2f}x) | light_warm=${w:.4f} ({w/s:.2f}x) | haiku45_cold=${c45:.4f} ({c45/s:.2f}x) | heavy_cold_rewrite=${hc:.4f} ; rewrite penalty = {(hc-s)/(s-w):.1f} warm-light-step savings")
```
