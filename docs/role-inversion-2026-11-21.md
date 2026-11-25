# Role inversion: the shielded native agent (arm S) as primary candidate, per-step control as challenger

**Dated note, 2026-11-21. Status of arm S: Implemented and tested (offline mechanism only). Status of the role inversion: Proposed in [#88](https://github.com/dgenio/turnwise-decision-lab/issues/88); it takes effect when the owner merges the change that adds this note.** It authorises no spend, provider call or outreach. It does not rewrite the 2026-11-19 architecture decision ([audit](architecture-fit-audit-2026-11-18.md)) or the hypothesis document; it is added beside them.

## What changes

Until now Turnwise Core was "the architecture to demonstrate and falsify", and *simple host rules plus the same capable agent* was a null to add later. From this note on:

- **Arm S, the shielded native agent, is the primary candidate.** The capable agent keeps its own loop and chooses its own operations. The host acts only where it already holds authority.
- **Turnwise Core (per-step control) is the challenger.** It stays on `main`, unchanged, and must beat S under the kill rule below.
- **S appears in every future comparison table** next to A (native agent) and Core. A table without S is incomplete.

S is the arm issue [#9](https://github.com/dgenio/turnwise-decision-lab/issues/9) calls R+G. This note fixes its definition.

## What arm S is

Code: [`examples/architecture/shield.py`](../examples/architecture/shield.py) (host side, stdlib only) and [`openai_agents/shielded.py`](../examples/architecture/openai_agents/shielded.py). Opt-in: `python -m examples.architecture.run_demo --shielded`. The default demo and `sample_output/` are unchanged.

| When | Who acts | What happens |
|---|---|---|
| Before the agent | Host rule, no model | A write the user plainly asked for is held for approval. A pure record question is answered from the verified incident record. A service-scoped question that names no service is asked, not guessed. Otherwise the host runs the reads its own evidence contract already requires for this question |
| During the agent | The model, in the framework's own loop | The same `Agent` as arm A, with every tool. It may batch calls, read more, or answer. Every tool call goes through `IncidentHost.execute`: unrequested writes are rejected, arguments are validated, the tool budget is enforced |
| At the exit | Host check | Receipts and claim screens on the finished answer. A rejected answer goes back to the agent with the reason, at most `max_feedback` times (default 1). If it is still rejected, the run ends as unresolved and the answer is not sent |

Optional: `typed_citations=True` changes only the agent's final output type to text plus cited receipt ids, and the exit check then verifies the citations.

**S is not Turnwise Core** and must not carry that name: the model, not a policy, regains control after each observation (invariant 1 in [`AGENTS.md`](../AGENTS.md) does not hold for S, by design). A test checks that S imports no policy, decision or runtime class from the core.

## What S gives up

- **No per-step light or heavy choice.** A provider effort setting or a router can stand in.
- **Less control over what the model sees at each step.** The agent sees its whole conversation.
- **No guarantee that a typed step contract is followed**, because there is none: the agent answers in its own format unless typed citations are switched on.

## Why: evidence in this repository

| Evidence | What it says | Limit |
|---|---|---|
| Archived v0.7 study ([PR #38](https://github.com/dgenio/turnwise-decision-lab/pull/38), frozen at `e3bde98`; [#75](https://github.com/dgenio/turnwise-decision-lab/issues/75)) | A host check at the exit cut replies sent on missing evidence from 44 to 15 across three controllers. Behind that check, hand-written rules matched a trained per-step head at 6% of its model tokens | 0.8B local model. Nothing follows for capable agents |
| Same study, blinded adjudication | The exit check did **not** improve what the weak agent then wrote: 18 of 20 investigations got the same grade with and without it | Two LLM graders, no human |
| Same study, task L56 | A lexical "action latch" that synthesised approval requests raised one for the wrong service | This is why S has no latch: the host holds only a write that `requested_writes` accepts, and reports everything else as not requested |
| Same study, narration arm | A reply can cite only grounded values and still state the wrong relation between them | This is why the exit check is described as provenance, never as a truth check |
| `experiment/sonnet55-strong-simple-null` (`0a5000c`, unmerged, simulated model) | The predecessor of S met the arm-agnostic required behaviour on 9 of 11 authored scenarios, 10 of 11 with typed citations; Core met 10 of 11 | Simulated; scenarios and arms share an author |
| Stage 0 ([#86](https://github.com/dgenio/turnwise-decision-lab/issues/86), [results](../research/stage0_headroom/RESULTS.md), [amendment 1](../research/stage0_headroom/RESULTS-AMENDMENT-1.md)) | On public capable-agent trajectories a strict host-rule oracle removed 0.0% to 0.3% of estimated cost. The economic case for removing model turns is not supported | Re-priced trajectories, hindsight ceilings |
| `policies.py` and `incident_env.py` on `main` | The demonstration policy's playbook and the host's `required_evidence_roles` encode the same rule twice. With a rule policy, Core and "host rules" are nearly the same program | Observation about this demo only |

External sources are listed in #88 and in the [archived research audit](research-audit-2026-11-21/README.md). They are not repeated here and were not re-verified for this note.

## Offline mechanism observations on `main` (simulated model; not a result)

OpenAI Agents SDK, the four demo tasks, one run each. These are operation counts in one simulated run. They are not cost, latency or quality, and the simulated native agent calls one tool per turn, which overstates A's model calls against an agent that batches.

| Task | A native | Core | S |
|---|---|---|---|
| `investigate` | completed; 4 model calls; 3 host tool requests | finished; 6 policy decisions; 2 model calls; 3 host tool requests | finished; 2 model calls; 3 host tool requests, 2 of them read by the host first |
| `status` | completed; 2; 1 | finished; 3 policy decisions; 1; 1 | finished; 1; 1 |
| `severity` | completed; 1; 0 | answered directly; 1 policy decision; 0; 0 | answered directly; 0; 0 |
| `rollback` | completed; 2; 1 held | held; 2 policy decisions; 0; 1 held | held; 0; 1 held |

On these four tasks S reaches the same terminal state as Core with the same number of model calls and no policy calls. That is what the mechanism predicts when the policy's playbook and the host's evidence contract are the same rule. It says nothing about which is better with a real model.

Known behaviours of S, pinned by tests in [`tests/test_architecture_shielded.py`](../tests/test_architecture_shielded.py):

- A negated request such as "Do not roll back checkout. Is checkout healthy?" can end unresolved: the shared claim screen is deliberately broad and refuses a truthful "no rollback was performed". Core has the same screen.
- A model that cites every receipt and ignores them passes the typed exit check. So does Core's `FINISH`.
- A provider failure ends the run as a named failure after one call. Receipts are kept and nothing is retried.
- Returning a reason to the agent grants nothing: a write proposed after a rejection is still rejected by the host.
- A failed run reports the model requests it made, and an empty answer is never accepted (both added 2026-11-25, see below).

## Added 2026-11-25: a second implementation of S exists, and what comparing the two found

[PR #101](https://github.com/dgenio/turnwise-decision-lab/pull/101) implements the same issue. It was written separately, from the same issue text and the same predecessor branch, so the two are not independent in any statistical sense. The same 54 scripted cases were run against both (the four demo tasks, 13 further requests, each plain and typed, and 20 scripted model behaviours). 40 gave the same status, answer, receipts and counts. The 14 that differed come from three causes, and three defects were found, two of them in **both** implementations. Nothing here involves a real model.

| Finding | Where | State in this change |
|---|---|---|
| A run that raises (provider failure, step limit, malformed typed output) reported `model_calls = 0` although one to three requests had been made. `AGENTS.md` asks for every call to be counted and for unmeasured values to be `unknown`, never `0`. The kill rule compares billed cost, so this undercounts S exactly where it fails | Both | Fixed: requests are counted as the SDK starts them (`RunHooks.on_llm_start`), so a failed run reports them |
| An empty or whitespace-only answer was accepted as `finished`. Core refuses an empty answer candidate in `parse_outcome`, so S was the weaker gate here | Both | Fixed: status `empty_answer`; the answer goes back to the agent like any other rejection |
| The reason shown to the user quoted receipt ids the agent had declared, which is agent-written text | This implementation only | Fixed: the user-facing reason is host-authored; declared ids go to the trace and back to the agent |
| A negative feedback bound raised `AttributeError` after the host had already run its reads | #101 only | Not applicable here (`ValueError` before anything runs) |
| The default simulated model does not speak the typed format, so `typed_citations=True` with it ends as `native_agent_failed` | This implementation only | Not changed. #101 teaches the simulated model and the provider double the typed format and makes typed the default |

One behaviour is shared by typed S and by Core and is pinned by a test, not fixed: a record question that names a service ("What is the severity of the checkout incident?") has no host rule and no required evidence role. The unmodified agent and plain S answer it. Typed S refuses the answer for citing nothing, and Core ends `held` on the same request with the simulated model. A rule that every accepted answer cites a receipt makes a question with an empty evidence contract unanswerable unless the agent reads something it does not need.

Not fixed, and not specific to S: the host's approval-claim screen on `main` matches "awaits approval" and "pending approval" but not "awaiting approval", so an answer that says a rollback "is awaiting human approval" when nothing is held passes in both implementations. The screen is documented as narrow and lexical.

## Kill rule (pre-declared in #88, copied unchanged)

On the comparison run under #9, with the same model, tools, host and budgets:

- **Retire per-step control as the canonical architecture** (keep it as a documented negative result) if S is non-inferior to Core on task success and on critical failures, and S's billed cost is not higher.
- **Keep Core for a named family only** if it beats S there by the pre-declared margin and loses or ties elsewhere.
- **Keep Core as primary** only if it is non-inferior to S on success and safety and at least 15% cheaper in billed cost, or strictly safer at equal cost.
- **Inconclusive** if the run is underpowered. No architecture claim either way.

The margin, the critical-failure ceiling and the spend cap are owner decisions under #9 and are not set here.

## The three families where Core could still win (written down before any live run)

Core cannot be rescued after the fact by a family chosen once the results are in. These three are declared now. A task belongs to a family by the rule in the second column, applied by the task author or the benchmark's own labels before any arm runs.

| Family | Membership rule | Why per-step control might win | What would count |
|---|---|---|---|
| **1. Policy-adherence dialogue** | The task's success depends on following a written procedure across several turns (for example τ-bench retail and airline policy rules), and the benchmark scores the final state against that procedure | A policy that owns the loop can refuse an out-of-procedure step before the model takes it; a shield only sees tool calls and the exit | Core beats S on task success or pass^k in this family by the pre-declared margin, with critical failures not higher |
| **2. Clarification timing** | The request is under-specified in a way the task author labels as "must ask before acting", and asking late is scored as a failure | A controller that sees the step index can ask at step 0; a native agent tends to ask late or not at all | Core asks within the labelled window more often than S by the pre-declared margin, without more false clarifications on fully specified tasks |
| **3. No-model tasks** | The gold label says the task is answerable from a verified record or a single deterministic read, with no generation needed | Core can end the turn with zero model calls by construction | Core's billed cost in this family is at least 15% lower than S's at non-inferior success. Note that S also answers record questions and holds plain writes with no model call, so the difference can only come from tasks S hands to the agent |

Outside these families, a Core win was not predicted and is reported as exploratory.

## What this note does not show

- Nothing here is a result with a real model. S, like Core, has only been exercised with a simulated model on `main`.
- The exit feedback loop is new in S and has no evidence of benefit. The one related measurement (archived v0.7, weak model) found that handing evidence back did not improve the reply.
- S exists for the OpenAI Agents SDK only. A LlamaIndex binding is not written; `run_demo --shielded --framework llamaindex` says so and exits.
- The optional variant S-par from #88 (prefetch concurrently with the first model call) is not implemented.
