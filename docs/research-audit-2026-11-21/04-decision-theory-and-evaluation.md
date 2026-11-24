# Decision theory, control and evaluation science for a per-step non-LLM agent controller

> **Status: dated external research note, archived 2026-11-21. Historical (accurate for its date).** Written by an AI research pass for the red-team review in [#94](https://github.com/dgenio/turnwise-decision-lab/issues/94). Research only: no model was called and no experiment was run by this repository. Verification flags are the author's own; the [audit index](README.md) says what was independently re-checked and lists known corrections. Do not rewrite this file; add a dated note instead.

Skeptical literature research for an adversarial review of Turnwise Decision Lab.
Research date: 2026-11-20. Research only; no repository was modified and nothing was posted.

## How to read this report

**Verification legend.** Every source carries one of three labels.

- **V (verified):** I opened the primary document in this session (publisher page, arXiv PDF or author-hosted PDF) and read the passage the claim rests on. Numbers are copied from that text.
- **VI (verified indirectly):** I could not open the original (paywall, HTTP 403, or an unreadable scan). The claim is supported by another primary document I did open, usually by the same author or one that restates the result. The entry says which.
- **NOT VERIFIED:** I found only bibliographic data or a search snippet. Treat it as a lead.

**Other conventions.** Arithmetic that I did myself is labelled "my arithmetic". Synthesis and opinion are labelled as such. "Turnwise" means the hypothesis as described in the task brief and in `AGENTS.md`: a small typed, non-generative policy re-invoked after every unresolved observation chooses the next operation from a closed set; model calls execute nothing and return typed proposals; the host validates, executes, holds writes and checks citations.

**Classification used in Part 1.** For each family: (a) directly applicable prior art that makes Turnwise non-novel, (b) a source of a concretely better design, (c) only an analogy.

---

## Executive summary

1. **The idea is not new in any of its three parts.** "Model proposes, a separate component disposes" is LLM-Modulo (ICML 2024), SayCan (2022), CaMeL/FIDES (2025) and AI Control (2023). "A cheap explicit controller picks the next operation from a closed set" is a classical dialogue manager (Young et al. 2013), the sequencer of a three-layer robot architecture (Gat 1998), and, for LLM agents specifically, ToolGate (June 2026) and Utility-Guided Orchestration (March 2026). "Host owns authority" is Anderson's 1972 reference monitor and the 2025-2026 runtime-enforcement literature (AgentSpec, Progent, Agent-C, AgentLTL).
2. **The closest prior art reports small or negative effects.** Utility-Guided Orchestration uses nearly the same action set (respond, retrieve, tool call, verify, stop). In its own Table I, plain ReAct gets higher F1 (0.2662 vs 0.2360) with fewer tokens (546.6 vs 1294.2) than the explicit policy. ToolGate, a logistic-regression gate on proposed tool calls, reaches 64-69% of baseline token cost at preserved average accuracy, on perception tools only.
3. **Three disciplines predict that the "simple host rules + same capable agent" null is the canonical design.** Simplex (Sha), shielding (Alshiekh et al.) and supervisory control (Ramadge and Wonham) all keep the high-performance controller in charge of performance and give the simple verified component a veto. Turnwise inverts this: the simple component makes the performance-relevant choice. AI Control quantifies what that inversion costs: usefulness falls monotonically as more decisions are deferred to the weak trusted component (93% at 10% deferral, 51% at 50%, 2% with the trusted model alone).
4. **Rational metareasoning says a rule table is the wrong object.** The choice "answer now, call a tool, or call a bigger model" is a value-of-computation problem. Russell's own 1997 survey describes rule-based metalevel control as the pre-rational stage of the field. The usable versions (Callaway et al. 2018; De Sabbata et al. 2024) learn the value of computation from data.
5. **The current evidence cannot support any quality, cost or safety claim.** 46 paired turns can detect only a difference of roughly 18 points at 80% power under a favourable assumption (my arithmetic), and zero failures in 46 trials still leaves a 95% upper bound of 6.3% on the failure rate (my arithmetic). Simulated model replies add no sampling variation at all. Bowyer et al. (2025) show that standard error bars are too narrow at this scale.
6. **A credible test needs roughly 500-650 paired tasks for a 5-point non-inferiority margin**, real model calls, at least five arms including the three nulls, repeated trials per task, a public host benchmark, and a pre-declared margin. The best available host is the τ-bench family (retail and airline, at a pinned corrected version), with AgentDojo as the second host for the write-gating and injection claims. Both have documented defects that must be controlled for, including a do-nothing agent that passes 38% of τ-bench airline tasks.

---

# Part 1 - Decision-making, control theory and cross-disciplinary ideas

## 1.1 Metareasoning and the value of computation

### Sources

| ID | Source | Finding (numbers as stated) | Limitations | Relevance |
|---|---|---|---|---|
| M1 | Russell, S. and Wefald, E. "Principles of metareasoning." *Artificial Intelligence* 49(1-3):361-395, 1991. Peer-reviewed. DOI 10.1016/0004-3702(91)90015-C. **VI** (paywalled; content checked through M2, M4, M6) | Computations are actions; a computation is worth doing when its expected improvement in the eventual decision exceeds its cost. | Full text not opened. | Founding statement of the problem Turnwise poses. |
| M2 | Russell, S. "Metareasoning" (draft MIT Encyclopedia of the Cognitive Sciences entry), 21 Nov 1997. Author-hosted. https://aima.eecs.berkeley.edu/~russell/papers/mitecs-metareasoning.pdf **V** | Early metalevel systems applied hand-written IF-THEN rules encoding the designer's expertise, with "no standard of rationality". Rational metareasoning values a computation by expected improvement in decision quality minus delay. Worked example: with estimates A = 10 (sd 1) and B = 8 (sd 4), value of lookahead is 0.3 from A and 0.82 from B; if A's estimate were 12 the values drop to 0.002 and 0.06; if both are 10 with sd 0.1 the value is 0.03. (The entry flags these example figures with an editorial "[[check]]".) | Encyclopedia entry, not an experiment; example numbers flagged as unchecked by the author. | A rule-based `TriagePolicy` is the pre-1989 design. The example shows the value of a tool or heavy call depends on whether it could change the decision. |
| M3 | Horvitz, E. "Reasoning About Beliefs and Actions Under Computational Resource Constraints." 1987, arXiv reprint 1304.2759. https://arxiv.org/abs/1304.2759 **V** (venue label not checked) | Argues for weighing expected costs and benefits of approximation procedures, and for "real-time rationality": balance the benefit of more computation against the cost of acting on a partial result. | Conceptual paper. | Same framing, from the decision-analytic side. |
| M4 | Hay, N., Russell, S., Tolpin, D., Shimony, S. E. "Selecting Computations: Theory and Applications." UAI 2012. https://arxiv.org/abs/1207.5879 **V** | Formalises metalevel decisions as Bayesian selection problems rather than bandits. Gives finite sampling bounds for optimal policies in some cases, and a counterexample to the conjecture that an optimal policy always reaches a decision. States that the myopic (one-step) policy tends to stop too early. | Monte Carlo selection and Go, not language agents. | One-step rules such as "answer if confident" inherit the stop-too-early bias. |
| M5 | Lieder, F. and Griffiths, T. L. "Resource-rational analysis." *Behavioral and Brain Sciences* 43:e1, 2020. Peer-reviewed. https://cocosci.princeton.edu/papers/lieder_resource.pdf **V** | Proposes the rational use of limited computational resources as a unifying modelling principle. | Cognitive science; no agent experiments. | Supplies the normative standard: a controller should be judged against the best policy available under its resource limits. |
| M6 | De Sabbata, C. N., Sumers, T. R., AlKhamissi, B., Bosselut, A., Griffiths, T. L. "Rational Metareasoning for Large Language Models." arXiv 2410.05563, Oct 2024 (v3 June 2025). Preprint. https://arxiv.org/abs/2410.05563 **V** | Defines VOC(c, b) as expected gain in best-action utility minus cost(c); the agent should stop when no computation has positive VOC. Trains the LLM itself with a VOC-inspired reward via Expert Iteration. 20-37% fewer generated tokens across three models at maintained task performance, against few-shot chain-of-thought and STaR. | Reasoning length only, not tools or model choice. Fine-tunes the model. | The metareasoning is internalised in the model. This is the competing design to an external controller. |
| M7 | Callaway, F., Gul, S., Krueger, P., Griffiths, T. L., Lieder, F. "Learning to select computations." arXiv 1711.06892, 2018. https://arxiv.org/abs/1711.06892 **V** (abstract) | Optimal computation selection is intractable. Bayesian metalevel policy search learns a metalevel policy using the insight that the value of information lies between the myopic value of information and the value of perfect information. | Evaluated on small metareasoning problems. | A blueprint for a small learned controller: a few VOC features with learned weights. |
| M8 | Liu, A. et al. "ToolGate: Token-Efficient Pre-Call Control for Tool-Augmented Vision-Language Agents." arXiv 2606.03054, 2 June 2026. Preprint. https://arxiv.org/abs/2606.03054 **V** | After a ReAct-style agent proposes a tool call, a lightweight external controller (L2-regularised logistic regression over trajectory text and simple structural features) decides execute or skip. Baseline helpful and harmful calls occur at similar rates (11.8% vs 9.9%). Token cost falls to 64-69% of unrestricted ReAct at preserved average accuracy across two Qwen3-VL backbones; +1.65 points with in-domain training on the 30B model. | Perceptual tools in vision-language tasks. Skip-or-execute only. | Direct prior art for "proposal returns to a small non-LLM policy". |
| M9 | Liu, B. et al. "Utility-Guided Orchestration for Cost-Efficient Tool-Augmented LLM Services." arXiv 2603.19896 (v2 13 Sep 2026). Preprint. https://arxiv.org/abs/2603.19896 **V** | Models agent control as a cost-aware sequential decision over a compact action space: respond, retrieve, tool call, verify, stop. A utility function combines expected gain, step cost, uncertainty and redundancy. Table I (200 HotpotQA dev examples): ReAct F1 0.2662 at 546.6 tokens; policy (step-cost) F1 0.2360 at 1294.2 tokens. The headline "up to 10.6%" token reduction is the policy with semantic redundancy control versus the same policy without it (1294.2 to 1156.6 tokens). The authors present it as an inspectable control layer, not an accuracy optimiser. | One dataset, n = 200, one locally served model, BM25 retriever. Gain and uncertainty are clipped LLM self-estimates, so the controller still spends model calls. | The closest prior art found. Its own table shows the explicit controller dominated by ReAct on both axes. |
| M10 | Wu, Q. et al. "To Call or Not to Call: A Framework to Assess and Optimize LLM Tool Calling." arXiv 2605.00737 (v3 6 Aug 2026). Preprint. https://arxiv.org/abs/2605.00737 **V** (abstract and introduction) | Frames tool calls by necessity, utility and affordability. With a web-search tool on factual questions, four of seven evaluated models make redundant calls and perform worse. | Abstract-level reading. | Evidence that tool-call decisions by models are not principled, which is the gap Turnwise targets. |
| M11 | Fang, Z. et al. "Inference-Time Budget Control for LLM Search Agents." arXiv 2605.05701, May 2026. Preprint. https://arxiv.org/abs/2605.05701 **V** (abstract) | A controller assigns each feasible action a value-of-information score per unit budget and chooses among retrieval, decomposition and answer commitment. Positive aggregate gains over four audited baselines across four multi-hop QA benchmarks, three backbones and four budget levels. | Abstract-level reading; no effect sizes extracted. | Value-of-information control under hard budgets already exists for search agents. |
| M12 | Dong, Y. R. et al. "Value of Information: A Framework for Human-Agent Communication." arXiv 2601.06407, Jan 2026. Preprint. https://arxiv.org/abs/2601.06407 **V** (abstract) | Decides ask-versus-act by expected utility gain against user cognitive cost, with no threshold tuning. Matches or exceeds the best manually tuned baselines in four domains, up to 1.36 utility points higher in high-cost settings. | Abstract-level reading. | Decision-theoretic treatment of the CLARIFY operation. |

### What it implies

**Is anyone treating the choice as a value-of-computation problem?** Yes, in three separate strands: reasoning length (M6), tool-call gating (M8, M10, M11) and clarification (M12). I did not find a paper that applies an explicit value-of-computation policy to the "call a bigger model" step inside an agent loop; that step sits in the model-routing literature, which the companion report on model routing covers ([02-model-routing.md](02-model-routing.md)).

**Design consequences.**

1. A policy that chooses among computations needs, for each candidate, an estimate of the probability that it changes the final decision and an estimate of its cost. A rule table has neither. M2's example makes the point: computation is worthless when the choice would not change.
2. One-step lookahead stops too early (M4). A rule such as "answer directly when the query looks simple" is a myopic stopping rule.
3. The metalevel must be far cheaper than the object level. Rules meet this. M9 does not, because its signals come from extra LLM calls, and that is the most likely reason it loses to ReAct on tokens.
4. The workable approach is a learned approximation of value of computation from a few features (M7), trained on counterfactual labels: for the same state, what happened with and without the call. ToolGate (M8) is exactly this for one decision type.

**Classification.** (a) and (b). The framing and the mechanism both exist. The better design is a learned, calibrated gate per decision type, not a hand-written policy over all types.

---

## 1.2 MDPs, POMDPs, options, dialogue managers and learning a controller from trajectories

### Sources

| ID | Source | Finding | Limitations | Relevance |
|---|---|---|---|---|
| P1 | Sutton, R. S., Precup, D., Singh, S. "Between MDPs and semi-MDPs: A framework for temporal abstraction in reinforcement learning." *Artificial Intelligence* 112:181-211, 1999. Peer-reviewed. http://incompleteideas.net/papers/SPS-aij.pdf **V** | Options are closed-loop policies over a period of time and can be used interchangeably with primitive actions. Theorem 2 (Interruption): re-evaluating at each step and terminating an option whenever Q(s, o) < V(s) yields a policy no worse than committing to the option. | Assumes a known MDP and a correct option-value function. No cost of re-deciding. | A native agent segment is an option. The theorem supports re-deciding each step only when the controller has reliable values. |
| P2 | Harb, J., Bacon, P.-L., Klissarov, M., Precup, D. "When Waiting is not an Option: Learning Options with a Deliberation Cost." arXiv 1709.04571, 2017. https://arxiv.org/abs/1709.04571 **V** (final venue not checked) | From the standpoint of absolute optimality, temporal abstraction is unnecessary; the optimal policy is achieved by primitive actions. Options are justified by bounded rationality: deliberation has a cost. Learns options with an explicit deliberation cost. | Atari experiments. | The case for per-step control and the case against it are the same equation with a different deliberation cost. |
| P4 | Young, S., Gašić, M., Thomson, B., Williams, J. D. "POMDP-based Statistical Spoken Dialogue Systems: a Review." *Proceedings of the IEEE* 101(5):1160-1179, 2013. Peer-reviewed. Author copy: https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/young2013procieee.pdf **V** | Conventional dialogue policies were flowcharts; such systems are "expensive to build and often fragile". POMDPs add an explicit belief state and a reward-optimised policy. Exact optimisation is intractable, so practical systems map belief to a compressed "summary space" with a small action set. Training needs user simulators because real users are scarce. | Speech-era systems with recognition error rates of 15-30%. | Turnwise's policy is a dialogue manager. The field's history is a move away from hand-crafted policies. |
| P5 | Sumers, T. R., Yao, S., Narasimhan, K., Griffiths, T. L. "Cognitive Architectures for Language Agents" (CoALA). TMLR, Feb 2024. https://arxiv.org/abs/2309.02427 **V** | Structures agents as memory, action space and a decision procedure. Each decision cycle has a planning stage (proposal, evaluation, selection) and an execution stage. Selection may reject all proposals and loop back. | Conceptual framework and survey. | Turnwise is one point in this taxonomy: proposal by the model, selection by code. |
| P6 | Takanobu, R. et al. "Is Your Goal-Oriented Dialog Model Performing Really Well? Empirical Analysis of System-wise Evaluation." arXiv 2005.07362, May 2020. https://arxiv.org/abs/2005.07362 **V** (final venue not checked) | A pipeline dialogue system trained with component-level supervision often beats joint and end-to-end models. Component-wise single-turn results are not always consistent with whole-system performance. Simulated evaluation correlates moderately with human evaluation (coefficient around 0.5 to 0.6). | Pre-LLM models on MultiWOZ. | The one pro-modular data point, and a warning that single-turn component scores mislead. |
| P7 | Hudeček, V. and Dušek, O. "Are Large Language Models All You Need for Task-Oriented Dialogue?" arXiv 2304.06556, 2023. https://arxiv.org/abs/2304.06556 **V** (abstract) | In explicit belief-state tracking, LLMs underperform specialised task-specific models, yet can steer dialogues to successful endings when given correct slot values. | 2023 models. | Explicit state tracking was still better done outside the LLM at that time. |
| P8 | Levine, S., Kumar, A., Tucker, G., Fu, J. "Offline Reinforcement Learning: Tutorial, Review, and Perspectives on Open Problems." arXiv 2005.01643, 2020. https://arxiv.org/abs/2005.01643 **V** | Names distributional shift as the fundamental challenge of learning from logged data: the learned policy visits states and takes actions the log does not cover. | Tutorial. | A controller trained on native-agent traces will meet states of its own making. |
| P9 | Ross, S., Gordon, G. J., Bagnell, J. A. "A Reduction of Imitation Learning and Structured Prediction to No-Regret Online Learning" (DAgger). arXiv 1011.0686, 2011. https://arxiv.org/abs/1011.0686 **V** | Behaviour cloning with per-step error ε can incur cost growing as T²ε over T steps because errors compound; iterative data aggregation under the learner's own state distribution removes the quadratic term. | Theory plus two imitation tasks. | A per-step classifier's small error rate compounds over a trajectory. |

### What it implies

**The options view gives a precise statement of the hypothesis.** A native agent loop is an option. `HANDOFF_AGENT` is selecting an option and committing to it. Turnwise Core forces termination after every step. Theorem 2 of P1 says forced re-evaluation is no worse, but only with a correct value function and free re-decision. P2 says the reason to commit to an option at all is that deliberation costs something. In an LLM system the cost of re-entering per step is not the policy's microseconds. It is the loss of the model's multi-step context and plan, plus any re-sent context tokens. The hypothesis therefore reduces to an empirical question about that cost, which a synthetic world with simulated replies cannot measure.

**The dialogue-systems history is the closest precedent.** A closed set of system acts chosen by a policy over tracked state is the classical pipeline. The field found hand-written policies fragile (P4), replaced them with learned policies over compressed state, and then largely replaced the pipeline with end-to-end models. P6 shows the pipeline still won on system-level success in 2020. No source I found settles the question for 2026 models.

**Learning the controller.** If the policy becomes a classifier trained on logged trajectories, P8 and P9 apply directly: train on states the controller itself induces, and expect per-step error to compound.

**Classification.** (a) for the framing (CoALA and dialogue managers already describe it). (b) for design: a summary-state policy trained with on-policy data, and an interruption rule based on estimated advantage in place of unconditional per-step termination.

---

## 1.3 Selective prediction, abstention, deferral, conformal methods and clarification

### Sources

| ID | Source | Finding | Limitations | Relevance |
|---|---|---|---|---|
| U1 | Chow, C. K. "On optimum recognition error and reject tradeoff." *IEEE Trans. Information Theory* 16(1), 1970. **NOT VERIFIED** (publisher page returned empty). Geifman and El-Yaniv (U2) cite Chow's earlier 1957 paper on the reject option. | Reject option: abstain when confidence is below a threshold, trading error against rejection rate. | Not opened. | Origin of the HOLD/abstain idea. |
| U2 | Geifman, Y. and El-Yaniv, R. "Selective Classification for Deep Neural Networks." arXiv 1705.08500, June 2017. https://arxiv.org/abs/1705.08500 **V** | Builds a selective classifier from a trained network so the user sets a target risk and the classifier rejects as needed to guarantee it with high probability. Example: 2% top-5 ImageNet error guaranteed with probability 99.9% at almost 60% coverage. | Image classification, i.i.d. data. | Guarantees are stated as risk at a coverage level, calibrated on held-out data. |
| U3 | Madras, D., Pitassi, T., Zemel, R. "Predict Responsibly: Improving Fairness and Accuracy by Learning to Defer." arXiv 1711.06664, 2018. https://arxiv.org/abs/1711.06664 **V** (abstract) | Learning to defer generalises rejection learning by modelling the downstream decision-maker; deferring models improve accuracy and fairness even with inconsistent or biased downstream deciders. | Tabular tasks. | Escalation to a heavy model is deferral to an imperfect expert. |
| U4 | Mozannar, H. and Sontag, D. "Consistent Estimators for Learning to Defer to an Expert." arXiv 2006.01862, 2020. https://arxiv.org/abs/2006.01862 **V** (abstract) | Learns a classifier and a rejector jointly through a reduction to cost-sensitive learning, with a consistent surrogate loss generalising cross-entropy. | Classification. | The rejector must be trained against the expert's actual accuracy, not set by hand. |
| U5 | Ren, A. Z. et al. "Robots That Ask For Help: Uncertainty Alignment for Large Language Model Planners" (KnowNo). CoRL 2023 (oral). https://arxiv.org/abs/2307.01928 **V** | Uses conformal prediction over multiple-choice next actions; the robot acts if the prediction set is a singleton and asks for help otherwise. Guarantee: with user-specified level 1 - ε, the task is completed correctly in at least that share of scenarios, holding with probability 1 - δ over the calibration sample (N = 400, δ = 0.01 in the paper). Reduces human help by 10-24% against baselines. Uncalibrated threshold baselines fail to hit the target rate. | Needs i.i.d. calibration scenarios from the deployment distribution. Assumes the environment is fully grounded in text, proposed actions execute successfully, and the human answers faithfully. Multi-step guarantees need sequence-level calibration. | The rigorous version of CLARIFY and HOLD. |
| U6 | Abbasi-Yadkori, Y. et al. "Mitigating LLM Hallucinations via Conformal Abstention." arXiv 2405.01563, May 2024. https://arxiv.org/abs/2405.01563 **V** (abstract) | Abstention procedure with theoretical guarantees on the hallucination rate, using self-consistency scores and conformal calibration; less conservative than log-probability baselines on a long-answer dataset, comparable on TriviaQA. | Closed-book QA. | Abstain-or-answer with a bounded error rate. |
| U7 | Mohri, C. and Hashimoto, T. "Language Models with Conformal Factuality Guarantees." arXiv 2402.10978, 2024. https://arxiv.org/abs/2402.10978 **V** (abstract) | A back-off algorithm that makes outputs less specific until a correctness guarantee holds; 80-90% correctness guarantees while retaining most of the original output. | QA and maths reasoning. | An alternative to the binary FINISH citation check: weaken the claim until it is supported. |
| U8 | Xiong, M. et al. "Can LLMs Express Their Uncertainty? An Empirical Evaluation of Confidence Elicitation in LLMs." ICLR 2024. https://arxiv.org/abs/2306.13063 **V** (abstract) | LLMs are overconfident when verbalising confidence. Calibration and failure prediction improve with capability but remain far from ideal. | 2023 models. | A `needs_evidence` self-report from the model is a weak signal. |
| U9 | Wen, B. et al. "Know Your Limits: A Survey of Abstention in Large Language Models." arXiv 2407.18418 (v3 Feb 2025); and Geng, J. et al. "A Survey of Confidence Estimation and Calibration in Large Language Models." arXiv 2311.08298, 2024. **V** (abstracts only; used for framing, no numbers taken) | Organise abstention by query, model and human-value perspectives; note that generative output spaces make classical calibration hard to apply. | Surveys. | Context. |
| U10 | Zhang, T. et al. "CLAMBER: A Benchmark of Identifying and Clarifying Ambiguous Information Needs in Large Language Models." arXiv 2405.12063, 2024. https://arxiv.org/abs/2405.12063 **V** (abstract) | About 12K items; current LLMs have limited practical utility in identifying and clarifying ambiguous queries. | Abstract-level reading. | A public test for the CLARIFY decision. |
| U11 | Gulati, A. et al. "Ask Early, Ask Late, Ask Right: When Does Clarification Timing Matter for Long-Horizon Agents?" arXiv 2605.07937, 8 May 2026. Preprint. https://arxiv.org/abs/2605.07937 **V** (abstract) | 84 task variants, 6,000+ runs, three benchmarks, four frontier models. Goal clarification loses nearly all value after 10% of execution (pass@3 falls from 0.78 to baseline); input clarification keeps value through roughly 50%. Deferring any clarification past mid-trajectory is worse than never asking. In 300 unscripted sessions no frontier model asks within the optimal window; behaviour ranges from over-asking (52% of sessions) to never asking. | Preprint; forced-injection design. | When to clarify matters as much as whether. |
| E5 | Rabanser et al. 2026 (full record in Part 2) **V** | For agents on τ-bench and GAIA, calibration has improved in recent models, while discrimination (telling likely successes from failures) has not improved on GAIA and worsened in some recent models. | Two benchmarks. | Agent-level confidence does not yet separate success from failure reliably. |

### What it implies

1. **Report risk-coverage curves, not points.** Every HOLD, CLARIFY and escalation is an abstention with a cost. The selective-prediction literature evaluates the whole trade-off curve (U2). A Turnwise result that reports one success number without the abstention rate is uninterpretable.
2. **Hand-set thresholds are the weak baseline.** In KnowNo the uncalibrated threshold methods are the ones that miss the target success rate (U5).
3. **Calibration needs data from the target distribution.** Conformal guarantees require a calibration sample exchangeable with deployment. A self-authored synthetic world supplies no such sample for any real workload.
4. **Model self-reports are poor routing signals** (U8, E5). Turnwise's `needs_evidence` outcome is a self-report.
5. **Clarification has a time profile** (U11). A per-step policy is well placed to exploit that, since it sees the step index. This is one of the few places the literature offers Turnwise a testable advantage.

**Classification.** (b). This family supplies a concretely better design: conformal thresholds per decision type with a stated target risk. It is (a) for the clarify decision, where decision-theoretic controllers already exist (M12).

---

## 1.4 Runtime verification, shielding, Simplex, reference monitors and information-flow control

### Sources

| ID | Source | Finding | Limitations | Relevance |
|---|---|---|---|---|
| R1 | Anderson, J. P. *Computer Security Technology Planning Study*, ESD-TR-73-51 Vol. II, Oct 1972. Technical report. https://csrc.nist.gov/files/pubs/conference/1998/10/08/proceedings-of-the-21st-nissc-1998/final/docs/early-cs-papers/ande72.pdf **V** | A reference validation mechanism must be tamper proof, must always be invoked, and must be small enough to be subject to analysis and tests. | 1972 operating systems. | "The host owns authority" is this concept. |
| R2 | Schneider, F. B. "Enforceable Security Policies." *ACM TISSEC* 3(1), 2000. Peer-reviewed. https://www.cs.cornell.edu/fbs/publications/EnfSecPols.pdf **V** | Mechanisms that work by monitoring execution can enforce only safety properties. Access control is a safety property. Information flow is not a property of single executions, so no execution monitor enforces it exactly. Availability-style requirements are not safety properties either. | Formal result about one mechanism class. | Draws the boundary of what Turnwise's host can ever guarantee. |
| R3 | Alshiekh, M. et al. "Safe Reinforcement Learning via Shielding." arXiv 1708.08611, 2017. https://arxiv.org/abs/1708.08611 **V** | A shield is a reactive system synthesised from a temporal-logic specification. It either supplies the list of safe actions before the learner chooses, or monitors the chosen action and corrects it only when it would violate the specification. | Needs a formal model of the safety-relevant dynamics. | The standard pattern keeps the learner in charge and intervenes minimally. |
| R4 | Sha, L. "Using Simplicity to Control Complexity." *IEEE Software* 18(4):20-28, 2001. DOI 10.1109/MS.2001.936213. **NOT VERIFIED directly** (publisher page empty). Content checked through R5, R6, R7 and a slide summary of the paper. | See R5 and R6. | Original not opened. | The Simplex architecture. |
| R5 | Sha, L. "Integrate Mixed-Criticality Components with Formalized Architectural Patterns" (position paper citing R4 as its basis), 2008. https://www2.ee.washington.edu/research/nsl/aar-cps/LuiSha-20081015223039.pdf **V** | Sorting example: a verified BubbleSort, an unverified ComplexFastSort, a verified checker that confirms the output is a sorted permutation, and a timer. If the fast sort finishes in time and passes the check its answer is used; otherwise BubbleSort runs. The system is correct for any fast-sort component and has a lower bound on performance. In Simplex a complex high-performance controller runs under a simple high-assurance subsystem that monitors whether a command would leave the stability envelope; such commands are rejected, and other commands get the benefit of the doubt. Cites the Boeing 777 normal and secondary controllers. Required properties: protection, timeliness and fault tolerance of the simple component. | Position paper. | Structural analogue, with the roles allocated the opposite way to Turnwise. |
| R6 | Phan, D. T. et al. "Neural Simplex Architecture." arXiv 1908.00528 (v2 Mar 2020); NFM 2020. https://arxiv.org/abs/1908.00528 **V** | Restates classic Simplex: a decision module switches control from an unverified advanced controller to a pre-certified baseline controller. In the traditional approach control then stays with the baseline. NSA adds reverse switching and online retraining of the neural controller. | Continuous control case studies. | Confirms the three-part structure and its known weakness: permanent fallback. |
| R7 | Sha, L. "A Software Architecture for Dependable and Evolvable Industrial Computing Systems." CMU/SEI-95-TR-005, 1995. https://www.sei.cmu.edu/library/a-software-architecture-for-dependable-and-evolvable-industrial-computing-systems/ **V** (abstract page) | Simplex was developed to support safe online upgrade of hardware and software despite errors in new modules. | Abstract only. | Provenance. |
| R8 | Wang, H., Poskitt, C. M., Sun, J. "AgentSpec: Customizable Runtime Enforcement for Safe and Reliable LLM Agents." ICSE 2026. https://arxiv.org/abs/2503.18666 **V** | A DSL of rules with triggers, predicates and enforcement actions. Prevents unsafe executions in over 90% of code-agent cases, eliminates hazardous actions in embodied tasks, 100% compliance in autonomous-vehicle scenarios, millisecond overhead. LLM-generated rules: 95.56% precision and 70.96% recall for embodied agents; 87.26% of risky code identified; 5 of 8 AV scenarios. | Rule coverage is the limit; rules mostly check single calls. | Host-side enforcement on a native agent, published and peer-reviewed. |
| R9 | Debenedetti, E. et al. "Defeating Prompt Injections by Design" (CaMeL). arXiv 2503.18813, Mar 2025 (v2 June 2025). Preprint. https://arxiv.org/abs/2503.18813 **V** | A privileged LLM writes a program from the trusted user query; a quarantined LLM with no tool access parses untrusted data; a custom interpreter tracks data provenance and enforces capability policies at tool calls. 77% of AgentDojo tasks solved with provable security against 84% undefended. Median 2.82x input and 2.73x output tokens versus native tool calling. Notes that protecting control flow alone is insufficient because injected data can still shape tool-call arguments. Does not defend against text-to-text attacks with no data-flow consequence. | Token overhead; requires policies; some tasks need user clarification. | "Model calls execute nothing" plus "intent from user text only" is the CaMeL pattern, with data-flow tracking that Turnwise lacks. |
| R10 | Costa, M. et al. "Securing AI Agents with Information-Flow Control" (FIDES). arXiv 2505.23643, May 2025 (v2 Sep 2025). Preprint. https://arxiv.org/abs/2505.23643 **V** | A planner that tracks confidentiality and integrity labels, enforces policies deterministically, hides tainted tool results in variables and inspects them through a quarantined LLM with constrained decoding. With policy checks and OpenAI reasoning models it completes on average about 16% more tasks than a basic planner, rising to 24% with prompt tuning. | AgentDojo only. | Deterministic host enforcement of data-flow policy. |
| R11 | Shi, T. et al. "Progent: Securing AI Agents with Privilege Control." arXiv 2504.11703 (v3 May 2026). Preprint. https://arxiv.org/abs/2504.11703 **V** (abstract) | Symbolic policies over tool names and arguments, checked deterministically on every call. An LLM proposes policy updates; an SMT solver classifies each as narrowing (auto-applied) or expansion (needs approval), so privileges only shrink without approval. | Abstract-level reading. | Least-privilege enforcement with an approval hold, as in Turnwise's write gating. |
| R12 | Kamath, A. et al. "Enforcing Temporal Constraints for LLM Agents" (Agent-C). arXiv 2512.23738, 25 Dec 2025. Preprint. https://arxiv.org/abs/2512.23738 **V** (abstract) | Temporal safety specifications checked by SMT during token generation, with constrained generation of a compliant alternative. In retail and airline applications: conformance rises from 77.4% to 100% (Claude Sonnet 4.5) and 83.7% to 100% (GPT-5), while utility rises from 71.8% to 75.2% and from 66.1% to 70.6%. | Preprint; two domains. | A native agent with a formal shield gains both conformance and utility. This is the strongest form of the "simple host rules + capable agent" null. |
| R13 | Elkoussy, L. et al. "AgentLTL." arXiv 2607.02599, 1 July 2026. Preprint. https://arxiv.org/abs/2607.02599 **V** (abstract) | A first-order LTL language over agent traces giving a deterministic, judge-free compliance score; the same constraints can gate tool calls online and serve as a training reward. | Abstract-level reading. | Temporal-logic monitoring for tool-using agents. |
| R14 | Anand, A. et al. "MENTOR: Procedural Shielding of Tool-Using LLM Agents." arXiv 2610.17039, 12 Oct 2026. Preprint. https://arxiv.org/abs/2610.17039 **V** (abstract, partial) | Argues that only blocking tool calls leaves the agent without guidance on how to progress, and combines LTL for ordering with constraint solving for arguments. | Partial reading; no numbers taken. | A criticism that applies to a host that only refuses. |
| R15 | Kekatos, N. et al. "Formal Runtime Verification for Tool-Using LLM Agents: An Offline Same-Benchmark Study on AgentDojo and STAC." arXiv 2610.09793, 7 Oct 2026. Preprint. https://arxiv.org/abs/2610.09793 **V** (abstract, partial) | Replays recorded AgentDojo, STAC and R-Judge trajectories through an unmodified metric first-order temporal logic monitor, offline. | Partial reading; no numbers taken. | Shows existing public traces can be re-monitored without running agents. |
| R16 | Cuadron, A., Yu, P., Liu, Y., Gupta, A. "SABER: Small Actions, Big Errors - Safeguarding Mutating Steps in LLM Agents." arXiv 2512.07850, 26 Nov 2025. Preprint (listed as submitted to ICLR 2026). https://arxiv.org/abs/2512.07850 **V** | On τ-Bench and SWE-Bench Verified traces, each additional deviation in a mutating action reduces the odds of success by up to 92% (airline) and up to 96% (retail); deviations in non-mutating actions have little to no effect. A test-time safeguard that verifies and reflects before mutating steps gives relative gains of +28% (airline), +11% (retail) and +7% (SWE-Bench Verified) for Qwen3-Thinking. Also releases τ-Bench Verified after finding annotation errors. | "Up to" figures; logistic regression on traces. | Control effort belongs on mutating steps, not on every observation. |
| R17 | Ramadge, P. J. and Wonham, W. M. "Supervisory Control of a Class of Discrete Event Processes." *SIAM J. Control and Optimization* 25(1):206-230, 1987. https://collaborate.princeton.edu/en/publications/supervisory-control-of-a-class-of-discrete-event-processes/ **VI** (abstract page only) | The plant generates a formal language; a supervisor is built from a recogniser of the desired behaviour; existence reduces to finding the largest controllable language inside the legal language. | Abstract only. | The design goal is a maximally permissive supervisor. |
| R18 | Girard, A. "Dynamic Triggering Mechanisms for Event-Triggered Control." arXiv 1301.2182 (v3 2014). https://arxiv.org/abs/1301.2182 **V** (abstract). Heemels, Johansson, Tabuada, "An introduction to event-triggered and self-triggered control", CDC 2012: **NOT VERIFIED**. | Event-triggered controllers update only when a triggering condition is met; stability is proved and a lower bound on inter-execution time is established for linear systems. | Continuous control theory. | Control theory's alternative to updating on every sample. |

### What it implies

**The host layer is established practice, not a contribution.** Anderson's three requirements (R1) describe Turnwise's host. By late 2026 there is a peer-reviewed DSL for it (R8) and several preprints with real-model results (R9-R13).

**Schneider's result sets a hard limit (R2).** A host that watches one execution and blocks bad steps can enforce "no write without approval" and "no FINISH without a citation". It cannot enforce "the task gets done" and it cannot exactly enforce "private data does not influence what is sent". The second is why CaMeL and FIDES track data flow (R9, R10). Turnwise parses write intent from the user's text only, which protects control flow. CaMeL's authors state that this is not enough, because injected content can still shape the arguments of an allowed call.

**Simplex and shielding allocate the roles the other way round.** This is the main finding of this family. In Simplex (R5, R6) the complex unverified controller runs the system and the simple verified component only vetoes or takes over at the safety boundary. In shielding (R3) the learner chooses and the shield corrects minimally. In supervisory control (R17) the goal is the most permissive supervisor. Each keeps the capable component in charge of performance. Turnwise gives the simple component the performance-relevant decision, the choice of next operation. So the literature's canonical design is exactly Turnwise's first null baseline: simple host rules plus the same capable agent. Agent-C (R12) is evidence that this null can be strong: conformance to 100% with utility going up.

**Refusal without guidance is a known weakness (R14).** LLM-Modulo makes the same point by requiring critics to give constructive feedback (see 1.7). `AGENTS.md` already asks policy authors to decide what happens after a declined proposal; the literature says that choice largely determines whether the loop makes progress.

**Per-observation control is the time-triggered extreme (R18, R16).** Event-triggered control gets the same guarantees with fewer controller updates. SABER shows empirically where the events are: mutating actions.

**Classification.** (a) for the host-authority half of Turnwise. (b) for the rest: shield or Simplex with the capable agent in charge, data-flow labels for injection, constructive feedback on refusal, and event-triggered intervention at mutating steps.

---

## 1.5 AI Control

### Sources

| ID | Source | Finding | Limitations | Relevance |
|---|---|---|---|---|
| C1 | Greenblatt, R., Shlegeris, B., Sachan, K., Roger, F. "AI Control: Improving Safety Despite Intentional Subversion." arXiv 2312.06942 (v5 July 2024); ICML 2024. https://arxiv.org/abs/2312.06942 **V** | Setting: untrusted GPT-4 (U), trusted GPT-3.5 (T), limited trusted human labour (H) able to audit 2% of problems, 5,000 APPS problems; safety is the probability of submitting no backdoored solution. Usefulness is rescaled so GPT-3.5 = 0 and GPT-4 = 1 (22% and 54% correct before rescaling). Results (safety, scaled usefulness): trusted model only 100%, 2%; upfront auditing 15%, 100%; trusted monitoring 62%, 97%; with defer-to-trusted 5% 74%, 95%; 10% 83%, 93%; 20% 92%, 83%; 50% 100%, 51%; untrusted monitoring 79%, 96%; trusted editing 20% 92%, 94%. | One code setting; red-team strength bounds the safety estimate. | The measured trade-off for "a weak trusted component decides". |
| C2 | Bhatt, A. et al. "Ctrl-Z: Controlling AI Agents via Resampling." arXiv 2504.10374, 14 Apr 2025. Preprint. https://arxiv.org/abs/2504.10374 **V** | First control evaluation in a multi-step agent setting: BashBench, 257 system-administration tasks; U is GPT-4o mini, T is Llama-3.1-8B. Trusted monitoring alone: safety 41.8% at 100% usefulness. Defer to trusted: 72.7% at 95%. Resample protocols: 83.2% to 87.1% at 95%. Best protocol cuts attack success from 58% to 7% at a 5% cost to a non-malicious agent. At most thresholds, deferring to T hurts usefulness more than resampling U. | Attack policy is human-assisted; one environment. | Per-step control of an agent, with numbers. |
| C3 | Wen, J. et al. "Adaptive Deployment of Untrusted LLMs Reduces Distributed Threats." arXiv 2411.17693, 26 Nov 2024. Preprint. https://arxiv.org/abs/2411.17693 **V** | A two-level scheme: micro-protocols handle one task using the trusted model to monitor or edit the untrusted model; an adaptive macro-protocol keeps a credence about the untrusted model and picks safer or riskier micro-protocols. At a given usefulness, 80% fewer backdoors than non-adaptive baselines. Combining all micro-protocols beats any single one. | Code generation testbed. | A non-LLM controller choosing among routes per task, already published. |
| C4 | Griffin, C. et al. "Games for AI Control: Models of Safety Evaluations of AI Deployment Protocols." arXiv 2409.07985 (v2 May 2026). https://arxiv.org/abs/2409.07985 **V** (abstract) | Formalises control evaluations as multi-objective, partially observable stochastic games and finds Pareto-optimal trusted-monitoring protocols. | Abstract-level reading. | Protocol choice is posed as an optimisation over a frontier. |
| C5 | Sandoval, A. and Rushing, C. "Factor(T,U): Factored Cognition Strengthens Monitoring of Untrusted AI." arXiv 2512.02157, 1 Dec 2025. Preprint. https://arxiv.org/abs/2512.02157 **V** (abstract) | A trusted model decomposes the task and an untrusted model solves each child task in isolation. Adding this to trusted monitoring raises safety from 41% to 63%. The protocols show low usefulness in APPS. | Abstract-level reading. | When the weak trusted model does the planning, usefulness suffers. |

### How close is Turnwise, and what was measured?

**Structural match.** AI Control protocols have a capable component that proposes, a cheap trusted component that scores or replaces the proposal, and a scarce human audit. Turnwise has a capable model that proposes, a cheap policy that decides, and held writes. Defer-to-trusted and trusted editing are close relatives. Greenblatt et al. themselves call trusted editing an instance of "dynamic routing".

**Differences.** The threat model differs: AI Control assumes the strong model may be adversarial, and Turnwise makes no such claim. The trusted component in AI Control is itself an LLM, far more capable than a rule table. Control protocols defer selectively on a suspicion score; Turnwise defers every control decision.

**What the trade-off looked like.** Usefulness falls steadily as more is handed to the weak component (C1 table above). The all-trusted end is safe and nearly useless. The attractive points come from a tuned threshold on a continuous score, and from resampling the strong model instead of replacing it (C2). Trusted planning costs usefulness (C5). An adaptive macro-controller over several micro-protocols beat any fixed one (C3).

**Consequence for Turnwise.** It should be evaluated as a family of operating points produced by sweeping a threshold, with usefulness and safety measured separately, as AI Control does. A single configuration compared with a single native agent says little. The measured shape also predicts a usefulness loss for any design that removes the capable model from control decisions, which is the opposite of the non-inferiority Turnwise needs to show.

**Classification.** (a) for the proposal-then-trusted-decision pattern. (b) for design: selective deferral on a calibrated score, resampling, and an adaptive macro-protocol.

---

## 1.6 Systems analogies with real content

### Sources

| ID | Source | Finding | Limitations | Relevance |
|---|---|---|---|---|
| D1 | Avnur, R. and Hellerstein, J. M. "Eddies: Continuously Adaptive Query Processing." SIGMOD 2000. https://www.cs.cmu.edu/~natassa/courses/15-721/papers/eddies.pdf **V** | An eddy routes each tuple through operators and continuously reorders them at run time, merging optimisation and execution. It performs nearly as well as a static optimiser in static scenarios and gives dramatic improvements in dynamic environments. Routing uses a lottery-scheduling learning scheme. | Initial implementation; pipelined operators. | A per-item router that regains control after every operator, 26 years old. |
| D2 | Deshpande, A., Ives, Z., Raman, V. "Adaptive Query Processing." *Foundations and Trends in Databases* 1(1):1-140, 2007. https://www.cs.umd.edu/~amol/papers/fnt-aqp.pdf **V** (sections 3.1-3.2) | The adaptivity loop is measure, analyse, plan, actuate. Measurement, analysis and planning all add overhead to normal processing. Routing may be done per tuple or less frequently. | Survey. | The cost of adaptivity is a first-class design variable. |
| D3 | Leis, V. et al. "How Good Are Query Optimizers, Really?" PVLDB 9(3), 2015. https://www.vldb.org/pvldb/vol9/p204-leis.pdf **V** | Join Order Benchmark, 113 queries on real data. All tested cardinality estimators routinely produce large errors; misestimates by a factor of 1,000 or more are routinely observed for multi-join queries. The cost model matters much less than cardinality estimates. Query performance is unsatisfactory when the engine relies too heavily on estimates; engines that rely mainly on hash joins and full scans are robust to large errors. | Relational joins. | A cost-based chooser is only as good as its estimates; robust defaults beat fine optimisation on bad estimates. |
| D4 | Patel, L. et al. "Semantic Operators: A Declarative Model for Rich, AI-based Data Processing" (LOTUS). arXiv 2407.11418 (v3 Mar 2025). https://arxiv.org/abs/2407.11418 **V** | Model cascades for semantic filters use a small proxy model and a large oracle model, with thresholds on proxy scores learned by sampling and statistical corrections, giving accuracy guarantees relative to a gold algorithm for a user-set accuracy target and error probability. Example: with 0.9 accuracy targets and 0.2 allowed error probability, a fact-checking program runs 1.7x faster and keeps 99.8% of the unoptimised program's accuracy. Optimisations give up to 1,000x speedups on some operators. Notes the proxy may perform very poorly on some tasks, which is why its quality is estimated at query time. | Bulk operators over many records; guarantees are relative to the gold algorithm, not to truth. | The strongest prior art for "cheapest sufficient executor with a quality target". |
| D5 | Liu, C. et al. "A Declarative System for Optimizing AI Workloads" (Palimpzest). arXiv 2405.14696, May 2024. Preprint. https://arxiv.org/abs/2405.14696 **V** | A cost-based optimiser picks model, method and plan to trade runtime, cost and quality. One plan is 3.3x faster and 2.9x cheaper than the baseline with better quality; with parallelism, up to 90.3x speedup at 9.1x lower cost with F1 within 83.5% of a single-threaded GPT-4 baseline. | Three workloads. | Cost-based model selection as a compiler pass. |
| D6 | Shankar, S. et al. "DocETL: Agentic Query Rewriting and Evaluation for Complex Document Processing." arXiv 2410.12189 (v3 Apr 2025). https://arxiv.org/abs/2410.12189 **V** | Agent-guided rewriting and validation of pipelines; outputs 21 to 80% more accurate than well-engineered baselines on four tasks. | Document pipelines. | Here the LLM agent is the optimiser, the reverse of Turnwise. |
| D7 | Russo, M. et al. "Abacus: A Cost-Based Optimizer for Semantic Operator Systems." PVLDB 19(5):1060-1073, 2026. https://arxiv.org/abs/2505.14661 **V** | Searches physical implementations under optional constraints on quality, cost or latency, estimating operator performance from a small set of validation examples, priors or an LLM judge. Systems optimised by Abacus achieve 6.7%-39.4% better quality and are 10.8x cheaper and 3.4x faster than the next best system, on average. | Document and multimodal QA workloads. | Constrained cost-based optimisation with estimates from validation data. |
| Y1 | Dean, J. and Barroso, L. A. "The Tail at Scale." *CACM* 56(2), 2013. https://www.barroso.org/publications/TheTailAtScale.pdf **V** | If a request fans out to 100 servers that are each slow one time in 100, 63% of requests exceed one second. Hedged requests: sending a second request after a 10 ms delay cut 99.9th-percentile latency from 1,800 ms to 74 ms while sending just 2% more requests. Deferring the hedge until the 95th-percentile latency limits extra load to about 5%. | Latency, not correctness. | Hedging beats predicting which replica will be slow. |
| Y2 | Verwaest, T. et al. "Maglev - V8's Fastest Optimizing JIT." V8 blog, 5 Dec 2023. Official engineering blog. https://v8.dev/blog/maglev **V** | Tiers: Ignition interpreter (collects feedback), Sparkplug baseline compiler, Maglev, TurboFan. Maglev compiles about 10x slower than Sparkplug and about 10x faster than TurboFan. Optimised code relies on assumptions checked at run time; a failed check triggers deoptimisation back to a lower tier. | Blog post. | Escalation driven by observed behaviour, with guards and a cheap fallback. |
| Y3 | Arpaci-Dusseau, R. and Arpaci-Dusseau, A. *Operating Systems: Three Easy Pieces*, ch. 8 "Scheduling: The Multi-Level Feedback Queue." Textbook. https://pages.cs.wisc.edu/~remzi/OSTEP/cpu-sched-mlfq.pdf **V** | Without knowing job length, MLFQ starts each job at top priority, demotes it once it uses its allotment, and periodically boosts all jobs. Warns against "voo-doo constants" (Ousterhout's Law) for parameters such as the boost period, and describes gaming of the scheduler. | Textbook treatment. | Learn the class of a job from what it does; distrust magic thresholds. |
| Y4 | Fowler, M. "CircuitBreaker." 6 Mar 2014. Practitioner article. https://martinfowler.com/bliki/CircuitBreaker.html **V** | Closed, open and half-open states; trips after a failure threshold; a trial call after a reset timeout. | Pattern description. | The "first-429 stop" in `AGENTS.md` is a circuit breaker with threshold 1 and no half-open state. |
| Y5 | Ye, N. et al. "Speculative Actions: A Lossless Framework for Faster Agentic Systems." arXiv 2510.04371 (v2 Apr 2026). Preprint. https://arxiv.org/abs/2510.04371 **V** | A faster model predicts the agent's next action; predicted actions run in parallel and commit only on a match. Up to 55% next-action prediction accuracy and up to 20% latency reduction across gaming, e-commerce and web search. | "Up to" figures; the predictor is itself an LLM. | An empirical ceiling on how often a cheaper predictor guesses the capable agent's next action. |

### What it implies

**Adaptive query processing is the most substantive systems analogue.** An eddy is a router that takes control back after every operator, which is Turnwise's invariant 1. Three lessons transfer. First, adaptivity has overhead and need not be per item (D2). Second, the chooser's estimates are the weak point, and they can be wrong by orders of magnitude (D3). Third, the robust response to bad estimates is to prefer executors that degrade gracefully (D3). For Turnwise, that argues for a default route that is safe to be wrong about, not a finely tuned light/heavy split.

**Semantic-operator optimisers are prior art for the cost claim (D4, D5, D7).** They already choose the cheapest sufficient model under a quality target, and LOTUS attaches a statistical guarantee. The guarantee depends on a property agent loops lack: a bulk of similar items from which to sample and compare the proxy with the oracle. The idea still transfers per decision type across a stream of sessions: audit a random sample of light-route decisions with the heavy model, and set the threshold to meet a stated target. That is a better design than a fixed rule and it is checkable.

**Hedging, tiering and feedback queues all avoid a priori prediction (Y1, Y2, Y3).** Each starts cheap, watches what happens and escalates on evidence. Tiered JITs additionally depend on a cheap guard that detects a wrong speculation. For model outputs the guard is the hard part, which is why this is an analogy and not a recipe. Y5 gives a number for the prediction alternative: at best about half of next actions were guessed correctly.

**Classification.** Adaptive query processing and semantic-operator optimisers: (a) for the mechanism and (b) for design (sampled audits with a stated target, robust defaults). Hedged requests, JIT tiering, MLFQ, circuit breakers and speculative execution: (c), with one transferable principle, which is to escalate on observed evidence.

---

## 1.7 Robotics and automated planning

### Sources

| ID | Source | Finding | Limitations | Relevance |
|---|---|---|---|---|
| B1 | Colledanchise, M. and Ögren, P. *Behavior Trees in Robotics and AI: An Introduction.* arXiv 1709.00084 (v6 2022). Book. https://arxiv.org/abs/1709.00084 **V** | Behaviour trees structure switching between tasks so that systems are both reactive and modular; finite state machines trade one against the other. The book shows how behaviour trees generalise hierarchical state machines, the subsumption architecture, teleo-reactive programs and decision trees. | Textbook. | A mature formalism for exactly the switching structure Turnwise hand-codes. |
| B2 | Gat, E. "On Three-Layer Architectures." In *Artificial Intelligence and Mobile Robots*, AAAI Press, 1998. https://flownet.com/gat/papers/tla.pdf **V** | Three components: a reactive controller, a sequencer that selects which primitive behaviour runs, and a deliberator for slow computations. The deliberator can either produce plans for the sequencer (3T) or answer specific queries from the sequencer (ATLANTIS, where the sequencer controls the planner). The sequencer should not perform search or temporal projection. | Retrospective essay. | Turnwise is the ATLANTIS arrangement: a fast sequencer in charge and a slow deliberator consulted on demand. |
| B3 | Brooks, R. A. "A Robust Layered Control System for a Mobile Robot." 1986 (MIT AI Memo 864). **NOT VERIFIED** (scan had no text layer). Described in B1 and B2. | Subsumption: layered reactive behaviours. | Not opened. | Background. |
| B4 | Ahn, M. et al. "Do As I Can, Not As I Say: Grounding Language in Robotic Affordances" (SayCan). arXiv 2204.01691, 2022. https://arxiv.org/abs/2204.01691 **V** | The LLM scores which skill is useful for the instruction; learned value functions give the probability each skill succeeds from the current state; the product selects the skill. 101 real-world tasks: 84% planning success and 74% execution success. Affordance grounding nearly doubles performance over non-grounded baselines. A better LLM improved robot performance. | Fixed skill library; one kitchen. | "Model proposes, a grounded value function disposes", with learned success probabilities. |
| B5 | Kambhampati, S. et al. "LLMs Can't Plan, But Can Help Planning in LLM-Modulo Frameworks." ICML 2024 (PMLR 235). Position paper. https://arxiv.org/abs/2402.01817 **V** | A generate-test-critique loop: the LLM generates candidate plans; a bank of external critics evaluates them; a Backprompt (Meta) Controller pools critiques into the next prompt. Soundness is inherited from the hard critics. Critics can be constructive. Humans are kept out of the inner loop. About 12% of GPT-4 plans are executable without errors when the LLM plans alone. With the VAL verifier as critic, Blocks World reaches 82% within 15 rounds and Logistics 70%; obfuscated Mystery Blocks World reaches about 10%. Travel planning: 6x the baselines within 10 rounds, against a 0.7% baseline for the best prior prompting strategies on GPT-3.5-Turbo. | Position paper; results reported from companion papers. Needs sound critics per domain. | "Model proposes, host verifies" with a meta-controller, published at ICML. |
| B6 | Liu, B. et al. "LLM+P: Empowering Large Language Models with Optimal Planning Proficiency." arXiv 2304.11477 (v3 Sep 2023). https://arxiv.org/abs/2304.11477 **V** (abstract) | The LLM translates a natural-language problem into PDDL, a classical planner solves it, and the LLM translates the plan back. | Needs a domain model. | Where a formal model exists, the planner should plan and the model should translate. |

### What it implies

**LLM-Modulo is the nearest published statement of "model proposes, host verifies" (B5).** It differs from Turnwise in two instructive ways. Its guarantee is explicit and limited: soundness comes from the critics, and completeness depends on the LLM producing a good candidate (hence 10% on the obfuscated domain). And the loop is built around feedback: a rejected candidate returns with a critique. Turnwise's host refuses, and what happens next is left to each policy.

**SayCan shows a stronger form of validation (B4).** Its gate is a learned probability that the action succeeds here and now, multiplied by the model's preference. Turnwise's `host_validates` is a set of binary checks. A learned affordance estimate is a concrete upgrade and connects to the value-of-computation framing in 1.1.

**The control arrangement is 1990s robotics (B2).** Gat's warning that the sequencer must stay simple matches Turnwise's own non-goals. Behaviour trees (B1) offer a formalism with known reactivity properties for the policy.

**Classification.** LLM-Modulo and SayCan: (a) and (b). Three-layer architectures: (a) for the control arrangement. Behaviour trees: (b) as an implementation formalism. Subsumption: (c).

---

## 1.8 Family verdicts

| Family | (a) Prior art making Turnwise non-novel | (b) Concretely better design | (c) Analogy only |
|---|---|---|---|
| Metareasoning and value of computation | Yes: framing (M1-M5); mechanism (M8, M9, M11) | Learned, calibrated value-of-computation gate per decision type | |
| Options, POMDP dialogue managers, CoALA | Yes: framing (P4, P5) | Interrupt on estimated advantage; summary-state learned policy with on-policy data | |
| Selective prediction, deferral, conformal | Partly: clarify decision (M12, U5) | Conformal thresholds with a target risk; risk-coverage reporting | |
| Reference monitors, shielding, Simplex, IFC | Yes: the host-authority half (R1, R8-R13) | Capable agent in charge with a minimal shield; data-flow labels; event-triggered checks at mutating steps | |
| AI Control | Yes: proposal then trusted decision (C1-C3) | Selective deferral on a score; resampling; adaptive macro-protocol | |
| Adaptive query processing, semantic operators | Yes: per-item routing and cost-based model choice (D1, D4, D7) | Sampled audits against a quality target; robust defaults | |
| Tail-tolerance, JIT tiering, MLFQ, circuit breakers, speculation | | Escalate on observed evidence | Yes |
| Three-layer robotics, behaviour trees, SayCan | Yes: control arrangement (B2); grounded gating (B4) | Learned affordance gate; behaviour-tree formalism | Subsumption |
| LLM-Modulo, LLM+P | Yes: generate-test-critique with a meta-controller (B5) | Constructive critics; planner where a model exists | |

No family supports the claim that a hand-written, non-learned policy choosing every next operation is a new or a preferred design. Several support narrower claims that are testable: gating mutating steps, calibrated abstention, timing of clarification.


---

# Part 2 - Agent evaluation and benchmark science

Skeptical literature research for an adversarial review of Turnwise Decision Lab. Research only.

**Verification legend** (same as Part 1). **V**: I opened the primary document in this session and read the passage the claim rests on. **VI**: original not opened; supported by another primary document I did open. **NOT VERIFIED**: bibliographic data or a search snippet only. Arithmetic I did myself is labelled "my arithmetic".

**Question this part answers.** What is the minimum credible experiment for the claim "an explicit non-LLM per-step controller plus a proposal-only model achieves non-inferior task success at lower cost than a well-tuned native agent"?

**Short answer.** A paired, pre-registered non-inferiority trial on a public tool-agent-user benchmark with real model calls. For a 5-point margin it needs about 500 paired tasks at a 20% discordance rate, or about 280 tasks run five times each if most disagreement is run-to-run noise (my arithmetic, section 2.7). It needs four main arms, trivial-agent controls, equal tuning budgets, dollar cost with cached tokens itemised, and decision rules fixed in advance. The present 46 simulated turns can support none of this.

---

## 2.1 Cost-controlled comparison and simple baselines

| ID | Source | Finding (numbers as stated) | Limitations | Relevance |
|---|---|---|---|---|
| E1 | Kapoor, S., Stroebl, B., Siegel, Z. S., Nadgir, N., Narayanan, A. "AI Agents That Matter." arXiv 2407.01502, 1 July 2024. Preprint. https://arxiv.org/abs/2407.01502 **V** | Three trivial baselines (retry up to five times, "warming" the temperature from 0 to 0.5, and escalation from Llama-3 8B through GPT-3.5 and Llama-3 70B to GPT-4 on test failure) match or beat published agent architectures on HumanEval at far lower cost. No significant accuracy difference between warming and the best agent. Reflexion and LDB cost over 50% more than warming; LATS over 50 times more. For similar accuracy, cost differs by almost two orders of magnitude. Results are means of five runs on 164 problems. Joint optimisation on HotPotQA gives 53% lower variable cost at similar accuracy for GPT-3.5. Holdout audit of 17 benchmarks: appropriate holdouts in 1/1 distribution-specific, 3/6 task-specific, 1/8 domain-general and 0/2 general-purpose benchmarks; 7 have no holdout at all. Case study: the top WebArena agent (STeP, 35.8%) hardcodes policies for specific benchmark tasks, such as appending a URL suffix to reach a user profile. | HumanEval is easy and has test signals; findings may not transfer to harder tasks, as the authors say. | Sets the reporting standard: dollar cost, Pareto frontier, simple baselines. The STeP case is a hand-written policy overfitted to a benchmark, which is the main validity risk for a hand-written `TriagePolicy`. Note that "escalation" is itself a light-to-heavy cascade, used as a trivial baseline. |
| E2 | Kapoor, S., Stroebl, B. et al. "Holistic Agent Leaderboard: The Missing Infrastructure for AI Agent Evaluation." arXiv 2510.11977, 13 Oct 2025. Preprint. https://arxiv.org/abs/2510.11977 **V** | 21,730 rollouts, 9 models, 9 benchmarks, about $40,000. The most expensive model is on the cost-accuracy Pareto frontier in only 1 of 9 benchmarks. In 21 of 36 model-agent-benchmark combinations, higher reasoning effort gives equal or lower accuracy. On Online Mind2Web one scaffold-model pair costs $171 and another $1,577, a 9x difference for a two-point accuracy gap. Task-specific scaffolds beat generalist ones (9 of 12 runs on CORE-Bench Hard, 11 of 12 on SWE-bench Verified Mini). Token-based and dollar-based frontiers give very different pictures. Log inspection found agents looking up benchmark answers on HuggingFace, a wrong credit card used in flight booking, and data leakage in the official τ-bench few-shot agent that invalidated those results. The paper states its SWE-Agent costs do not yet account for cache hits. Benchmark cost ranges from $13 (ScienceAgentBench average) to over $450 (Online Mind2Web average). | Preprint. One or few runs per configuration for cost reasons. | The scaffold is a large effect in its own right, so "native agent" must be a specific, tuned scaffold. Inspect logs, not only scores. Cache accounting is easy to get wrong. |
| E4 | Xia, C. S., Deng, Y., Dunn, S., Zhang, L. "Agentless: Demystifying LLM-based Software Engineering Agents." arXiv 2407.01489 (v2 Oct 2024). Preprint. https://arxiv.org/abs/2407.01489 **V** | A fixed three-phase pipeline (localisation, repair, patch validation), without letting the LLM decide future actions or operate complex tools, reached 32.00% on SWE-bench Lite (96 fixes) at $0.70, the best performance and low cost among open-source agents at that time. | 2024 models; SWE-bench Lite. I did not check whether the result held with later models. | The best single piece of evidence in favour of taking control away from the model. It is also prior art for doing so. |
| M9 | Utility-Guided Orchestration (full record in Part 1). **V** | In the authors' own Table I, ReAct beats the explicit utility policy on F1 (0.2662 vs 0.2360) and tokens (546.6 vs 1294.2). | n = 200, one model. | The nearest design to Turnwise did not beat the native loop. |

**Implications.**

1. The primary result must be a cost-accuracy plot in dollars with every arm on it, including the trivial ones (E1).
2. Because light-to-heavy escalation is one of Kapoor et al.'s trivial baselines, a Turnwise saving that comes only from using the light model more often is not evidence for per-step control. The design must separate routing savings from control savings (see the ablations in 2.8).
3. A hand-written policy evaluated on the world it was written for is the STeP pattern. It needs held-out tasks at the level of generality being claimed.

---

## 2.2 Statistical treatment of evaluations

| ID | Source | Finding | Limitations | Relevance |
|---|---|---|---|---|
| T1 | Miller, E. "Adding Error Bars to Evals: A Statistical Approach to Language Model Evaluations." Anthropic. arXiv 2411.00640, Nov 2024. Preprint. https://arxiv.org/abs/2411.00640 **V** | Treat questions as a sample from a super-population. Recommendations: standard errors from the Central Limit Theorem; clustered standard errors when questions come in related groups (clustered errors can be over 3x the naive ones on real evals); variance reduction by resampling answers; analyse paired per-question differences, not population summaries; power analysis before running. Sample-size formula (eq. 9): n = (z_{α/2} + z_β)² (ω² + σ_A²/K_A + σ_B²/K_B) / δ², where ω² is the variance of the per-question difference in conditional means and σ² is the mean within-question variance. Worked example: ω² = 1/9, δ = 0.03, 80% power, α = 0.05 gives n ≈ 969. With σ² = 1/6, ω² = 1/9 and n = 198, raising K from 1 to 10 lowers the minimum detectable effect from 13.2% to 7.5%. Resampling K = 2, 4, 6 reduces total variance by 1/3, 1/2, 5/9 in the paper's example, with a ceiling of 2/3. | Asymptotic methods; examples partly fictional. | Supplies the paired, clustered, repeated-trial framework used in 2.7. |
| T2 | Bowyer, S., Aitchison, L., Ivanova, D. R. "Position: Don't Use the CLT in LLM Evals With Fewer Than a Few Hundred Datapoints." arXiv 2503.01747 (v3 May 2025). https://arxiv.org/abs/2503.01747 **V** | With small benchmarks, CLT-based intervals perform very poorly and usually underestimate uncertainty. Recommends alternatives, including Bayesian credible intervals and Wilson intervals, which behave well at small N. | Position paper with simulations. | 46 turns is far below the threshold in the title. |
| T3 | Card, D. et al. "With Little Power Comes Great Responsibility." arXiv 2010.06595, Oct 2020. https://arxiv.org/abs/2010.06595 **V** | Underpowered experiments are common in NLP. For several GLUE tasks, small test sets mean most comparisons with the state of the art are not adequately powered. Typical machine-translation test sets of 2,000 sentences have about 75% power to detect a 1 BLEU difference. Uses McNemar's test for paired accuracy comparisons and treats 80% power as a minimum. | NLP benchmarks, pre-LLM-agent. | Underpowered studies also exaggerate the effects they do find. |
| T4 | Dietterich, T. G. "Approximate Statistical Tests for Comparing Supervised Classification Learning Algorithms." *Neural Computation* 10(7), 1998. Author copy: https://web.engr.oregonstate.edu/~tgd/publications/dietterich-approximate-statistical-tests-nc1998.pdf **V** | A test for the difference of two proportions and a resampled paired t-test have high Type I error and should not be used. McNemar's test has low Type I error. For algorithms that can be executed only once, McNemar's test is the only test with acceptable Type I error. | Classifier comparison on fixed test sets. | Expensive trials run once per task call for McNemar or its exact version. |
| T5 | NCSS. *PASS Sample Size Software*, ch. 150 "Tests for Two Correlated Proportions (McNemar Test)." Vendor documentation. https://www.ncss.com/wp-content/themes/ncss/pdf/Procedures/PASS/Tests_for_Two_Correlated_Proportions-McNemar_Test.pdf **V** | Only discordant pairs carry information. Gives the approximate sample-size formula of Machin, Campbell, Fayers and Pinol (1997) in terms of the odds ratio P10/P01 and the discordant proportion PD = P10 + P01, and the exact unconditional power of Schork and Williams (1980). Notes the statistic is binomial for a fixed number of discordant pairs. | Documentation, not a research paper. | Source of the standard formula in 2.7. |
| T6 | NCSS. *PASS*, ch. 160 "Non-Inferiority Tests for the Difference Between Two Correlated Proportions." https://www.ncss.com/wp-content/themes/ncss/pdf/Procedures/PASS/Non-Inferiority_Tests_for_the_Difference_Between_Two_Correlated_Proportions.pdf **V** | States the hypotheses H0: P_T - P_S ≤ -M versus H1: P_T - P_S > -M with a positive margin M, a one-sided test, based on Liu, Hsueh, Hsieh and Chen (2002). Stresses that the margin must be chosen to be meaningful. | Documentation; the 2002 paper itself not opened. | The correct test family for "no worse than the native agent". |
| T7 | Lakens, D. "Equivalence Tests: A Practical Primer for t Tests, Correlations, and Meta-Analyses." *Social Psychological and Personality Science* 8(4):355-362, 2017. https://pmc.ncbi.nlm.nih.gov/articles/PMC5502906 **V** | A non-significant difference does not show absence of an effect. The two one-sided tests procedure rejects effects outside pre-set bounds built from the smallest effect size of interest. Bounds should be pre-specified. | Psychology framing. | "No significant difference between arms" would not establish non-inferiority. |
| T8 | Johari, R., Pekelis, L., Koomen, P., Walsh, D. "Always Valid Inference: Continuous Monitoring of A/B Tests." arXiv 1512.04922 (v3 2019). https://arxiv.org/abs/1512.04922 **V** (abstract) | Ordinary p-values and intervals are unreliable when the experimenter chooses the stopping time by watching the data. Always-valid p-values and intervals remain valid at any stopping time. | A/B-testing setting. | Allows stopping early when each trial costs money, without inflating error. |
| T9 | Howard, S. R., Ramdas, A., McAuliffe, J., Sekhon, J. "Time-uniform, nonparametric, nonasymptotic confidence sequences." arXiv 1810.08240 (v9 2022). https://arxiv.org/abs/1810.08240 **V** (abstract) | Confidence sequences valid uniformly over an unbounded horizon, with non-asymptotic coverage under nonparametric conditions. | Theory paper. | A concrete tool for sequential monitoring of a paired difference. |
| - | Classical group-sequential boundaries and alpha spending (Pocock 1977; O'Brien and Fleming 1979; Lan and DeMets 1983). **NOT VERIFIED** | Pre-planned interim looks with a spent error budget. | Not opened. | Named for completeness; use T8 or T9 if a verified basis is required. |
| - | Paired bootstrap over tasks (Efron and Tibshirani; Berg-Kirkpatrick et al. 2012 for NLP). **NOT VERIFIED** | Resample tasks, keeping each task's arm results together. | Not opened. T2 reports that bootstrap intervals also under-cover at small N. | Acceptable as a secondary analysis at a few hundred tasks. |

**Guidance that follows.**

- **Unit of analysis is the task.** Trials within a task, and turns within a session, are clustered (T1). The 46 v0.5 turns sit inside a smaller number of sessions, so the effective sample is smaller than 46.
- **Paired design.** Run every arm on the same tasks and analyse per-task differences (T1). For one trial per task, use McNemar's test or the exact binomial test on discordant pairs (T4, T5).
- **Non-inferiority, not "no difference".** Pre-declare the margin and test one-sided (T6, T7).
- **Small samples.** Below a few hundred tasks use Wilson or Bayesian intervals (T2).
- **Interim looks.** Either fix the sample size or use always-valid inference (T8, T9).

---

## 2.3 Candidate host benchmarks and their validity problems

| ID | Source | Finding | Limitations | Relevance |
|---|---|---|---|---|
| E6 | Yao, S., Shinn, N., Razavi, P., Narasimhan, K. "τ-bench: A Benchmark for Tool-Agent-User Interaction in Real-World Domains." arXiv 2406.12045, June 2024. Preprint. https://arxiv.org/abs/2406.12045 **V** | Tool-agent-user tasks under domain policies; reward compares the final database state with the annotated goal state. 115 retail tasks and 50 airline tasks. Introduces pass^k, the chance that all k i.i.d. trials of a task succeed. GPT-4o with function calling: about 61% pass^1 on retail and about 35% on airline; pass^8 falls to about 25% on retail. The user is simulated by an LLM (gpt-4-0613). The authors list limits of the simulated user: ambiguous instructions, missing domain knowledge, and limited reasoning or instruction-following by the simulator. | 165 tasks; LLM-simulated user. | Best structural fit: policies, confirmations, mutating tool calls, and a reliability metric. |
| E7 | Barres, V., Dong, H., Ray, S., Si, X., Narasimhan, K. "τ²-Bench: Evaluating Conversational Agents in a Dual-Control Environment." arXiv 2506.07982, June 2025. Preprint. https://arxiv.org/abs/2506.07982 **V** | Adds a telecom domain modelled as a Dec-POMDP in which the user also has tools; 114 tasks sampled from 2,285 generated. pass^1 on telecom: 34% (gpt-4.1), 42% (o4-mini), 49% (claude-3.7-sonnet). Manual audit of the user simulator: errors in 47% of airline conversations (13% task-critical), 40% of retail (12% critical), 16% of telecom (6% critical). | Audit on 50-100 conversations per domain with one model pair. | Quantifies simulator noise by domain. Roughly one conversation in eight in retail and airline has a simulator error that prevents task completion. |
| E8 | Sierra Research. `tau2-bench` repository README and Agent Developer Guide. Official repository documentation, read 2026-11-20/21. https://github.com/sierra-research/tau2-bench and https://github.com/sierra-research/tau2-bench/blob/main/src/tau2/agent/README.md **V** | The project is now "τ-bench 2.0"; the previous release, τ³-bench v1.0, included "75+ task fixes"; v1.0.1 is dated 2026-07-15 and fixed grading in one domain. 2.0 changes the judge and the prompts, so 2.0 scores are not comparable with the 1.x leaderboard. Domains listed include airline, retail, telecom and banking_knowledge. A `--num-trials` flag exists. Custom agents subclass `HalfDuplexAgent`, implement `get_init_state` and `generate_next_message(message, state)`, are registered with `registry.register_agent_factory`, and are selected with `tau2 run --agent <name>`. Each call receives one incoming user or tool message and returns one output. The README does not say whether token cost is recorded. | Repository state changes; pin a release. | An external-controller arm can be plugged in as a custom agent whose `generate_next_message` is driven by non-LLM code. Cost logging must be added or verified. |
| R16 | SABER (full record in Part 1). **V** | Audited τ-Bench airline and retail, found annotation errors and underspecified tasks that cap scores, and released "τ-Bench Verified". | Preprint. | An independent audit exists. |
| - | Amazon `tau2-bench-verified` repository. https://github.com/amazon-agi/tau2-bench-verified **NOT VERIFIED** (search snippet only) | Described as a corrected, human-verified version of τ²-bench. | Not opened. | Lead only. |
| E3 | Zhu, Y. et al. "Establishing Best Practices for Building Rigorous Agentic Benchmarks" (Agentic Benchmark Checklist, ABC). arXiv 2507.02825 (v5 Aug 2025). Preprint. https://arxiv.org/abs/2507.02825 **V** | Two validity conditions: task validity (solvable if and only if the agent has the target capability) and outcome validity (a positive result if and only if the task succeeded). Of 10 benchmarks assessed, 7 violate task validity, 7 violate outcome validity and all 10 have reporting limitations. τ-bench: 38% of airline tasks and 6% of retail tasks are intentionally unsolvable and are scored as passed when the environment is left unchanged, so a do-nothing agent passes them; a trivial empty-response agent scores 38% on airline and outperforms a GPT-4o agent; 2% of airline and 3.6% of retail tasks can be passed by dumping the database. WebArena overestimates by 1.4-5.2%. SWE-Lancer allows 100% without solving tasks. KernelBench overestimates by about 31%. OSWorld underestimates by 28% in its Chrome section because websites changed. Applying ABC to CVE-Bench cut overestimation by 33%. Reporting items include R.10 (statistical significance), R.12 (non-AI baselines) and R.13 (results of trivial agents, such as one that does nothing). | Preprint; flaws found on specific benchmark versions, some since patched. | Critical for Turnwise: an agent that holds or refuses is rewarded on these tasks for doing nothing. |
| E9 | Seshadri, P. et al. "Lost in Simulation: LLM-Simulated Users are Unreliable Proxies for Human Users in Agentic Evaluations." arXiv 2601.17087 (v2 Jan 2026). Preprint. https://arxiv.org/abs/2601.17087 **V** (abstract) | On τ-Bench retail, agent success varies by up to 9 percentage points across user-simulator LLMs. Simulated-user evaluation is systematically miscalibrated: it underestimates agents on hard tasks and overestimates on moderately hard ones. | Abstract-level reading. | The choice of user simulator is worth more than a 5-point margin. |
| E10 | Zhou, X., Sun, W. et al. "Mind the Sim2Real Gap in User Simulation for Agentic Tasks." COLM 2026. arXiv 2603.11245 (v2 July 2026). https://arxiv.org/abs/2603.11245 **V** (abstract) | Full τ-bench protocol with 451 human participants on 165 tasks, against 31 LLM simulators. Simulators are excessively cooperative and stylistically uniform, creating an "easy mode" that inflates agent success above the human baseline. | Abstract-level reading. | Simulated-user results overstate real-user performance. |
| E17 | Debenedetti, E. et al. "AgentDojo: A Dynamic Environment to Evaluate Prompt Injection Attacks and Defenses for LLM Agents." NeurIPS 2024 Datasets and Benchmarks. arXiv 2406.13352. https://arxiv.org/abs/2406.13352 **V** | 97 user tasks, 629 security test cases, 70 tools across workspace, Slack, travel and banking suites. Metrics: benign utility, utility under attack, targeted attack success rate. A new agent needs only a query function taking the user instruction, tools and environment state; modular pipelines are supported. | 97 tasks; no simulated user. | Host for the security-utility claim. Published reference points exist: CaMeL 77% vs 84% undefended (Part 1, R9), FIDES and Progent. |
| E18 | Trivedi, H. et al. "AppWorld: A Controllable World of Apps and People for Benchmarking Interactive Coding Agents." arXiv 2407.18901, July 2024. https://arxiv.org/abs/2407.18901 **V** (abstract) | 9 apps, 457 APIs, 750 tasks, state-based unit tests that also check for unexpected changes (collateral damage). GPT-4o solves about 49% of normal and about 30% of challenge tasks. | Agents write code; fit with a typed-operation controller not assessed. | The only candidate large enough for a 5-point margin at one trial per task. |
| E11 | OpenAI. "Introducing SWE-bench Verified." 13 Aug 2024. Official blog. https://openai.com/index/introducing-swe-bench-verified/ **V** | 93 developers annotated 1,699 samples; 38.3% flagged as underspecified and 61.1% for unfair unit tests; 68.3% filtered out; 500 samples retained. | Vendor post. | A benchmark needed human re-validation within a year of release. |
| E12 | OpenAI. "Why we no longer evaluate SWE-bench Verified." 23 Feb 2026. Official blog. https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/ **V** | Audit of 138 problems (27.6% of the set) that o3 did not consistently solve over 64 runs: at least 59.4% have flawed tests; 35.5% narrow tests enforcing a specific implementation; 18.8% tests checking unstated functionality. Frontier models reproduced gold patches or verbatim task details. Recommended SWE-bench Pro in the interim. | Vendor post; the audited subset was selected for failure. | Even the "verified" set became unusable for frontier comparison. |
| E13 | OpenAI. "Separating signal from noise in coding evaluations." 8 July 2026. Official blog. https://openai.com/index/separating-signal-from-noise-coding-evaluations **V** | About 30% of SWE-Bench Pro tasks estimated broken: an agent pipeline flagged 200 of 731 (27.4%), a human campaign 249 (34.1%). OpenAI retracted its recommendation of SWE-Bench Pro. | Vendor post. | The replacement failed too, five months later. |
| E14 | Liang, S., Garg, S., Zilouchian Moghaddam, R. "The SWE-Bench Illusion: When State-of-the-Art LLMs Remember Instead of Reason." arXiv 2506.12286 (v4 Dec 2025). https://arxiv.org/abs/2506.12286 **V** | Models identify buggy file paths from issue text alone with up to 76% accuracy on SWE-Bench Verified, against up to 53% on repositories outside SWE-Bench; up to 35% consecutive 5-gram overlap with ground-truth functions against up to 18% on other benchmarks. | Diagnostic tasks, not direct proof of leakage. | Contamination evidence. Coding benchmarks are a poor host. |
| E15 | XLANG Lab. "OSWorld-Verified." 28 July 2025. Maintainer blog. https://xlang.ai/blog/osworld-verified **V** | About 300 reported issues reviewed and fixed over roughly two months, mostly in evaluators; causes included changed websites, timing, ambiguous instructions and rejected valid solutions. | Maintainer post. | Live-web environments drift. |
| E16 | El hattami, A. et al. "WebArena Verified: Reliable Evaluation for Web Agents." NeurIPS 2025 workshop poster. https://neurips.cc/virtual/2025/124576 **V** (abstract page) | Audits all 812 tasks; replaces loose matching; verifies backend state for state-changing tasks; a 137-task hard subset cuts evaluation cost by 83% and reduces false negatives by about 11% for the tested baseline. | Workshop paper; abstract only. | Shows the fix pattern: backend-state verification. |
| E19, E20 | ToolSandbox (Lu et al., arXiv 2408.04682) and TheAgentCompany (Xu et al., arXiv 2412.14161). **V** (abstracts) | ToolSandbox: stateful tools, a built-in user simulator, milestone and minefield scoring; it contrasts tool-use evaluation with dialogue-state-tracking pipelines that derive tool calls from explicit states under a predefined ontology. TheAgentCompany: the most competitive agent completes 30% of tasks autonomously. | Abstract-level reading. | Alternatives considered and not preferred. |

### Can an external controller arm be plugged in?

- **τ-bench family: yes** (E8). The custom-agent interface hands the agent one message at a time and expects one output. A per-step policy can sit inside `generate_next_message`, call the model for a proposal, and decide. The same interface hosts the native agent, the checklist-prompted agent and the host-rules agent, so all arms share tools, data, user simulator and scoring.
- **AgentDojo: yes** (E17). A new agent needs one query function.
- **One structural mismatch must be settled in advance.** τ-bench scores the final database state. Turnwise holds writes for approval and never executes them. Unless an approval step is defined, Turnwise would fail every task that needs a write, and would pass every unsolvable task. The approval rule (for example, execute a held write once the simulated user has explicitly confirmed it, which τ-bench policy already requires for consequential actions) must be identical for all arms and pre-declared.

### Validity problems to control for

1. **Do-nothing credit.** Report a do-nothing agent and an always-HOLD agent on the same task set, and report results on solvable and unsolvable tasks separately (E3).
2. **Simulator noise.** Fix the simulator model and version for all arms. Expect up to 9 points of movement from the simulator alone (E9) and critical simulator errors in about one conversation in eight (E7). This noise raises the discordance rate and therefore the sample size.
3. **Annotation errors.** Use a corrected, pinned release (E8, R16) and state it. Do not compare with leaderboard numbers from another release.
4. **Scaffold leakage.** HAL found benchmark examples inside an official few-shot agent (E2). Any few-shot content in any arm must be checked against the test tasks.
5. **Sim-to-real.** A result with simulated users is an upper bound on real-user performance (E10).

---

## 2.4 Reliability, provider nondeterminism and drift

| ID | Source | Finding | Limitations | Relevance |
|---|---|---|---|---|
| E5 | Rabanser, S., Kapoor, S., Kirgis, P., Liu, K., Utpala, S., Narayanan, A. "Towards a Science of AI Agent Reliability." arXiv 2602.16666 (v3 June 2026); listed at ICML 2026. https://arxiv.org/abs/2602.16666 **V** (the paper exists; the brief asked for this to be checked) | Twelve metrics over four dimensions: consistency, robustness, predictability, safety. 15 models on GAIA and τ-bench, each task run K = 5 times at temperature 0. Outcome consistency is low across all models: agents that can solve a task often fail to do so consistently. Reliability has improved only slightly over 24 months of releases, with moderate gains on τ-bench and barely any on GAIA. Token and compute use vary widely across runs. Models tolerate tool faults better than paraphrased instructions. Reasoning models do not expose a temperature setting. | Two benchmarks. | Run-to-run variation at temperature 0 is large. Cost also varies run to run. |
| E22 | Atil, B. et al. "Non-Determinism of 'Deterministic' LLM Settings." arXiv 2408.04667 (v5 Apr 2025). Preprint. https://arxiv.org/abs/2408.04667 **V** | Five LLMs configured to be deterministic, eight tasks, 10 runs each. Accuracy varies by up to 15% across naturally occurring runs; the gap between best possible and worst possible performance is up to 70%. No model delivers repeatable accuracy across all tasks. | Single-turn tasks. | A single run per arm cannot be trusted even at temperature 0. |
| E21 | Chen, L., Zaharia, M., Zou, J. "How Is ChatGPT's Behavior Changing over Time?" arXiv 2307.09009 (v3 Oct 2023). https://arxiv.org/abs/2307.09009 **V** | The "same" service changed between March and June 2023: GPT-4's accuracy at identifying prime versus composite numbers fell from 84% to 51%, while GPT-3.5 improved on that task. | 2023 snapshots. | Arms run weeks apart may be compared against different models. |
| E23 | Madaan, L. et al. "Quantifying Variance in Evaluation Benchmarks." arXiv 2406.10229, June 2024. https://arxiv.org/abs/2406.10229 **V** (abstract) | Variance in benchmarks is rarely quantified, although it determines whether differences are meaningful; provides estimates of seed variance. | Abstract-level reading. | Variance must be measured, not assumed. |

**Controls that follow.** Pin a dated model snapshot and record the returned model identifier on every call. Interleave arms in time on the same day, never one arm per week. Run each task at least three to five times per arm. Re-run a fixed sentinel set at the start and end of the campaign to detect drift. Report pass^k alongside pass^1.

---

## 2.5 Baseline under-tuning and forking paths

| ID | Source | Finding | Limitations | Relevance |
|---|---|---|---|---|
| G3 | Melis, G., Dyer, C., Blunsom, P. "On the State of the Art of Evaluation in Neural Language Models." arXiv 1707.05589 (v2 Nov 2017). https://arxiv.org/abs/1707.05589 **V** | With large-scale automatic hyperparameter tuning, standard LSTMs, properly regularised, outperform more recent architectures. | Language modelling. | Apparent architectural gains came from unequal tuning. |
| G4 | Lucic, M., Kurach, K., Michalski, M., Bousquet, O., Gelly, S. "Are GANs Created Equal? A Large-Scale Study." NeurIPS 2018. arXiv 1711.10337. https://arxiv.org/abs/1711.10337 **V** | Most models reach similar scores with enough hyperparameter optimisation and random restarts; no tested algorithm consistently beats the original non-saturating GAN. | GANs. | Same pattern. |
| G5 | Musgrave, K., Belongie, S., Lim, S.-N. "A Metric Learning Reality Check." arXiv 2003.08505 (v3 Sep 2020). https://arxiv.org/abs/2003.08505 **V** | Finds methodological flaws in numerous metric-learning papers; actual improvements over time have been marginal at best. | Metric learning. | Same pattern. |
| G6 | Ferrari Dacrema, M., Cremonesi, P., Jannach, D. "Are We Really Making Much Progress? A Worrying Analysis of Recent Neural Recommendation Approaches." RecSys 2019. arXiv 1907.06902. https://arxiv.org/abs/1907.06902 **V** | Of 18 algorithms from top venues, only 7 could be reproduced with reasonable effort; 6 of those can often be outperformed by comparably simple heuristic methods; the remaining one did not consistently beat a well-tuned non-neural linear ranking method. | Recommender systems. | Simple, well-tuned baselines win. |
| G2 | Lipton, Z. C. and Steinhardt, J. "Troubling Trends in Machine Learning Scholarship." arXiv 1807.03341, July 2018. https://arxiv.org/abs/1807.03341 **V** | Four patterns, including failure to identify the sources of empirical gains, for example crediting architecture changes when gains come from hyperparameter tuning, and proposing many tweaks without ablations. | Essay. | Names the failure mode. |
| G1 | Gelman, A. and Loken, E. "The garden of forking paths." Unpublished manuscript, 14 Nov 2013. http://www.stat.columbia.edu/~gelman/research/unpublished/p_hacking.pdf **V** | Researcher degrees of freedom create a multiple-comparisons problem even when only one analysis is run and the hypothesis was stated in advance, because analysis details are contingent on the data. | Unpublished manuscript. | A pre-registered hypothesis with a post hoc choice of metric, subset or margin is still exposed. |
| G7 | Bertinetto, L., Henriques, J., Albanie, S., Paganini, M., Varol, G. (organisers). "The pre-registration experiment: an alternative publication model for machine learning research." NeurIPS 2020 workshop. https://neurips.cc/virtual/2020/workshop/16158 **V** | Papers are reviewed without results on the strength of the argument and the experimental protocol, and the protocol is run after acceptance. | Workshop format. | Precedent for results-blind protocols in ML. |
| G8 | van Miltenburg, E., van der Lee, C., Krahmer, E. "Preregistering NLP research." arXiv 2103.06944, Mar 2021. https://arxiv.org/abs/2103.06944 **V** (abstract) | Discusses how NLP researchers could pre-register and proposes question sets for different study types; argues for registered reports. | Abstract-level reading. | Practical templates. |

**Implications.** Four independent fields found that proposed methods stopped beating simple baselines once the baselines were tuned equally (G3-G6). I found no source that states "a null baseline should get equal engineering effort" as a rule in those words; it is my inference from these papers and from E1. For Turnwise the practical form is: log tuning effort per arm (prompt revisions, dev-set runs, person-hours) and equalise it. Ideally someone other than the policy's author tunes the nulls. The v0.5 pre-registration is a real strength, but pre-registering a study on a self-authored world with simulated replies fixes the analysis and leaves the world, the tasks and the simulated behaviour as free choices (G1).

---

## 2.6 Cost accounting pitfalls

| ID | Source | Finding | Limitations | Relevance |
|---|---|---|---|---|
| K1 | Erol, M. H., El, B., Suzgun, M., Yuksekgonul, M., Zou, J. "Cost-of-Pass: An Economic Framework for Evaluating Language Models." ICLR 2026. arXiv 2504.13359. https://arxiv.org/abs/2504.13359 **V** (abstract) | Defines cost-of-pass as the expected monetary cost of generating a correct solution, and a frontier cost-of-pass as the minimum across models or a human expert. Finds that performance-oriented inference-time techniques with marginal gains rarely justify their cost. | Single-model tasks, not agents. | The right scalar for "cheaper at equal success". |
| K2 | OpenAI. "Prompt caching" guide. Official documentation, read 2026-11-21. https://developers.openai.com/api/docs/guides/prompt-caching **V** | Caching applies when a request starts with the same prefix; reuse requires the entire prefix to match. Minimum prefix 1,024 tokens for GPT-5.6 and later. Cached tokens are reported in `usage.input_tokens_details.cached_tokens`. On GPT-5.6 and later, cache reads cost 0.1x the ordinary input rate (0.05x for some models) and cache writes 1.25x for the default 30-minute lifetime. | One provider; terms change. | Cached and uncached input tokens differ in price by an order of magnitude, and cache hits depend on prompt structure. |
| E1, E2 | Kapoor et al.; HAL (records above). **V** | Report dollars, not proxies; publish token counts so costs can be recomputed at new prices; distinguish fixed from variable cost; HAL's own SWE-Agent figures omit cache hits; dollar and token frontiers disagree. | | |
| R9 | CaMeL (Part 1). **V** | A proposal-and-interpreter architecture used a median 2.82x input and 2.73x output tokens compared with native tool calling. | AgentDojo. | Reference point for the token overhead of separating proposal from execution. |

**Pitfalls and the rule for each.**

1. **Cache structure differs by architecture.** A native loop appends to one growing prefix, which is cache-friendly. A controller that issues a fresh prompt per operation type may break the prefix and pay full price, or write caches it never reads. Report input tokens split into uncached, cache-read and cache-write, and report cost with and without caching (K2).
2. **Count everything.** Policy calls, retries, fallbacks, rejected proposals, re-proposals and any judge or verifier calls. `AGENTS.md` already requires this and requires `unknown` in place of `0`.
3. **Cost per attempt hides failure.** Report cost-of-pass, in effect mean cost per attempt divided by success rate (my restatement of K1), with a bootstrap interval over tasks.
4. **Cost varies run to run** (E5). Report the distribution across trials, not one total.
5. **Latency is a separate axis.** More, smaller calls can cost fewer tokens and more wall-clock time. Report both.
6. **Engineering cost is a fixed cost** (E1). A hand-written policy per domain has an authoring and maintenance cost that the native agent does not. State it, even if only in hours.
7. **Prices move.** Publish raw token counts by model so the comparison can be recomputed (E1).

---

## 2.7 Sample sizes for paired binary outcomes (worked illustration; my arithmetic)

Everything in this section is my own calculation from standard formulas (T1, T5, T6). I checked the non-inferiority figures by Monte Carlo simulation (8,000 replications per case) and say so where relevant.

### Set-up

Two arms run on the same n tasks, one trial each. For each task the pair of outcomes is one of four kinds. Let P10 be the share of tasks where only the new arm succeeds and P01 the share where only the reference arm succeeds. The discordance rate is PD = P10 + P01 and the difference in success rates is δ = P10 - P01. The per-task difference has variance PD - δ².

- **Non-inferiority** at margin M, one-sided α, power 1 - β, true difference zero: n = (z_{1-α} + z_{1-β})² × PD / M². With α = 0.05 and power 0.80 the multiplier is (1.6449 + 0.8416)² = 6.18.
- **Detecting a difference** δ (McNemar, two-sided α): n = (z_{1-α/2} √PD + z_{1-β} √(PD - δ²))² / δ². This is algebraically the same as the Machin et al. formula in T5.

**The success level matters only through the discordance rate.** When both arms have the same true success rate p, the formula does not contain p. So the tables below apply to both the 70% and the 85% case. What p changes is which discordance rates are plausible. With equal success rates, PD = 2p(1 - p)(1 - φ), where φ is the correlation between the two arms' outcomes on a task.

| True success of both arms | PD if arms were independent | Implied correlation at PD = 10% | at PD = 20% | at PD = 30% |
|---|---|---|---|---|
| 70% | 42.0% | 0.76 | 0.52 | 0.29 |
| 85% | 25.5% | 0.61 | 0.22 | -0.18 (at the feasible maximum; implausible) |

At 85% success, a 30% discordance rate would mean every failure of one arm is a success of the other. Treat that cell as a worst case, not an expectation.

### Non-inferiority: paired tasks needed (one-sided α = 0.05, power 0.80, true difference zero, one trial per task)

| Margin | PD = 10% | PD = 20% | PD = 30% |
|---|---|---|---|
| 5 points | 248 | 495 | 742 |
| 10 points | 62 | 124 | 186 |

These hold for both arms at about 70% and for both arms at about 85%. Simulation check: power 0.795 (70%) and 0.805 (85%) at n = 495, PD = 20%, margin 5; power 0.799 and 0.810 at n = 124, PD = 20%, margin 10. Simulated Type I error at the margin was 0.050 at n = 495 and 0.060 at n = 124, so the simple Wald test is slightly liberal at the smaller size; use an exact or score-based test there.

If the new arm is truly a little worse, the numbers rise fast. If it is truly 2 points worse and the margin is 5, the effective distance is 3 points and n grows by a factor of about (5/3)² ≈ 2.8.

### Detecting a difference: paired tasks needed (power 0.80, one trial per task)

| True difference | Test | PD = 10% | PD = 20% | PD = 30% |
|---|---|---|---|---|
| 5 points | two-sided α = 0.05 | 312 | 626 | 940 |
| 5 points | one-sided α = 0.05 | 246 | 493 | 740 |
| 10 points | two-sided α = 0.05 | 77 | 155 | 234 |
| 10 points | one-sided α = 0.05 | 60 | 122 | 184 |

For comparison, an unpaired design comparing 70% with 75% needs about 1,251 tasks per arm (two-sided α = 0.05, power 0.80). Against the two-sided row above, pairing cuts the tasks needed per arm by a factor of about 4 at PD = 10%, 2 at PD = 20% and 1.3 at PD = 30%.

### How k repeated trials per task change this

Split the discordance into two parts: a share f that is run-to-run noise within a task (model sampling, simulator variation) and a share 1 - f that is stable disagreement between the arms on particular tasks. Averaging k trials per task per arm shrinks only the first part. Following Miller's eq. 9 (T1):

n(k) = n(1) × (1 - f + f / k)

| Noise share f | k = 2 | k = 3 | k = 5 | k = 8 | k = 10 | Floor as k grows |
|---|---|---|---|---|---|---|
| 0.3 | 0.85 | 0.80 | 0.76 | 0.74 | 0.73 | 0.70 |
| 0.5 | 0.75 | 0.67 | 0.60 | 0.56 | 0.55 | 0.50 |
| 0.8 | 0.60 | 0.47 | 0.36 | 0.30 | 0.28 | 0.20 |
| 1.0 | 0.50 | 0.33 | 0.20 | 0.13 | 0.10 | 0.00 |

(Entries are the multiplier on the number of tasks.)

Three consequences:

1. **Repeats save tasks, not runs.** Total runs per arm are n(k) × k = n(1) × (k(1 - f) + f), which rises with k whenever f < 1. If more tasks are available, more tasks is the cheaper route. Repeats are for when the benchmark is a fixed size, and for measuring pass^k.
2. **There is a floor.** Stable task-level disagreement cannot be averaged away. Beyond about k = 5 the gain is small unless noise dominates.
3. **f must be estimated, not assumed.** An A/A run (the same arm twice on the same tasks) measures pure-noise discordance directly. Miller's own example moves the minimum detectable effect from 13.2% to 7.5% when K goes from 1 to 10 at n = 198 (T1).

### What fixed benchmark sizes can show

Smallest non-inferiority margin testable at one-sided α = 0.05 and power 0.80, assuming a true difference of zero:

| Task set | n | PD = 20%, k = 1 | PD = 20%, k = 5, f = 0.5 | PD = 20%, k = 5, f = 0.8 |
|---|---|---|---|---|
| τ-bench airline | 50 | 15.7 points | | |
| AgentDojo user tasks | 97 | 11.3 points | | |
| τ-bench retail | 115 | 10.4 points | | |
| τ-bench retail + airline | 165 | 8.7 points | 6.7 points | 5.2 points |
| retail + airline + telecom | 279 | 6.7 points | 5.2 points | 4.0 points |
| AppWorld | 750 | 4.1 points | | |
| Turnwise v0.5 | 46 turns | 16.4 points | | |

For n = 165 the same calculation gives 6.1 points at PD = 10% and 10.6 points at PD = 30% (k = 1).

**Reading.** A 5-point margin is out of reach on τ-bench retail plus airline at one trial per task. It becomes reachable with about five trials per task if most disagreement is noise, or by adding the telecom domain. A 10-point margin is reachable on retail plus airline at one trial per task for PD up to about 25%. The 46-turn study, even if its turns were independent and its replies real, could test only a margin of about 16 points. Zero failures in 46 trials leaves a one-sided 95% upper bound of 6.3% on the true failure rate, which bounds any safety claim.

---

## 2.8 Minimum credible design

This section is my synthesis from the sources above.

### Host benchmark

**Primary: the τ-bench family (retail and airline; add telecom for power), at one pinned, corrected release, run through its custom-agent interface.**

Reasons:

1. It is the closest public match to what Turnwise claims to control: multi-turn tool use under written policy, explicit user confirmation before consequential actions, and state-changing calls (E6).
2. pass^k is native, so reliability is measured, not only average success (E6).
3. All arms can be plugged into one interface with shared tools, data, simulator and scoring (E8).
4. Its defects are documented and can be designed around: do-nothing credit (E3), simulator error rates (E7, E9, E10), annotation fixes (E8, R16).
5. Independent results on native agents exist for calibration (E2, E5).

Known costs of this choice: only 165 to 279 tasks, an LLM-simulated user, and version churn that prevents comparison with published leaderboards.

**Secondary: AgentDojo, for the write-gating and injection claims.** It reports benign utility, utility under attack and attack success, and published defences give reference points (E17; Part 1, R9-R11). With 97 tasks it supports roughly an 11-point utility margin at one trial per task.

**Power-oriented alternative: AppWorld** (750 tasks, collateral-damage checks, no simulated user). I did not assess whether a typed-operation controller fits its code-writing interface.

**Not recommended: SWE-bench variants.** Both the Verified and Pro sets were withdrawn by OpenAI for flawed tests and contamination within 2026 (E12, E13, E14), and the operation set (clarify, hold, approve) does not fit.

### Why a self-authored synthetic world is not enough

1. **The author controls both sides.** The policy and the world it is tested on come from the same hands. This is the STeP pattern (E1).
2. **Simulated replies have no distribution.** A simulated model reply cannot disagree with its author's expectations, vary between runs, or be wrong in ways nobody anticipated. E5 and E22 show that real variation at temperature 0 is large.
3. **No external reference.** Without published native-agent results on the same tasks, nobody can tell whether the native baseline was run competently (G3-G6).
4. **No holdout at the claimed level of generality.** A domain-general claim needs held-out tasks, not held-out samples (E1).
5. **Too small.** See 2.7.
6. **Even public, human-validated benchmarks fail** (E11-E13, E15). A private one has had none of that scrutiny.

The synthetic world remains useful for what `AGENTS.md` says it is: a mechanism test of control flow.

### Arms

All arms use the same model snapshot, tools, data, user simulator, approval rule, token budget ceiling and scoring.

| Arm | What it is | Why it is needed |
|---|---|---|
| A | Native agent: the benchmark's reference tool-calling agent, tuned | The reference for non-inferiority |
| B | Native agent plus a checklist prompt | Tests whether a prompt reproduces the benefit |
| C | Simple host rules plus the same native agent (shield only: validation, write hold, citation check) | The canonical Simplex or shielding design; isolates the value of per-step control over a veto |
| D | Per-step policy plus the same model, proposal-only (Turnwise Core) | The treatment |
| E | `HANDOFF_AGENT` variant | Existing contrast: control ownership changes for a segment |

D must beat or match each of A, B and C, not their average. With one treatment and three references, adjust for three comparisons (for example Holm), or pre-declare C as the single primary comparator.

### Ablations

1. **Routing versus control.** Run D with the heavy model only. If the saving disappears, it came from using a cheaper model, which Kapoor et al.'s trivial "escalation" baseline also does (E1). Add that escalation baseline to arm A.
2. **Per-step versus per-task.** The policy decides once at the start and then hands to the native loop.
3. **Proposal-only versus direct reads.** Let the model execute read-only tools directly; keep the gate on mutating tools. SABER predicts most of the benefit sits at mutating steps (R16).
4. **Refusal with and without feedback.** Return the host's reason to the model, or return only a refusal (Part 1, R14, B5).
5. **Caching on and off** for every arm (K2).

### Negative controls

1. **Trivial agents:** do-nothing, always-HOLD, always-CLARIFY, always-direct-answer. Required by ABC item R.13 and essential on τ-bench, where doing nothing passes 38% of airline tasks (E3).
2. **A/A run:** arm A against itself. Measures noise discordance, validates the pipeline, and supplies PD and f for the power calculation.
3. **Scrambled policy:** arm D with the policy's decisions permuted across states at matched frequencies. If it does as well, the policy's content is not what matters.
4. **Length-matched placebo prompt** for arm B, to separate checklist content from prompt length.
5. **Sentinel set** re-run at the start and end to detect provider drift (E21).

### Procedure

- **Split first.** A development split for tuning every arm with a logged, equal budget; a test split run once. Tasks, not samples, are held out (E1).
- **Real model calls** on a pinned dated snapshot, arms interleaved in time, k ≥ 3 trials per task per arm (k = 5 if the 5-point margin is the target on 165 to 279 tasks).
- **Log inspection** of a random sample of trajectories from every arm, for shortcuts and unsafe actions (E2).
- **Stopping.** Fix n in advance, or pre-declare a sequential rule with always-valid inference (T8, T9).

### Cost accounting

Dollar cost per task and cost-of-pass per arm with intervals; input tokens split into uncached, cache-read and cache-write; every policy call, retry, rejected proposal and verifier call counted; latency reported separately; raw token counts published; authoring hours for the policy and for each baseline stated (2.6).

### Pre-declared decision rules

Declare before any test-split run: primary endpoint (per-task success, mean over k trials), comparator (arm C, or all of A, B, C with correction), margin M, α, the cost threshold, and the safety endpoint.

| Outcome | Rule |
|---|---|
| **Success** | The one-sided 95% lower confidence bound for (success of D minus success of comparator) is above -M; and the 95% upper bound for the cost-of-pass ratio D / comparator is below the declared threshold (below 1 at minimum); and policy-violation and unsafe-write rates for D are not higher (upper bound of the difference at or below zero or a declared tolerance); and the trivial-agent and scrambled-policy controls score clearly below D |
| **Failure** | The 95% upper confidence bound for the success difference is below -M (D is inferior); or D is non-inferior but its cost-of-pass is not lower; or a trivial or scrambled control matches D |
| **Inconclusive** | Anything else, including a confidence interval that spans -M. Report it as inconclusive, not as "no difference" (T7) |

Suggested margin: 5 points if at least 279 tasks with k = 5 can be afforded, otherwise 10 points, stated as a limitation. Per `AGENTS.md`, an outcome where arm C matches D is a SHRINK or STOP result, and the plan should say so in advance.

### What a tough reviewer would still ask

Whether the native agent was tuned by someone who wanted it to win. Whether the approval rule favours the arm that holds writes. Whether the policy was written after seeing test-split tasks. Whether results replicate on a second model family. Whether simulated-user results survive a small human-user sample (E10).

---

## 2.9 Source table (Part 2)

Full records with findings and limitations are in the section tables above. This index lists every Part 2 source with its status.

| ID | Citation | Type | URL | Status |
|---|---|---|---|---|
| E1 | Kapoor et al., "AI Agents That Matter", 2024 | Preprint | https://arxiv.org/abs/2407.01502 | V |
| E2 | Kapoor, Stroebl et al., "Holistic Agent Leaderboard", 2025 | Preprint | https://arxiv.org/abs/2510.11977 | V |
| E3 | Zhu et al., "Establishing Best Practices for Building Rigorous Agentic Benchmarks", 2025 | Preprint | https://arxiv.org/abs/2507.02825 | V |
| E4 | Xia et al., "Agentless", 2024 | Preprint | https://arxiv.org/abs/2407.01489 | V |
| E5 | Rabanser et al., "Towards a Science of AI Agent Reliability", 2026 | Preprint; listed at ICML 2026 | https://arxiv.org/abs/2602.16666 | V |
| E6 | Yao et al., "τ-bench", 2024 | Preprint | https://arxiv.org/abs/2406.12045 | V |
| E7 | Barres et al., "τ²-Bench", 2025 | Preprint | https://arxiv.org/abs/2506.07982 | V |
| E8 | Sierra Research, tau2-bench README and Agent Developer Guide | Official repository docs | https://github.com/sierra-research/tau2-bench | V |
| E9 | Seshadri et al., "Lost in Simulation", 2026 | Preprint | https://arxiv.org/abs/2601.17087 | V (abstract) |
| E10 | Zhou, Sun et al., "Mind the Sim2Real Gap in User Simulation for Agentic Tasks", COLM 2026 | Peer-reviewed | https://arxiv.org/abs/2603.11245 | V (abstract) |
| E11 | OpenAI, "Introducing SWE-bench Verified", 2024 | Official blog | https://openai.com/index/introducing-swe-bench-verified/ | V |
| E12 | OpenAI, "Why we no longer evaluate SWE-bench Verified", 2026 | Official blog | https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/ | V |
| E13 | OpenAI, "Separating signal from noise in coding evaluations", 2026 | Official blog | https://openai.com/index/separating-signal-from-noise-coding-evaluations | V |
| E14 | Liang et al., "The SWE-Bench Illusion", 2025 | Preprint | https://arxiv.org/abs/2506.12286 | V |
| E15 | XLANG Lab, "OSWorld-Verified", 2025 | Maintainer blog | https://xlang.ai/blog/osworld-verified | V |
| E16 | El hattami et al., "WebArena Verified", NeurIPS 2025 workshop | Workshop paper | https://neurips.cc/virtual/2025/124576 | V (abstract page) |
| E17 | Debenedetti et al., "AgentDojo", NeurIPS 2024 D&B | Peer-reviewed | https://arxiv.org/abs/2406.13352 | V |
| E18 | Trivedi et al., "AppWorld", 2024 | Preprint | https://arxiv.org/abs/2407.18901 | V (abstract) |
| E19 | Lu et al., "ToolSandbox", 2024 | Preprint | https://arxiv.org/abs/2408.04682 | V (abstract) |
| E20 | Xu et al., "TheAgentCompany", 2024 | Preprint | https://arxiv.org/abs/2412.14161 | V (abstract) |
| E21 | Chen, Zaharia, Zou, "How Is ChatGPT's Behavior Changing over Time?", 2023 | Preprint | https://arxiv.org/abs/2307.09009 | V |
| E22 | Atil et al., "Non-Determinism of 'Deterministic' LLM Settings", 2024-25 | Preprint | https://arxiv.org/abs/2408.04667 | V |
| E23 | Madaan et al., "Quantifying Variance in Evaluation Benchmarks", 2024 | Preprint | https://arxiv.org/abs/2406.10229 | V (abstract) |
| T1 | Miller, "Adding Error Bars to Evals", 2024 | Preprint | https://arxiv.org/abs/2411.00640 | V |
| T2 | Bowyer, Aitchison, Ivanova, "Don't Use the CLT in LLM Evals With Fewer Than a Few Hundred Datapoints", 2025 | Position paper | https://arxiv.org/abs/2503.01747 | V |
| T3 | Card et al., "With Little Power Comes Great Responsibility", 2020 | Preprint | https://arxiv.org/abs/2010.06595 | V |
| T4 | Dietterich, "Approximate Statistical Tests for Comparing Supervised Classification Learning Algorithms", 1998 | Peer-reviewed | https://web.engr.oregonstate.edu/~tgd/publications/dietterich-approximate-statistical-tests-nc1998.pdf | V |
| T5 | NCSS PASS ch. 150, McNemar test | Vendor documentation | https://www.ncss.com/wp-content/themes/ncss/pdf/Procedures/PASS/Tests_for_Two_Correlated_Proportions-McNemar_Test.pdf | V |
| T6 | NCSS PASS ch. 160, non-inferiority for correlated proportions | Vendor documentation | https://www.ncss.com/wp-content/themes/ncss/pdf/Procedures/PASS/Non-Inferiority_Tests_for_the_Difference_Between_Two_Correlated_Proportions.pdf | V |
| T7 | Lakens, "Equivalence Tests: A Practical Primer", 2017 | Peer-reviewed | https://pmc.ncbi.nlm.nih.gov/articles/PMC5502906 | V |
| T8 | Johari et al., "Always Valid Inference", 2015-19 | Preprint | https://arxiv.org/abs/1512.04922 | V (abstract) |
| T9 | Howard et al., "Time-uniform, nonparametric, nonasymptotic confidence sequences", 2018-22 | Preprint | https://arxiv.org/abs/1810.08240 | V (abstract) |
| G1 | Gelman and Loken, "The garden of forking paths", 2013 | Unpublished manuscript | http://www.stat.columbia.edu/~gelman/research/unpublished/p_hacking.pdf | V |
| G2 | Lipton and Steinhardt, "Troubling Trends in Machine Learning Scholarship", 2018 | Essay | https://arxiv.org/abs/1807.03341 | V |
| G3 | Melis, Dyer, Blunsom, "On the State of the Art of Evaluation in Neural Language Models", 2017 | Preprint | https://arxiv.org/abs/1707.05589 | V |
| G4 | Lucic et al., "Are GANs Created Equal?", NeurIPS 2018 | Peer-reviewed | https://arxiv.org/abs/1711.10337 | V |
| G5 | Musgrave, Belongie, Lim, "A Metric Learning Reality Check", 2020 | Preprint | https://arxiv.org/abs/2003.08505 | V |
| G6 | Ferrari Dacrema, Cremonesi, Jannach, "Are We Really Making Much Progress?", RecSys 2019 | Peer-reviewed | https://arxiv.org/abs/1907.06902 | V |
| G7 | NeurIPS 2020 pre-registration workshop | Workshop page | https://neurips.cc/virtual/2020/workshop/16158 | V |
| G8 | van Miltenburg, van der Lee, Krahmer, "Preregistering NLP research", 2021 | Preprint | https://arxiv.org/abs/2103.06944 | V (abstract) |
| K1 | Erol et al., "Cost-of-Pass", ICLR 2026 | Peer-reviewed | https://arxiv.org/abs/2504.13359 | V (abstract) |
| K2 | OpenAI, "Prompt caching" guide | Official documentation | https://developers.openai.com/api/docs/guides/prompt-caching | V |
| - | Amazon `tau2-bench-verified` repository | Repository | https://github.com/amazon-agi/tau2-bench-verified | NOT VERIFIED |
| - | Pocock 1977; O'Brien and Fleming 1979; Lan and DeMets 1983 (group-sequential designs) | Peer-reviewed | none opened | NOT VERIFIED |
| - | Efron and Tibshirani; Berg-Kirkpatrick et al. 2012 (paired bootstrap) | Book; peer-reviewed | none opened | NOT VERIFIED |
| - | Liu, Hsueh, Hsieh, Chen 2002; Machin et al. 1997; Schork and Williams 1980 (formulas cited inside T5 and T6) | Peer-reviewed | none opened | VI (through T5, T6) |

Part 1 sources referenced here (M9, R9, R14, R16, B5) have full records in the Part 1 family tables.

### Things I could not verify, or verified only in part

- Final publication venues for several arXiv papers were not checked; they are labelled "Preprint".
- Sources marked "V (abstract)" were opened, but only the abstract or introduction was read. No numbers beyond those quoted were taken from them.
- The τ-bench repository does not state in its README whether token cost is recorded. This must be checked before relying on it for cost accounting.
- I did not check whether Agentless's 2024 result held with later models, or whether a typed-operation controller fits AppWorld.
- "A null baseline should get equal engineering effort" is my inference from G3-G6 and E1, not a quoted rule.

---

# What an outsider from each discipline would build

**This section is my synthesis, not a finding from any single source.** Each entry says what a practitioner of that field would build if handed Turnwise's goal, and cites the Part 1 or Part 2 source IDs behind it.

- **Decision theorist (metareasoning).** A gate per decision type that estimates the value of each candidate computation from logged counterfactuals and acts only when the estimate is positive. No rule table (M2, M4, M7, M8).
- **Reinforcement-learning researcher.** Treat the native loop as an option and learn when to interrupt it, from on-policy data, with an explicit deliberation cost (P1, P2, P9).
- **Dialogue-systems engineer.** A tracked summary state, a small set of system acts and a learned policy, evaluated system-wide and not turn by turn (P4, P6).
- **Statistician working on selective prediction.** Conformal thresholds for abstain, clarify and escalate, with a stated target risk, and risk-coverage curves in the report (U2, U5).
- **Safety-critical control engineer.** Simplex: the capable agent runs the task; a small verified monitor vetoes steps that leave the safe envelope; a simple fallback takes over only then. This is Turnwise's own first null baseline (R5, R6, R3).
- **Security engineer.** A reference monitor plus data-flow labels, because a monitor that sees only actions cannot stop untrusted data from shaping an allowed call (R1, R2, R9, R10).
- **AI Control researcher.** A suspicion score with a tuned deferral threshold, resampling in place of replacement, a red team, and safety and usefulness reported as a frontier (C1, C2, C3).
- **Database researcher.** A cost-based optimiser with sampled audits of the cheap route against the expensive one, a stated accuracy target, and robust defaults where estimates are poor (D3, D4, D7).
- **Systems engineer.** Start cheap, escalate on observed evidence, hedge when latency matters, and intervene on events such as mutating calls, not on every observation (Y1, Y2, Y3, R16, R18).
- **Roboticist.** A behaviour tree as the sequencer, the model as a deliberator consulted on demand, and learned affordance scores as the gate (B1, B2, B4).
- **Planning researcher.** Generate-test-critique with sound critics that return reasons, and a classical planner wherever a formal model of the workflow exists (B5, B6).
- **Evaluation scientist.** Before any of the above: a pre-registered paired non-inferiority trial on a public benchmark with trivial-agent controls and dollar costs (Part 2, section 2.8).

Nine of these twelve keep the capable model in charge of choosing the next step and add a narrow, calibrated or verified intervention. None would hand-write a policy over every operation.

---

# Surprises and contradictions

1. **The nearest prior art lost to ReAct in its own table** (M9): lower F1 and more than twice the tokens. The abstract's "10.6%" saving compares two variants of the same controller.
2. **Three control traditions point at Turnwise's null baseline as the standard design** (R3, R5, R17). The hypothesis under review is the unusual allocation of roles.
3. **A do-nothing agent passes 38% of τ-bench airline tasks** (E3). A controller with HOLD as an operation is the kind of agent that benefits.
4. **The benchmark's own authors measured critical user-simulator errors in about one conversation in eight** on retail and airline (E7).
5. **Both "verified" coding benchmarks were withdrawn within five months of each other in 2026** (E12, E13).
6. **Evidence cuts both ways on removing control from the model.** Agentless (E4) and the 2020 dialogue-pipeline result (P6) favour it. AI Control's usefulness curve (C1), Factor(T,U) (C5) and M9 go against it. Agent-C (R12) shows a shielded native agent gaining both conformance and utility.
7. **Errors concentrate in mutating steps** (R16). This supports gating writes and undercuts regaining control after every observation.
8. **Higher reasoning effort gave equal or lower accuracy in 21 of 36 runs** (E2), so "heavy" is not reliably better than "light", which weakens a fixed light-to-heavy escalation rule.

---

# Part 1 sources not verified, or verified only indirectly

- **Russell and Wefald 1991 (M1):** paywalled. Content checked through Russell's 1997 encyclopedia entry (M2), Hay et al. 2012 (M4) and De Sabbata et al. 2024 (M6).
- **Sha 2001, "Using Simplicity to Control Complexity" (R4):** publisher page empty. Content checked through Sha's 2008 position paper (R5), the Neural Simplex paper (R6) and the 1995 SEI report abstract (R7).
- **Chow 1970 (U1):** not opened.
- **Ramadge and Wonham 1987 (R17):** abstract page only.
- **Heemels, Johansson and Tabuada 2012 (event-triggered control tutorial):** search result only.
- **Brooks 1986 (B3):** scan had no text layer.
- Several Part 1 sources were read at abstract level only and are marked "V (abstract)" in their tables.
