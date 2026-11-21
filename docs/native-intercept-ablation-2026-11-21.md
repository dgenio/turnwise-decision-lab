# The native-intercept model port (B'), 2026-11-21

**Status: Demonstrated with simulated inference (structural).** Offline, provider double, simulated replies, synthetic token counts. An **ablation of how the model is asked**, opt-in, for the OpenAI Agents SDK pair. It is not the canonical Turnwise Core arm, it is not a cost measurement, and it says nothing about quality or about how a real model behaves. Issue: [#87](https://github.com/dgenio/turnwise-decision-lab/issues/87), which calls these arms C and C'; on `main` the Turnwise Core arm is **B**, so the new one is **B'**.

## Why this exists

Turnwise Core (arm B) asks the model for one typed `StepOutcome` with no tools attached. That buys the property the hypothesis needs: **nothing a model emits is executed without a policy decision and host validation**. It also changes four other things at the same time:

| Bundled with arm B | Consequence |
|---|---|
| One proposal per model call | k model-chosen reads cost k model calls plus one |
| A fresh packet for every call, no conversation | Less of each request repeats the previous one |
| Tools described as text inside the input | Tool schemas leave the provider's `tools` field; the base instructions say "use the tools" and the step contract says "no tool is callable" |
| A tool call written as JSON inside a string | Not the format providers train and optimise for |

Any difference measured between the conventional agent (A) and Turnwise Core (B) therefore mixes "who controls" with "how the model is asked". B' holds the first constant and changes only the second.

## What B' is

The same `TriagePolicy`, the same host and the same loop as arm B. `NativeInterceptRuntime` replaces one method of `TurnwiseRuntime`, the model call; `run`, `host_validates`, the tool execution path and the `FINISH` checks are inherited unchanged, and a test asserts it.

1. The model is called with the provider's real `tools` field and an appended conversation. Its typed final reply is a `StepAnswer` (an answer with citations, or "needs evidence").
2. **Every tool call in a response comes back to the policy as a `tool_proposal`.** The policy is asked about each one in order. The model call executes none of them.
3. An adoption (`CALL_TOOL ... adopted_from=...`) is validated and executed by the host exactly as in arm B. A call the policy does not adopt is answered `declined by policy: <reason>`, because the API requires every call to be answered.
4. Results the host obtained itself are appended as messages that start with `HOST RESULTS`.

On the OpenAI Agents SDK this uses the documented approval seam and only public APIs. Every tool on the step agent is **inert** and marked `needs_approval=True`, so the SDK pauses the run before any tool runs and returns the tool calls as `interruptions`. When the policy next calls the model, an adopted call is approved and its inert tool hands back the receipt the host already produced; a declined call is rejected with the reason. The SDK then makes exactly one more model call. The inert tool cannot execute anything. If it is ever invoked with no host result waiting, it says so and records the event; the tests assert that record stays empty.

**Several proposals in one response.** For each proposal the runtime calls `policy.decide` with that proposal as the latest observation. Only an adoption acts. Any other decision is read as "declined, for this reason" and is not carried out; when every proposal has been considered, the ordinary loop asks the policy for its next move. A terminal decision ends the phase at once. A policy written for arm B therefore works unchanged, and every such call is counted as a policy decision.

**The tools field is fixed per conversation**, at the set the policy offers on the first model call. It is the start of the cacheable prefix. A later, narrower `may_propose` does not change it: a call to a tool the policy no longer lists is still only a proposal, and the policy declines it. A later *wider* offer is refused visibly and nothing is sent.

## Invariant 2 needs an owner decision

`AGENTS.md` invariant 2 says a model step "runs with no tools". B' sends a `tools` field, so **it is labelled as an ablation and not as Turnwise Core** in code, traces and docs. What it preserves is the narrower property in bold above, and invariant 1 is untouched: the policy regains control after every observation, including each proposal.

#87 proposes rewording invariant 2 to "no model output is executed without a policy decision and host validation". **That wording has not been changed here.** It is the owner's call.

## Offline table

Produced on 2026-11-21 with openai-agents 0.25.0, llama-index-core 0.14.26, llama-index-llms-openai 0.9.0, openai 3.57.0, pydantic 2.14.4. Request sizes depend on how those packages serialise requests, so this is a dated snapshot and is **not** compared byte for byte in CI; the tests pin the mechanisms. **k** is the number of the task's three evidence reads that the *model* chooses under the Turnwise arms; the policy's playbook reads the other `3 - k` first. Arms A and A' have no policy, so the model always chooses all three. B' is reported twice because this repository cannot know whether a model batches its tool calls.

```text
How the model is asked, held apart from who controls | PROVIDER DOUBLE (simulated responses; no inference performed)
SIMULATED, structural: request shapes come from the offline provider double, token counts are synthetic and replies are simulated. Arithmetic under stated assumptions, NOT a cost measurement.
scenario 'investigate' | framework openai-agents | price card: input $2, cached input $0.1, cache write $2.5, output $10 per MTok (docs/live-smoke-decision-packet.md (gpt-6.1-sol; prices read 2026-11-19))
cost columns: the same stable 5000-token prefix added to every request of every arm; minimum cacheable length 1024 tokens. Arithmetic, NOT a cost measurement.

=== native arms: the model chooses all three reads (no policy) ===
arm       |   k | requests | calls/response | prefix of previous     | policy decisions | no caching | cache reads | reads + write price
A         | all |        4 |              1 | -, 82%, 83%, 86%       |             none |    0.04976 |     0.01663 |             0.01970
A'        | all |        2 |              3 | -, 59%                 |             none |    0.02623 |     0.01549 |             0.01855

=== k = 1: the model chooses 1 of the three reads; the policy's playbook reads 2 first ===
arm       |   k | requests | calls/response | prefix of previous     | policy decisions | no caching | cache reads | reads + write price
B         |   1 |        2 |              0 | -, 60%                 |                6 |    0.02756 |     0.01667 |             0.02003
B' seq    |   1 |        2 |              1 | -, 86%                 |                6 |    0.02621 |     0.01487 |             0.01793
B' batch  |   1 |        2 |              1 | -, 86%                 |                6 |    0.02621 |     0.01487 |             0.01793

=== k = 2: the model chooses 2 of the three reads; the policy's playbook reads 1 first ===
arm       |   k | requests | calls/response | prefix of previous     | policy decisions | no caching | cache reads | reads + write price
B         |   2 |        3 |              0 | -, 50%, 60%            |                7 |    0.04093 |     0.01936 |             0.02303
B' seq    |   2 |        3 |              1 | -, 86%, 88%            |                7 |    0.03913 |     0.01620 |             0.01934
B' batch  |   2 |        2 |              2 | -, 75%                 |                6 |    0.02691 |     0.01560 |             0.01874

=== k = 3: the model chooses 3 of the three reads; the policy's playbook reads 0 first ===
arm       |   k | requests | calls/response | prefix of previous     | policy decisions | no caching | cache reads | reads + write price
B         |   3 |        4 |              0 | -, 43%, 50%, 60%       |                8 |    0.05431 |     0.02224 |             0.02627
B' seq    |   3 |        4 |              1 | -, 87%, 87%, 89%       |                8 |    0.05234 |     0.01753 |             0.02075
B' batch  |   3 |        2 |              3 | -, 67%                 |                6 |    0.02764 |     0.01633 |             0.01954

Pre-declared outcomes in #87, offline halves only. ADOPT B': fewer provider requests than B whenever k >= 2, and at least as much prefix reuse. KEEP B: no request or token advantage at k >= 2.
  B' seq   : fewer requests: no; prefix reuse at least B's: yes; fewer input tokens: yes | ADOPT B' met: no; KEEP B met: no
  B' batch : fewer requests: yes; prefix reuse at least B's: yes; fewer input tokens: yes | ADOPT B' met: yes; KEEP B met: no
  Reading: the offline half of ADOPT B' is met only when the simulated model batches its tool calls, and the offline half of KEEP B is not met in either case. Whether a model batches is something only a real model can show: INCONCLUSIVE offline; both ports go forward as arms.

'calls/response' is the most tool calls any one model response carried. Under B a model call carries none: it can only propose one, as text.
Under B' every tool call came back to the policy as a proposal; the policy adopted it and the host executed it. No model call executed anything.
Nothing here measures answer quality, real cost, real latency, or how a real model behaves.
```

## What the table shows

- **Request count follows from how the model is asked.** Arm B needs k + 1 requests. B' needs k + 1 when the simulated model asks for one tool per response and 2 when it asks for all of them at once.
- **The appended conversation reuses more of its prefix.** B' repeats 67% to 89% of the previous request; arm B repeats 43% to 60%.
- **In every cell of this table, and at stable prefixes of 0 and 20,000 tokens, B' costs no more than B.** With a 5,000-token stable prefix and discounted cache reads the difference is 11% at k = 1 and 21% (sequential) or 27% (batched) at k = 3.
- **With the interface held equal, the policy adds no model requests.** At k = 3, B' sequential sends as many requests as the conventional agent A (four), and B' batched as many as A' (two). Each is about 5% above its native counterpart in the cost columns, which is the step contract and the answer schema. For comparison, arm B at k = 3 is 34% above A under discounted cache reads. On this one simulated scenario, most of that gap goes with the typed tool-less interface, not with the policy being in control.

## Against the pre-declared outcomes in #87

| Outcome | Offline half | Result |
|---|---|---|
| **Adopt B'** as the canonical model port | Fewer provider requests than B whenever k ≥ 2, and at least as much prefix reuse | Met when the simulated model batches. **Not met** when it asks for one tool at a time: same request count |
| **Keep B** | B' shows no request or token advantage at k ≥ 2 | **Not met** in either case: B' sends fewer input tokens even without batching |
| **Inconclusive offline** | Carry both ports as arms into the Level C design | **This is the outcome.** Whether a model batches is something only a real model can show |

The live halves (invalid-outcome rate, any executed-without-decision event, task success) are **not tested**. They belong to a run authorised under [#9](https://github.com/dgenio/turnwise-decision-lab/issues/9).

## What this does not show

- Real cost. Token counts are the double's `bytes // 4` and prices are operator-supplied.
- Whether a real model batches its tool calls, follows the step contract, or copes with a declined call. The simulated model re-proposes a declined call, and `TriagePolicy` then stops the run.
- Quality. Counter-evidence in #87 says a fresh, focused packet could *help* a real model; an appended conversation keeps more untrusted text in context. Neither effect is measured here.
- Anything for LlamaIndex: B' exists for the OpenAI Agents SDK pair only.
- Anything beyond one scenario.

## Tests

[`tests/test_architecture_native_intercept.py`](../tests/test_architecture_native_intercept.py) pins mechanisms, not the verdict:

- a tool call in a model response runs only after the policy adopts it and the host validates it; a policy that adopts nothing means nothing runs;
- parallel proposals are each considered, validated and answered; a declined call is answered with the reason and never reaches the host; a policy that adopts a write is still stopped by the host;
- the proposal budget counts every tool call, the tool budget still applies, and a terminal decision ends the consideration phase;
- on the real SDK: one model call per decision, a fixed tools field, an append-only conversation, the tripwire stays empty, and a call to a tool that was not offered never reaches the host;
- the default demo, its sample output and the smoke matrix are unchanged.

Four mutations are caught: tools that no longer need approval, adoptions not validated by the host, proposals executed without asking the policy, and declined calls answered as if adopted.

## Reproduce

```bash
pip install -r examples/architecture/requirements.txt
```

```bash
python -m examples.architecture.intercept_structure
```

```bash
python -m examples.architecture.run_demo --native-intercept
```

Use `--stable-prefix-tokens`, `--min-cacheable-tokens` and the price flags to change the assumptions.
