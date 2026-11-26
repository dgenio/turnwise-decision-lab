# Live smoke test: decision packet (spending gate)

> **Status.** This plan's single authorization was consumed on 2026-11-19 and the attempt was INCONCLUSIVE: see [the first authorized run](#first-authorized-run-and-subsequent-offline-correction-2026-11-19) below, the [evidence record](../reports/live-smoke-44520205372.md), and [release status](release-status.md) for the current state. A future attempt needs a new PR and the owner's explicit authorization; a workflow merge alone is not a paid run.

> The status line below is the **pre-run historical authorization record**, deliberately retained unmodified for chronology.

**Status (2026-11-19): owner authorised ONE GPT-6.1 Sol run, up to US$2, in ChatGPT. No paid provider call has been made.** The key remains with the owner and is not stored in GitHub, ChatGPT or the repository. A rerun needs new authorisation.

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

The harness computes this worst case itself, and refuses to start if it exceeds `--authorize-usd`. The 8,000-input-token figure was a planning estimate for the 2026-11-19 run. *Note (2026-11-21):* since [#68](https://github.com/dgenio/turnwise-decision-lab/pull/68) it is also enforced: the ledger refuses, before sending, any request whose whole-body input bound exceeds `--max-input-bound-tokens` (default 8,000).

The **hard bound** is separate. Before each request is sent, the ledger prices that request from its actual size, using the body's byte length + 512 as an upper bound on input tokens, plus its `max_output_tokens`. Each reasoning item that the Agents SDK echoes back by id adds another `max_output_tokens` of input, because its stored content may be billed but is not in the body. It refuses the request if that bound, added to the spend so far, could exceed the authorisation. The spend reservation keeps at least the size-derived bound of **every** admitted request, including HTTP errors with no usage, and uses a larger provider-reported usage if available. Reported usage is shown separately. This is an estimated billing guard based on declared token prices and a text-payload size bound; it is **not a provider-enforced invoice ceiling**. Any model price, API feature, hidden token accounting or billing difference must be checked separately.

## Authorisation requested

**Maximum spend: USD 2.00**, for one run of the four-configuration matrix with `gpt-6.1-sol` (or `gpt-4.1` if preferred), under the caps above. A re-run would need a new decision.

## Secure local execution (recommended)

Run on a trusted personal computer (Windows, macOS or Linux), not a shared or corporate-managed host unless its policies explicitly permit personal API keys. Create a dedicated OpenAI API project and a **restricted, revocable key** permitted to write to `/v1/responses`. Check that API billing is active; a ChatGPT subscription does not pay for API usage. Never paste the key into chat, issues, GitHub Actions, terminal commands, screenshots or a file.

From a checkout of the reviewed `main`, create a fresh Python 3.11+ virtual environment and install `examples/architecture/requirements.txt`. Run:

```bash
python -m examples.architecture.secure_live_once
```

This performs the free provider-double rehearsal and a zero-cost price/limits plan. **No API key is requested.** Only after it passes, run:

```bash
python -m examples.architecture.secure_live_once --execute
```

The launcher disables the Agents SDK's *separate default tracing exporter* before loading any SDK, asks for a project key with no echo (Python `getpass`), demands an explicit `RUN`, and invokes exactly one `live_smoke --provider openai` matrix with fixed model, price inputs and the US$2 application guard. It never writes the key to disk or command history. The process environment contains it only while making provider calls.

The launcher keeps its rehearsal JSON, paid JSON and one-attempt marker in `~/.turnwise-decision-lab/` (outside Git; private directory on POSIX). If a paid attempt is interrupted, refused, fails or completes, **do not rerun it**: the marker intentionally prevents a second attempt without new owner authorisation. The JSON includes model outputs and should not be published without inspection and redaction. Revoking the temporary project key after use is recommended. The guard is an estimate, **not a guarantee that the provider's invoice cannot exceed US$2**.

**Direct CLI (manual alternative, for advanced operators only).** Keep Agents SDK tracing disabled with `OPENAI_AGENTS_DISABLE_TRACING=1` before loading it, and introduce `OPENAI_API_KEY` only in your local process environment (not as a command-line argument).

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

### Owner-dispatched Actions execution (same single authorization)

The dedicated `paid-smoke.yml` workflow is an alternative to the local launcher. This authorization covers one matrix across both launch paths. Once either path reserves it, retire the other path for this authorization. The tag and local marker live in different places. The observed local preparation ended before reservation.

Only the owner's first attempt at a manual dispatch on the default branch can proceed. The workflow checks runner connectivity without a key, runs the offline tests and rehearsal, checks the repository secret by name, and creates the fixed tag `turnwise-paid-gpt-6-1-sol-001` using GitHub's create-ref API. The tag consumes the authorization even if the runner is cancelled or the provider rejects the first request. Keep the tag permanently. A new authorization requires a separately reviewed change.

The private report exists only on the runner. The job summary retains a fixed-field projection of the ledger, including response statuses, tool receipts, typed outcomes, policy observations and per-arm spend. Missing arms are inconclusive. Admitted requests can include transport failures. Reported token counts cover only replies carrying usage. A mechanism result makes no comparative performance claim.

### First authorized run and subsequent offline correction (2026-11-19)

The [sanitized evidence record](../reports/live-smoke-44520205372.md) preserves per-configuration observations and separates owner-supplied results from GitHub-verifiable metadata. The original run has no downloadable artifact; its provider error subtype and actual billing remain unknown.

[Attempt 1](https://github.com/dgenio/turnwise-decision-lab/actions/runs/44520205372) consumed the authorization on revision `8ac5bca`. The provider returned HTTP 429 for all ten requests. The four configurations were inconclusive, with no model outputs, usage records or writes. Each conventional agent sent one request. Each Core policy received four invalid observations and exhausted its model-call budget. The ledger reserved USD 0.32729. The billing amount and the provider error subtype remain unknown.

Future smoke matrices stop sending provider requests after the first observed HTTP 429. A Core policy receiving that provider error holds, and later configurations are skipped. The sanitized JSON includes allowlisted provider error codes and is downloadable as the `turnwise-summary` Actions artifact as well as displayed in the job summary. These changes were tested offline. The original attempt tag still applies.
