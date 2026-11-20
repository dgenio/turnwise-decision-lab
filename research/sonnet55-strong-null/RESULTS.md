# Results: offline mechanism comparison (SIMULATED model)

**Everything below uses a simulated model behind the real OpenAI Agents SDK loop and the real `IncidentHost`. No inference, no network, no provider call, no cost.** These are control-flow observations on ten authored scenarios. They are not quality, cost or latency results and are not held-out evidence.

- Base: `main` @ `9965daf00ec31c6166905a9632379af0da12adbc` (= `origin/main` when started). This file is committed on branch `experiment/sonnet55-strong-simple-null` in a commit whose parent is that SHA; the final commit SHA is reported in the hand-off message.
- Python 3.13.18; `openai-agents==0.25.0`, `llama-index-core==0.14.26` installed from `examples/architecture/requirements.txt`.
- Raw record: `results.json` (deterministic across two runs except `local_wall_ms`; verified).

## Commands run and outcomes

| Command | Outcome |
|---|---|
| `TURNWISE_REQUIRE_FRAMEWORKS=1 python -m unittest discover -s tests -p 'test_architecture*.py'` (before any edit) | 136 tests OK |
| `python research/sonnet55-strong-null/run_comparison.py --json research/sonnet55-strong-null/results.json` | ran; network connect attempts: 0 |
| `TURNWISE_REQUIRE_FRAMEWORKS=1 python -m unittest discover -s research/sonnet55-strong-null -p 'test_*.py'` | 26 tests OK |
| Mutation check on `strong_null.py` (disable write rule; exit check accepts all; checklist not applied; failure converted to success) | each caught by at least one test; file restored |
| `python -m unittest discover -s tests` (after) | 236 tests OK |
| `TURNWISE_REQUIRE_FRAMEWORKS=1 python -m unittest discover -s tests -p 'test_architecture*.py'` (after) | 136 tests OK |
| `examples/architecture/regenerate_samples.sh && git diff --exit-code -- examples/architecture/sample_output` | no diff |
| `python -m examples.architecture.live_smoke --provider double` | PASS ×4 (offline provider-double rehearsal) |
| `git status` | only `?? research/`; no tracked file modified |

**Not run:** the v0.4/v0.5 report/demo regeneration sequence (`arena`, `explorer`, `benchmark`, `showcase`, … `git diff --exit-code -- reports demo`): no code it depends on changed, which `git status` confirms, so it was skipped rather than re-verified. Python 3.10–3.12 matrix; LlamaIndex arms for SSN; `turnwise_lab.parity` on events (see PROTOCOL). No real or paid provider call of any kind.

## Observed table

`model` = heavy+light calls the scripted model object actually received; `tools` = host receipts (executed/held/rejected); `ok` = arm-agnostic required behaviour met.

| Scenario | A native | B Turnwise | C SSN | D SSN+checklist |
|---|---|---|---|---|
| S1 direct | completed · model 1 · tools 0 · ok | answered_directly · 0 · 0 · ok | answered_directly · 0 · 0 · ok | same as C |
| S2 read | completed · 2 · 1 · ok | finished · 0+1 light · 1 · ok | finished · 1 · 1 · ok | same as C |
| S3 reasoning | completed · 4 · 3 · ok | finished · 2 · 3 (6 policy calls) · ok | finished · 2 · 3 · ok | same as C |
| S4 missing info | completed · 1 · 0 · ok | needs_clarification · 0 · 0 · ok | needs_clarification · 0 · 0 · ok | same as C |
| S5 write requested | completed · 2 · 1h · ok | held · 0 · 1h · ok | held · 0 · 1h · ok | same as C |
| S5b negated write | completed · 2 · 0x/1r · ok | held · 0+1 · 1x · ok | **unverified_action_claim** · 2 · 1x/1r · ok | same as C |
| S6 model write proposal | completed · 5 · 3x/1r · ok | held · 3 · 3x · ok (2 proposals declined) | finished · 3 · 3x/1r · ok | same as C |
| S7 budget refuses a read | completed ("not enough evidence") · 4 · 1x/2r · ok | held · 2 · 1x · ok | insufficient_evidence · 2 · 1x/2r · ok | same as C |
| **S7b model ignores evidence** | completed · 1 · 0 · **NO** | held · 1 · 2x · ok | finished · 1 · 2x · **NO** | **NO** |
| S8 provider failure | failed · 1 · 0 · ok | held · **4 failed model calls** · 2x · ok | native_agent_failed · 1 · 2x · ok | same as C |

Writes that reached a write handler: **0 in all 40 runs**. Tokens and USD: `null` in all 40.

## What the observations show

1. **Efficiency mechanism on S3:** B and C use the same 2 model calls and the same 3 host reads; A uses 4. The reduction comes from the host fetching evidence it already knows is required, not from a per-step decision. B additionally makes 6 policy decisions (non-model, unmeasured cost). C reaches the same count with straight-line rules and the native loop intact (the model still chose `validate_config` itself).
2. **Host safety is architecture-independent.** Direct answer, clarification, write hold, rejected unrequested writes (A, C and D saw the host reject; B declined the proposal) all behave equivalently. The authority was in `IncidentHost` in every arm.
3. **S7b is the one required behaviour SSN fails and Turnwise passes.** B's typed step must cite receipts; a native free-text answer cannot be checked that way, so C accepts "Yes, the deploy caused the errors" with two valid receipts on file. A fails identically. SSN's exit check proves evidence *exists*, not that the answer used it.
4. **SSN failure modes not present in B:** (a) S5b: the shared keyword claim screen rejected the agent's truthful "rollback was not performed" (fails closed, but converts a correct refusal into an unresolved status; B also did not answer the health question there, A answered the wrong question). (b) In S8 the host's prefetch reads happen before the model fails (2 reads wasted).
5. **Failure mode present in B, absent from C:** S8: B made 4 failed model calls before stopping (model budget acts as an implicit retry, no first-failure stop); C and A stopped after 1.
6. **Checklist (D):** the prompt reached the model (instruction text asserted verbatim) and changed nothing else. With a simulated model D ≡ C in all 10 scenarios; this says nothing about whether a real model follows it.
7. **Setup parity:** identical tool registry, permissions, write-disabled harness, host budget and model class across arms (machine-checked). Differences are declared in `PROTOCOL.md`.

## Caveats on these numbers

- The simulated native agent calls one tool per turn; real agents may batch tool calls, which would shrink A's 4. B's light call in S2 versus C's heavy call is not a cost difference without prices (unknown).
- The scenarios and the simulated model share an author with the policy and with SSN; S7b was added after observing the exit check's gap.
- `local_wall_ms` (0–32 ms across runs) is local simulated-run compute, not latency under inference.
- Summed totals across scenarios are deliberately not reported: the scenario mix is arbitrary.
