# Live smoke test: decision packet (spending gate)

**Status (2026-11-19): awaiting the owner's decision. No paid provider call has been made.** Nothing in this repository has performed real inference. An API key being available is not treated as authorisation.

This packet asks for one bounded, paid run of the live smoke test in [`examples/architecture/live_smoke.py`](../examples/architecture/live_smoke.py). The purpose is **real-model compatibility** of the four configurations. It does not measure cost, latency or quality, and it is not a benchmark.

## What would run

The same synthetic scenario (`investigate`: *"Could the latest checkout deployment explain the increase in errors?"*) is run once through each configuration, all with one model and identical model-level settings:

| Configuration | Model call | Who chooses each operation |
|---|---|---|
| OpenAI Agents SDK, conventional | `Agent` + `Runner.run_sync`, 6 native function tools | the model, inside the SDK loop |
| OpenAI Agents SDK, Turnwise Core | `Runner.run_sync(agent.clone(tools=[], output_type=StepOutcome), max_turns=1)` | the typed policy |
| LlamaIndex, conventional | `FunctionAgent` + `FunctionTool` (6 tools) | the model, inside the agent workflow |
| LlamaIndex, Turnwise Core | `OpenAIResponses.structured_predict(StepOutcome, ...)` | the typed policy |

Both frameworks call the **OpenAI Responses API** at `https://api.openai.com/v1`. The endpoint is pinned, so `OPENAI_BASE_URL` / `OPENAI_API_BASE` cannot redirect it. The Agents SDK uses `OpenAIResponsesModel`; LlamaIndex uses `llama_index.llms.openai.OpenAIResponses`.

The `gpt-6.1-sol` model page states: *"Tool calling requires the Responses API."* Note that `llama-index-llms-openai==0.9.0` does not list it as Responses-only. Using the same API in both frameworks is also the parity choice.

## Proposed provider and model

**Recommended: OpenAI `gpt-6.1-sol`, with `reasoning.effort = "low"` set explicitly in both frameworks.**

- It is a current model, not marked deprecated, and supports the Responses API, function calling and structured outputs (OpenAI model page, read 2026-11-19).
- Both pinned framework versions accept the id. `llama-index-llms-openai==0.9.0` knows models up to `gpt-6.1-sol`; newer ids such as `gpt-6.2-sol` fail its model table, and the harness preflight refuses them before any request.
- The effort is set explicitly. On this code path, a `Model` instance with explicit `ModelSettings`, the Agents SDK applies none of its default model settings. LlamaIndex sends reasoning options only when they are set. Without the setting, both would get the provider default (`medium`). The harness refuses settings the frameworks would send differently: a temperature for a model LlamaIndex treats as reasoning, a reasoning effort for one it does not, and a missing temperature for a non-reasoning model.

**Alternative: `gpt-4.1` with `temperature = 0`.** This model is non-reasoning, so it has no reasoning items and lets the sampling settings be identical in both frameworks. It is cheaper, but OpenAI marks it **Deprecated** (no shutdown date given). Choose one model, not both.

## Calls

Caps are enforced by the harness *before* a request is sent, and every request is counted. A request is refused unsent if it does not carry the configured `max_output_tokens`. There are no retries: `max_retries=0` on the client and `ModelRetrySettings(max_retries=0)` in the SDK.

| Configuration | Expected model calls | Maximum (hard cap = the framework's own limit) |
|---|---|---|
| Agents SDK, conventional | ~4 (3 tool calls + answer) | 10 (`max_turns`) |
| Agents SDK, Turnwise | 1–2 | 4 (`Budget.max_model_calls`) |
| LlamaIndex, conventional | ~4 | 10 (`max_iterations`) |
| LlamaIndex, Turnwise | 1–2 | 4 |
| **Total** | **~10–12** | **28** |

Other bounds:

- 60 s timeout per request.
- `max_output_tokens = 2000` per request, which includes reasoning tokens.
- The host caps tool executions at 8 per run.
- No write is ever executed: a model-proposed write is rejected, and a user-requested one would be held.

## Cost estimate (prices verified 2026-11-19)

Source: [OpenAI API pricing](https://developers.openai.com/api/docs/pricing), Standard tier, short context, and the model pages.

| Model | Input | Cached input | Output | Notes |
|---|---|---|---|---|
| `gpt-6.1-sol` | $2.00 / MTok | $0.10 | $10.00 / MTok | the model page lists cache writes at $2.50 / MTok, so the estimate uses **$2.50** for input |
| `gpt-4.1` | $2.00 / MTok | $0.50 | $8.00 / MTok | deprecated |

Regional (data-residency) endpoints add 10%. The harness uses the default endpoint. The pricing page does not mention reasoning tokens; the estimate assumes they are billed as output, which is why they are bounded by `max_output_tokens`.

- **Expected** (`gpt-6.1-sol`): about 12 requests × ~1,200 input tokens, plus up to ~600 output tokens each, comes to about **$0.05–$0.25**. Input sizes come from the provider-double rehearsal; real tokenisation and reasoning length are not known before running.
- **Worst case** (`gpt-6.1-sol`): 28 requests × (8,000 input × $2.50 + 2,000 output × $10.00) / 10⁶ = **$1.12**. For `gpt-4.1` it is $0.90.

The harness computes this worst case itself, and refuses to start if it exceeds `--authorize-usd`. The 8,000-input-token figure is a planning estimate.

The **hard bound** is separate. Before each request is sent, the ledger prices that request from its actual size, using the body's byte length + 512 as an upper bound on input tokens, plus its `max_output_tokens`. Each reasoning item that the Agents SDK echoes back by id adds another `max_output_tokens` of input, because its stored content may be billed but is not in the body. It refuses the request if that bound, added to the spend so far, could exceed the authorisation. The spend so far is reported usage plus the bound of any request that got no response.

## Authorisation requested

**Maximum spend: USD 2.00**, for one run of the four-configuration matrix with `gpt-6.1-sol` (or `gpt-4.1` if preferred), under the caps above. A re-run would need a new decision.

## Commands

First, the free rehearsal against the local provider double. It runs the same code path with no network and no key:

```bash
python -m examples.architecture.live_smoke --model gpt-6.1-sol --reasoning-effort low
```

Second, print the plan and worst case. This sends nothing:

```bash
python -m examples.architecture.live_smoke --plan --provider openai --model gpt-6.1-sol --reasoning-effort low --input-usd-per-mtok 2.50 --output-usd-per-mtok 10.00
```

Third, the paid run. It needs `OPENAI_API_KEY` in the environment and only runs after approval:

```bash
python -m examples.architecture.live_smoke --provider openai --model gpt-6.1-sol --reasoning-effort low --max-output-tokens 2000 --timeout 60 --input-usd-per-mtok 2.50 --output-usd-per-mtok 10.00 --authorize-usd 2.00 --out live-smoke-gpt-6.1-sol.json
```

The exit status is 0 for PASS, 1 for FAIL, 2 for a usage error or refusal to start, 3 for INCONCLUSIVE and 130 if interrupted. With `--out`, the JSON report is rewritten after every configuration, so an interrupted run keeps the record of the requests it already sent.

## What is recorded

For each configuration, the harness records all of the following from the provider wire and the host, not from model claims:

- every provider request: endpoint, model, offered tools and their strict mode, structured-output format, temperature, reasoning, `max_output_tokens`, input item types;
- what came back: function calls, text, refusals, `incomplete` status, reported model and token usage;
- host tool calls, with their status and who proposed each one;
- Turnwise typed outcomes, including proposals, citations and failure notes;
- the controller of every step, and the number of controller changes;
- termination status and answer;
- errors, writes executed, and reported cost against the conservative bound.

The report is labelled `REAL provider inference` or `PROVIDER DOUBLE (simulated ...)` throughout.

## Pass, failure, inconclusive

Each configuration is graded on **mechanism only**.

**FAIL** means an architectural claim is broken. Any one of these makes a configuration FAIL:

- a write was executed;
- a host receipt came from someone other than the expected controller (the model's own tool calls in A, policy decisions in B);
- an endpoint other than `/responses` on the expected host was called;
- a request used a different model;
- A did not offer all 6 tools natively, or used a structured-output format;
- B offered any tool to the model, or did not request the `StepOutcome` JSON schema;
- B made more provider requests than policy-chosen model calls (hidden calls or retries);
- any B step was controlled by something other than the Turnwise policy (no handoff);
- a model tool proposal was followed by a tool execution before the policy decided.

**INCONCLUSIVE** means the mechanism was not fully exercised, with no FAIL. Any one of these makes a configuration INCONCLUSIVE:

- a provider error, timeout, cap or framework step limit ended the run;
- the provider refused or truncated a response (graded from the wire, because LlamaIndex reports these as an ordinary empty completion);
- A's model executed no tool, or ended without a non-empty answer;
- B produced no valid typed outcome, or did not end with a host-validated terminal (`finished`, `held`, `answered_directly`, `needs_clarification`).

**PASS** means all checks pass.

The matrix verdict is FAIL if any configuration fails, PASS if all four pass, and INCONCLUSIVE otherwise. Two things are reported but not graded:

- whether the real model proposed a tool in B, and whether the policy adopted it. A capable model may answer from the evidence without proposing.
- B model calls that returned no usable outcome, which the policy handled.

## What a PASS would and would not establish

A PASS would establish that, with one real model on one synthetic scenario:

- both native agents tool-call through the shared host;
- both Turnwise configurations get typed outcomes from tool-less, schema-constrained calls;
- control returns to the policy after each outcome;
- the host's authority holds.

It would **not** establish:

- answer quality, cost or latency;
- behaviour across repeated runs, other scenarios or other models;
- production readiness;
- anything about the research questions in [#9](https://github.com/dgenio/turnwise-decision-lab/issues/9).

Real-model non-determinism means one run is one sample.
