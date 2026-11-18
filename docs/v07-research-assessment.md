# v0.7 research assessment: what v0.6 established, where it breaks, and what to test next

Written before the v0.7 locked run. It reconstructs the state of the project from the repository and GitHub on 2026-11-18, not from summaries. Results of the v0.7 study are in [`reports/v07/summary.md`](../reports/v07/summary.md); this document is the reasoning that led to it.

## 1. Evidence map

Status of each claim on 2026-11-18. *Reproduced* means recomputed in this work from committed traces or by running the code; *observed* means recorded by an earlier run and not re-run.

| Claim | Status | Where to check |
|---|---|---|
| v0.6 held-out success: decision-driven 16/30, heavy-only 13/30, rules 14/30 | **Reproduced** from recorded traces (not from re-run inference) | `python -m turnwise_lab.agent.bench --report`; `reports/v06/traces/heldout/` |
| Decision-driven arm failed all 7 investigations on the frozen check | **Reproduced** from traces | same |
| Heavy-only agent computed fewer tokens than the decision-driven arm (394 vs 570 per task); the pre-registered "96.5% fewer heavy tokens" is generation-only | **Reproduced** from traces | `reports/v06/audit.md` §1 |
| 11 of 14 decision-driven failures were confident (p ≥ 0.5), so the escalation gate could not fire | **Reproduced** from traces | `reports/v06/audit.md` §2 |
| Both dropped actions in the decision-driven arm were caused by escalation to a text-only generator | **Reproduced** from traces (H18, H19) | `agent/providers.py` `LearnedDecider.decide`; audit §2 |
| No reply on the 7 investigations and 2 action requests was fully correct in any arm | **Observed**: one LLM adjudicator, packet without the assembled prompt | `reports/v06/adjudication/` |
| The frozen lexical check passes replies the facts contradict | **Observed** (adjudication), consistent with the code: `_text_ok` is substring matching | `agent/bench.py` |
| Model inference numbers themselves (latency, token counts, generated text) | **Observed**, single run, greedy decoding, one CPU | trace provenance blocks |
| A decision head trained on 614 synthetic states transfers to independently worded tasks | **Disputed** by v0.6 itself: 0/7 investigations | PR #6 |
| Per-step decision control lowers total cost at equal quality against a capable agent | **Untested**. No capable model has run in any arm | issue #9 |
| Dynamic prompt-block selection pays for itself | **Not supported**: same success as full context, 1.15 s per task of overhead, slower p95 | audit §1 |
| v0.5 "tool-calling agent 46/46" | **Obsolete as evidence**: it was an assumed-perfect agent, never executed | README (v0.5 section) |
| v0.4 route-label agreement (38/40) | **Obsolete as evidence**: labels and rules shared an author; agreement is not an outcome | README (earlier versions) |
| OpenAI Decisions / System One controllers | **Untested**: adapters exist, exercised against a fake server only | `agent/remote.py` |

## 2. Where v0.6 breaks (each with a code path and a reproduction)

The v0.6 audit classified failures. This section names the mechanism in code. Items marked *test* are pinned in [`tests/test_v07_diagnosis.py`](../tests/test_v07_diagnosis.py), which runs against the frozen v0.6 code without changing it.

### Evidence and causal reasoning

1. **The host accepts an exit after any single receipt.** `Host.validate` allows `finish` when "at least one verified observation" exists, whatever was asked. H09 (`get_error_metrics → finish` for a p95 question) and H12 end this way. Nothing in the host relates the evidence to the request. *Test.*
2. **Sufficiency lives only in the controller's weights.** The trained head learned the sequence errors → deploys → heavy from templates. On independent wording it stopped early with high confidence (H13: 0.98 → 0.99). A probability over *operations* is not a statement about *evidence*; calibrating it better does not make it one.
3. **Documents reach the model through two paths with different provenance.** `context._runbooks` retrieves runbooks into the prompt without a tool call; the scorer counts only tool receipts. H08's note was in the prompt in four arms and "missing" for the scorer. The reply contradicted the note anyway.
4. **Arithmetic and time comparison are left to a 0.8B model.** H11: "10-hour window" for 10:30–11:30. H10: a rollback that never happened. The host had the numbers and did not compute the relation.
5. **Follow-ups resolve to the first service in the history, not the latest.** `HeuristicDecider` joins earlier user messages and takes `services[0]`. After "how's checkout" and "anything deployed to search?", "who approved that deploy" is answered for checkout. *Test.* The learned arm avoids the silent error only by asking for clarification (H25, H27), which the scorer counts as a failure too.

### Routing and escalation

6. **Escalation discards capability.** Below the confidence gate, `LearnedDecider` returns `call_model(heavy)`: a text generator that cannot call a tool or raise an approval. H18 and H19 were action requests. *Test* (the same request under the exit gate becomes an approval).
7. **The rules arm has the same defect by a different route.** "No rule matched; short general reply" sends anything unrecognised, including "roll it back", to the light model. *Test.*
8. **Most wrong decisions are confident.** 11 of 14. An uncertainty gate is the wrong instrument for a failure that is not uncertain.

### Verification

9. **The verification marker is recognised only at the start of a reply.** `text.upper().startswith("NEED_MORE_EVIDENCE")`. Three replies emitted it after prose. *Test.*
10. **The scorer ignores required evidence on compound action requests.** For `outcome: approval`, `required_facts` are never checked, so H30 ("pull the error trend, then roll back") passes without the read. *Test.* v0.7's scorer checks it and says so.
11. **Lexical grading counts some wrong replies as successes** (adjudication: 2 of 8 passes judged incorrect, none judged correct).

### Economics

12. **The controller re-reads the growing state at every step** and its scoring was not in the headline metric. Per attempted task the decision-driven arm computed 45% more tokens than the agent it was meant to be cheaper than.
13. **Deciding at every step pays for decisions that were already determined.** After `get_error_metrics` on a causal question, the next call is not a judgement; it follows from the question. v0.6 asked a model anyway, and the model sometimes got it wrong.
14. **Tool latency is zero in this world.** Any design that reads more looks free. v0.7 reports a sensitivity table instead of pretending otherwise.

## 3. Reformulating the question

v0.6 asked: *can a learned decision model choose each next operation as well as an LLM agent, more cheaply?* The evidence above says the framing is off in three ways.

- The failures that mattered were not about choosing the next operation. They were about **ending the turn**: finishing, or generating, before the evidence could support the reply. That is a property of the exit, and it can be checked without knowing who chose the steps.
- Where the next operation *was* the issue, it was usually **determined by the request** once its kind was known. A decision that is determined does not need inference.
- The one place uncertainty handling was built (escalation) removed the capability needed to handle the uncertain cases.

So the stronger formulation is:

> **Gate the exit, not every step.** Let any controller drive the turn. Before the turn may end, the host checks the reply's *kind* against an **evidence contract**: the classes of evidence that kind of reply requires for the entity in question, taken from tool receipts. If the contract is not met, the host names the missing calls, runs them without asking a model, and hands the turn back. An action the user asked for cannot be dropped at the exit. A generated reply that states values found in no receipt is not sent.

This turns "is a trained decision model needed?" into a measurable question: once the exit is gated, how much does the choice of controller still matter, and what does each controller cost?

**What would falsify it.** On new tasks: the gate does not reduce evidence-missing failures across controllers; or it breaks about as many tasks as it fixes (false holds, false clarifications, over-acquisition that confuses the model); or its benefit exists only for the controller it was developed alongside; or the gated learned controller still clearly beats gated rules, which would mean per-step learning carries value the gate does not replace. Any of these is a result. The pre-registration lists them as predictions with thresholds.

**What it cannot show here.** Every model in this repository is at most 0.8B parameters. A capable agent may already gather complementary evidence, in which case the gate would rarely fire and its value would be the cost of the check, close to zero, against a small safety margin. That is the Level C question and it is not answered by this study.

## 4. Directions considered

Scores are judgements, 1 (low) to 5 (high), made before the v0.7 run.

| Direction | Differentiation | Expected effect on success and serious failures | Effect on total cost and p95 | How it is disproved | Prospective evidence obtainable now | Complexity | Value to framework maintainers | Time to a runnable demonstration |
|---|---:|---|---|---|---|---:|---:|---|
| **A. Exit gate with evidence contracts, as a factorial over controllers** (chosen) | 4 | Targets the dominant v0.6 failure directly; should cut dropped actions | Adds tool calls and, for an agent, a regeneration; removes controller inference in the planner arm | Gate does not reduce evidence-missing failures, or breaks as much as it fixes | Yes: new tasks, pinned local models, paired design | 3 | 5: it is a hook, not a runtime | Days |
| B. Retrain the decision head with sufficiency features | 2 | Might fix sequencing on this world | Keeps per-step inference | Still fails on new wording | Partly: still confounded with training | 3 | 1: a head trained on this world | Days |
| C. Calibrated uncertainty and a better escalation threshold | 2 | Cannot reach confident errors (11 of 14) | Small | Already falsified by v0.6 P6 | Yes | 2 | 2 | Days |
| D. Hosted decision service as the controller (OpenAI Decisions, System One) | 3 | Unknown | Per-step paid calls | Needs spend | **No**: no credentials or approved budget | 2 | 3 | Blocked |
| E. Capable heavy model in every arm (Level C) | 5 | Decides the project's main hypothesis | Real provider economics | Hybrid not non-inferior | **No**: owner must approve model, margin and budget | 2 | 5 | Blocked on approval |
| F. Model-typed claims: one constrained scoring pass types the request instead of a lexicon | 3 | Could raise the planner's coverage | One short inference per turn instead of one per step | Typing accuracy no better than the lexicon | Yes, but better as a follow-up once A shows whether typing is the bottleneck | 3 | 3 | Days |

A was chosen because it is the only direction that (i) attacks the measured failure mechanism instead of the measured symptom, (ii) can be falsified now with what is available, (iii) answers the "is a trained decision model needed at all" question as a by-product, and (iv) yields something a framework maintainer could adopt in an afternoon. E is the experiment that matters most and is prepared, not run: the same gate and planner run against a hosted agent through [`turnwise_lab/v07/hosted.py`](../turnwise_lab/v07/hosted.py), tested against a fake server only.

## 5. Prior art (checked 2026-11-18)

A research subagent read the primary sources below (documentation pages and paper abstracts) on 2026-11-18; the three closest papers were fetched a second time to confirm title and claim. Full texts of the papers were not read. This is a check for overlap, not a survey.

**Frameworks can host such a gate; none ships one.**
- LangChain v1 middleware has `after_model` hooks that can jump back to the model or to tools, so a hook can refuse a final answer. Its documented guardrails end the run or replace the output; none requires specific tools or checks grounding ([custom middleware](https://docs.langchain.com/oss/python/langchain/middleware/custom), [guardrails](https://docs.langchain.com/oss/python/langchain/guardrails)).
- OpenAI Agents SDK output guardrails run on the final output and raise a tripwire: they halt, they do not continue with more evidence. "Continue until evidence holds" needs a host loop around the run ([guardrails](https://openai.github.io/openai-agents-python/guardrails/)).
- LlamaIndex Workflows let a custom step loop before `StopEvent`; the gate would be user code ([workflows](https://developers.llamaindex.ai/python/framework/module_guides/workflow/)).

**Routers choose a model, not an exit.** LiteLLM auto routing and its decision-model classifiers pick a tier from the request ([docs](https://docs.litellm.ai/docs/proxy/auto_routing)). vLLM Semantic Router's vision paper lists tool selection and hallucination detection as components ([arXiv:2603.21354](https://arxiv.org/abs/2603.21354)). FrugalGPT, RouteLLM and AutoMix are cascades over models ([2305.05176](https://arxiv.org/abs/2305.05176), [2406.18665](https://arxiv.org/abs/2406.18665), [2310.12963](https://arxiv.org/abs/2310.12963)). *Learning Compositional Meta-Routing for Agentic Workflows*, a benchmark in which logistic heads choose among answer, decompose, retrieve, execute, delegate and verify under a budget, is close to Turnwise's v0.6 premise ([2608.00106](https://arxiv.org/abs/2608.00106)).

**Decision models are now a commodity API.** OpenAI Decisions and TypeSafe System One exist and are wired into LangChain and LiteLLM ([guide](https://developers.openai.com/api/docs/guides/decisions), [API](https://docs.typesafe.ai/api), [LiteLLM decisions](https://docs.litellm.ai/docs/decisions)). Training a project-specific head is hard to defend as a contribution.

**Sufficiency before answering is studied mostly as a learned or LLM-judged signal.** Self-RAG, CRAG, FLARE, Adaptive-RAG ([2310.11511](https://arxiv.org/abs/2310.11511), [2401.15884](https://arxiv.org/abs/2401.15884), [2305.06983](https://arxiv.org/abs/2305.06983), [2403.14403](https://arxiv.org/abs/2403.14403)); *Sufficient Context* finds strong models tend to answer rather than abstain on insufficient context ([2411.06037](https://arxiv.org/abs/2411.06037)).

**Closest work.**
- *Before Reasoning Can Fail: Pre-Evidence Procedural Failures in Agentic RAG* evaluates **Read-Gate**, a runtime invariant (read after search, before finalising) that recovers accuracy on trajectories that would have skipped reading ([2608.02011](https://arxiv.org/abs/2608.02011)). A single invariant, not a typed contract.
- *From Evidence to Action: How Tool-Using Agents Fail* (SafeActBench): agents "stop with incomplete investigation or act before required evidence is established"; uses a provenance-bound evidence ledger and a deterministic trajectory evaluator ([2610.07753](https://arxiv.org/abs/2610.07753)). From the abstract, the ledger is an evaluator rather than a runtime gate.
- Receipt-based claim checking: NabaOS, ProvenanceGuard, Actions with Receipts ([2603.10060](https://arxiv.org/abs/2603.10060), [2606.18037](https://arxiv.org/abs/2606.18037), [2610.00327](https://arxiv.org/abs/2610.00327)).
- MAST's failure taxonomy includes premature termination and incomplete verification ([2503.13657](https://arxiv.org/abs/2503.13657)).

**What this leaves for Turnwise.** Not the idea of checking before answering. The contribution is narrower and empirical:
1. a **typed, two-sided evidence contract** derived from the kind of reply (a cause needs a symptom receipt *and* a change receipt for the same entity), enforced at the exit by host code that calls no model;
2. a **factorial measurement**: the same gate around a rules controller, a learned head and an LLM agent, against each of them ungated, with every controller token and every extra tool call counted;
3. the resulting answer to whether per-step learned control adds anything once the exit is checked.

The search did not find that combination measured. It was a bounded search; if you know of one, please open an issue.
