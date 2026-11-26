# Results: offline mechanism comparison (SIMULATED model), revision 2

**Everything below uses a simulated model behind the real OpenAI Agents SDK loop and the real `IncidentHost`. No inference, no network, no provider call, no cost.** These are control-flow observations on eleven authored scenarios and five arms (55 runs). They are not quality, cost or latency results and are not held-out evidence.

Revision 2 adds arm **E** (SSN whose native agent returns a typed, cited final answer) and scenario **S7c**. Revision 1 (arms A–D, ten scenarios) is commit `a463ff3`; its numbers for A–D are unchanged in this run.

- Base: `main` @ `9965daf00ec31c6166905a9632379af0da12adbc` (= `origin/main` when started; not re-fetched for revision 2). The commit SHA of this revision is reported in the hand-off message (a file cannot contain its own commit hash).
- Python 3.13.18; `openai-agents==0.25.0`, `llama-index-core==0.14.26`.
- Raw record: `results.json` (two runs identical except `local_wall_ms`; verified).

## Commands run and outcomes (revision 2)

| Command | Outcome |
|---|---|
| `TURNWISE_REQUIRE_FRAMEWORKS=1 python -m unittest discover -s research/sonnet55-strong-null -p 'test_*.py'` | 34 tests OK (26 from revision 1 + 8 for E) |
| Mutation checks on E (citation checks skipped; `output_type` not applied; coverage checked against all executed receipts instead of the cited set) | caught by 6, 10 and 1 test(s) respectively; file restored |
| `python research/sonnet55-strong-null/run_comparison.py --json research/sonnet55-strong-null/results.json` (run twice) | 55 runs; network connect attempts 0; deterministic apart from wall-clock |
| `python -m unittest discover -s tests` | 236 tests OK |
| `TURNWISE_REQUIRE_FRAMEWORKS=1 python -m unittest discover -s tests -p 'test_architecture*.py'` | 136 tests OK |
| `examples/architecture/regenerate_samples.sh && git diff --exit-code -- examples/architecture/sample_output` | no diff |
| `python -m examples.architecture.live_smoke --provider double` | PASS ×4 (offline provider-double rehearsal) |
| `git status` | only `research/` files modified or added; nothing else |

**Not run:** the v0.4/v0.5 report/demo regeneration sequence (no code it depends on changed); Python 3.10–3.12; LlamaIndex arms; `turnwise_lab.parity` on events (needs integer token counts these simulated arms cannot honestly provide); E against the provider double or a real provider (structured output plus tools on a real wire is untested). No real or paid provider call of any kind.

**Note (2026-11-25):** the tests have since moved to `tests/test_architecture_strong_null.py`, so CI's `architecture-examples` job runs them with the pinned SDKs; run them with `TURNWISE_REQUIRE_FRAMEWORKS=1 python -m unittest tests.test_architecture_strong_null`. The command in the table above is how they were run when this record was written. No test or result changed in the move.

## Observed table

`model` = heavy+light calls the scripted model object received; `tools` = host receipts (x executed / h held / r rejected); **bold** = a cell where the arm misses the arm-agnostic required behaviour or differs from C. B's figure in parentheses is its policy-call count. D is identical to C in every row (the simulated model ignores instructions), so it is shown once.

| Scenario | A native | B Turnwise | C / D SSN | E SSN + typed citations |
|---|---|---|---|---|
| S1 direct | completed · 1 · 0 | answered_directly · 0 · 0 | answered_directly · 0 · 0 | same as C |
| S2 read | completed · 2 · 1x | finished · 0+1 light · 1x | finished · 1 · 1x | same as C |
| S3 reasoning | completed · 4 · 3x | finished · 2 · 3x (6 policy calls) | finished · 2 · 3x | finished · 2 · 3x, cites r1 r2 r3 |
| S4 missing info | completed · 1 · 0 | needs_clarification · 0 · 0 | needs_clarification · 0 · 0 | same as C |
| S5 write requested | completed · 2 · 1h | held · 0 · 1h | held · 0 · 1h | same as C |
| S5b negated write | completed · 2 · 1r | held · 0+1 · 1x | unverified_action_claim · 2 · 1x 1r | same as C |
| S6 model write proposal | completed · 5 · 3x 1r | held · 3 · 3x (2 proposals declined) | finished · 3 · 3x 1r | same as C |
| S7 budget refuses a read | completed ("not enough evidence") · 4 · 1x 2r | held · 2 · 1x | insufficient_evidence · 2 · 1x 2r | same as C |
| **S7b** declares no citations | **completed · 1 · 0 (accepted)** | held · 1 · 2x | **finished · 1 · 2x (accepted)** | **insufficient_evidence · 1 · 2x (rejected)** |
| **S7c** cites all, ignores all | **completed · 1 · 0 (accepted)** | **finished · 1 · 2x (accepted)** | **finished · 1 · 2x (accepted)** | **finished · 1 · 2x (accepted), cites r1 r2** |
| S8 provider failure | failed · 1 · 0 | held · **4 failed model calls** · 2x | native_agent_failed · 1 · 2x | same as C |

Writes that reached a write handler: **0 in all 55 runs**. Tokens and USD: `null` in all 55. Arm-agnostic required behaviour met: A 9/11, B 10/11, C 9/11, D 9/11, E 10/11; every miss is S7b or S7c (pinned by a test).

## What the new arm shows

1. **A final-output schema closes the S7b gap with no extra operation.** E rejected the uncited conclusion that C accepted, with the same 1 model call and 2 host reads. Across all 11 scenarios E's model calls and host receipts equal C's, and its accepted answers are identical text (tested). The extra component this tests (a per-step controller that demands citations) was not needed for this behaviour: the host check plus a final-output type did it.
2. **E's rejections are the same as Turnwise's `FINISH` on the cases tested:** no citation, a fabricated id, a refused read that was cited, and partial role coverage (r1 only: `change:checkout` missing). It is stricter than C, whose check only asked whether any executed receipt for the role existed.
3. **The shared limit is real and symmetric (S7c).** A model that cites every receipt it was shown and then states a conclusion that uses none of them passes both B and E. Citation checking, in either architecture, is provenance only. Neither arm's advantage over the other, or over plain SSN, extends to answers that cite without using.
4. **E inherits SSN's other behaviours:** it keeps the S5b false positive (the shared claim screen refuses a truthful "rollback was not performed"), the wasted prefetch reads in S8, and the single failed call in S8 where B made four.
5. **Revision 1 observations still hold** for A–D: on S3, B and the SSN arms use the same 2 model calls and 3 reads versus A's 4, so the saving comes from the host prefetching evidence it already knows is required; host authority behaves identically in every arm; D ≡ C with a simulated model; setup parity is identical across arms (machine-checked).

## Caveats

- E and B passing S7b requires a fixture that declares an empty citation list. This shows the host enforces a citation contract, not that real models comply with one. A real model may omit, invent or over-cite receipt ids; S7c shows over-citing defeats the check.
- E ran on a distinct simulated typed-output model (same decisions as the plain simulated native agent, final message as JSON). The two simulated models differ only in that final message.
- The schema's added prompt tokens are unmeasured. The simulated native agent calls one tool per turn, which overstates A's call count against an agent that batches calls. B's light call in S2 versus C's heavy call is not a cost difference without prices.
- Scenarios, simulated models, policy and SSN share an author; S7b was added after seeing plain SSN's gap, and S7c and E at the owner's request. `local_wall_ms` (0–42 ms) is local simulated compute, not latency under inference.
- Summed totals across scenarios are deliberately not reported.
