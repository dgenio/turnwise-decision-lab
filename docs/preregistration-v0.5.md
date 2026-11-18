# Pre-registration: outcome-scored per-turn routing (v0.5)

**Committed before any v0.5 experiment code, session fixture or router existed.** Git history is the timestamp. Anything changed after the first scored run is listed in the report's `post_freeze_changes` field.

## Why v0.4's benchmark could not answer the question

v0.4 scored *route labels* written by the same person who wrote the rules. That design has three structural problems:

1. `direct` was defined by the presence of a `verified_answer` field, so every arm that read the field got 8/8 by construction.
2. Agreement with a label is not an outcome. A route can match its label and still return the wrong data, or fail to match and still serve the user.
3. Only the execution path was scored. Context selection and tool arguments, which are the parts the "joint routing" thesis is actually about, were never evaluated. (The harness also discarded the plan's context selection at execution time.)

## Design

A closed, deterministic, synthetic incident world: four services, real Python read tools and flows, three side-effecting actions that the harness must refuse, a small document store and a few host-verified facts. Multi-turn sessions, written as a human investigator would type them, include elliptical follow-ups, compound questions, risky-sounding reads, paraphrased writes, negations and a reference that can only be resolved by reasoning.

**Turns are labelled with outcomes, not routes.** Each turn declares the *facts* a correct answer needs (`health:checkout`, `doc:rb-timeouts`, `fact:incident_id`, ...) and a mode:

- `lookup`: showing the needed facts answers the question.
- `synthesis`: the needed facts must be interpreted by a model.
- `action`: the user asks for a side effect; the correct outcome is an approval hold, never an execution.

Any path that produces the needed outcome is scored as correct. No arm is told which route is "right".

### Outcomes (all computed mechanically)

| Outcome | Meaning |
|---|---|
| `resolved` | Deterministic execution produced every needed fact for a lookup. No model call. |
| `silent_miss` | Deterministic execution returned data that does **not** answer the turn (wrong tool, wrong entity, partial compound answer, or raw data where an explanation was needed). The harness receipt still says `completed`. |
| `ready` | A model call was made with every needed fact already in its context. |
| `ready_after_tools` | A model call lacked evidence and needed an extra tool round (assumed to fetch exactly the right facts). |
| `insufficient` | A model call lacked needed evidence and had no tool able to fetch it. |
| `held` | An action turn raised an approval hold (or was refused because no capability exists). Nothing executed. |
| `false_hold` | A non-action turn was blocked. |
| `unauthorized_execution` | A side-effecting handler ran. Must be zero. |

### Arms

| Arm | Path decision | Context for model calls |
|---|---|---|
| `agent_baseline` | Every turn goes to a model with **all** tools exposed (a conventional tool-calling agent). | Conversation history, oldest dropped first to fit the budget; missing facts are fetched by tool rounds. |
| `stateless_router` | v0.4's frozen regex rules applied to the latest message only; anything it cannot map falls through to `agent_baseline`. | Same as `agent_baseline`. |
| `joint_router` | Rules over the latest message **plus session state** (carried entities and last capability); capability matching against the catalog; side-effects detected from capability metadata, not from verbs. | Route-aware packet: evidence gathered by this turn's deterministic prefetch, facts carried from earlier turns, and documents retrieved using both the turn text and the gathered evidence. Read tools stay available as a fallback. |
| `joint_no_state` | Ablation: `joint_router` with no carried entities or capabilities. | Same as `joint_router`. |
| `joint_lexical_context` | Same path decisions as `joint_router`. | Ablation: only this turn's prefetched evidence plus documents retrieved by the turn text (v0.4-style lexical packing). |
| `learned_nb_path` | v0.4's Naive Bayes, trained on v0.4's 60 route prompts (out of distribution for these sessions), chooses the path; everything else uses `joint_router` machinery. | Same as `joint_router`. |
| `oracle` | Cheapest path that succeeds on each turn, chosen with knowledge of the answer. Upper bound, not a policy. | Exactly the needed evidence. |

A separate red-team run uses a **compromised router** that forges an approved plan to execute every requested write.

### Deliberate biases in favour of the baseline

- The agent is assumed to call exactly the right tools, in parallel, in one extra round. Real agents misselect tools, especially with large catalogs.
- Generated answers are not simulated and are excluded from every arm's history. This understates the agent's context growth.
- Whenever a model call has (or can fetch) the needed evidence, it is counted as able to succeed. Answer quality is **not measured**.

If routing still loses under these assumptions, that is a negative result for the thesis.

### Metrics

Measured: outcomes above per turn and per turn family; model calls (total and per turn, including tool rounds); router invocations; deterministic handler executions; characters of context and tool schemas sent to model calls; evidence sufficiency of the route-aware packet; sequential model calls on each turn's critical path; local Python wall time (not provider latency).

**Not measured:** answer quality, token counts, dollars, provider latency, calibration, any live router (LiteLLM, vLLM Semantic Router, Jev, provider tool search). Prices appear only as user-adjustable inputs in the explorer, never as results.

Default context budget: 2,400 characters of evidence/history per model call (tool schemas counted separately), with a sweep over 600, 1,200, 2,400, 4,800 and 9,600.

## Hypotheses and predictions

| ID | Hypothesis | Prediction | Falsified if |
|---|---|---|---|
| H1 | Headroom exists: many turns need no model at all. | The oracle answers ≥30% of turns with zero model calls. | Oracle zero-call share < 30% on this workload. |
| H2 | **Route depends on context (state).** A message-only router cannot route follow-ups. | `joint_router` resolves ≥75% of follow-up lookups deterministically; `stateless_router` and `joint_no_state` resolve ≤25%. | The gap is under 25 percentage points. |
| H3 | **Context depends on route.** Evidence gathered by the execution path improves the context packet. | Route-aware packets contain every needed fact for ≥80% of synthesis turns; `joint_lexical_context` for ≤50%. | Gap under 20 points. |
| H4 | **Skipping the model creates silent failures.** | Every router that saves model calls produces ≥1 `silent_miss`. | Some saving router has zero silent misses. |
| H5 | **Safety lives in the harness, not the router.** | Zero unauthorized executions in every arm, including the compromised router; v0.4's verb regex produces ≥2 false holds and misses ≥1 paraphrased write that the harness still holds. | Any unauthorized execution, or the regex adds no false holds. |
| H6 | v0.4's learned classifier does not transfer. | `learned_nb_path` has more silent misses + false holds than `joint_router`. | It has fewer. |
| H7 | Exchange rate. | No prediction. Report model calls saved per failure for each arm versus `agent_baseline`. | n/a |

## Threats to validity, stated in advance

- One author wrote the world, the sessions, the needed-fact annotations and every router. Routers are frozen before the first scored run, and the session file's SHA-256 is recorded, but that does not remove authoring bias. Families designed to break each arm, including `joint_router`, are included on purpose.
- The workload mix decides the aggregate numbers. Results are therefore also reported per turn family so readers can reweight to their own traffic.
- About 50 turns: report counts, not confidence intervals that the sample cannot support.
- The optimistic generation assumption hides any model failure, including tool misselection by the baseline agent.
