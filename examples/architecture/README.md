# The same agent, with and without Turnwise Core

**What this shows:** who decides the next operation. In a conventional agent the generative model decides every step. Under Turnwise Core a separate typed policy decides every step, and the model is one operation the policy may choose.

**What this does not show:** that Turnwise is cheaper, faster or better. Nothing here measures quality, cost or latency. The point is the control flow, not a result.

Both examples use **the same** task, tools, synthetic data, host, permissions, base instructions and model. What the model is *shown* necessarily differs; see [parity notes](#parity-notes). They come as two framework pairs:

- [OpenAI Agents SDK](openai_agents/)
- [LlamaIndex](llamaindex/)

## The one difference

| | **A. Conventional agent** | **B. Same agent, Turnwise Core** |
|---|---|---|
| Who chooses the next operation | The LLM, inside the framework's loop | A typed policy: `policy.decide(snapshot) -> Decision` |
| What a model call is | The controller of the loop | One bounded operation (`CALL_HEAVY` / `CALL_LIGHT`) chosen by the policy |
| When the model wants a tool | The framework runs it, then asks the model again | It returns a typed `tool_proposal` to the policy, which may adopt or decline it |
| Who executes tools | The shared host (validates every call) | The same shared host (validates every call) |
| How the run ends | When the model answers without a tool call | `FINISH`, `DIRECT`, `HOLD` or `CLARIFY`, chosen by the policy and validated by the host (see [What the host enforces](#what-the-host-enforces-for-both-architectures) for how much each check covers) |

```mermaid
flowchart LR
  subgraph A["A. Conventional agent (framework loop)"]
    direction LR
    UA([task]) --> LLM{{"LLM decides"}}
    LLM -- "tool call" --> HA["host validates + executes"]
    HA -- "tool result" --> LLM
    LLM -- "final answer" --> EA([end])
  end
  subgraph B["B. Turnwise Core (policy loop)"]
    direction LR
    UB([task]) --> P{{"typed policy decides"}}
    P -- "CALL_TOOL / CALL_WORKFLOW" --> HB["host validates + executes"]
    HB -- "receipt" --> P
    P -- "CALL_HEAVY / CALL_LIGHT" --> M["model: ONE call, no tools"]
    M -- "typed outcome: answer candidate / tool proposal / needs evidence" --> P
    P -- "FINISH (host checks citations) / DIRECT / HOLD / CLARIFY" --> EB([end])
  end
```

## The two code paths

**A. A plain SDK agent** ([`openai_agents/conventional.py`](openai_agents/conventional.py)):

```python
agent = Agent[HostSession](name="Incident investigator", instructions=AGENT_INSTRUCTIONS,
                           tools=[_function_tool(spec) for spec in TOOLS], model=model)
result = Runner.run_sync(agent, task, context=HostSession(host, actor="llm"), max_turns=10)
# The SDK loop: model -> tool calls -> host -> results appended -> model -> ... -> final_output
```

**B. The same agent under Turnwise Core** ([`openai_agents/turnwise.py`](openai_agents/turnwise.py), [`turnwise_core.py`](turnwise_core.py)):

```python
agent = build_agent(model)                                  # the very same agent definition
step_agent = agent.clone(tools=[], handoffs=[], mcp_servers=[],  # nothing executable left:
                         output_type=StepOutcome)                 # a model step can only *propose*

for step in range(1, budget.max_steps + 1):                 # TurnwiseRuntime.run(), simplified
    decision = policy.decide(snapshot(step))                # the POLICY chooses the next operation
    ok, why = host_validates(decision)                      # ...and the host may refuse it
    if decision.op in (CALL_TOOL, CALL_WORKFLOW):
        observation = host.execute(decision.target, decision.arguments)
    elif decision.op is CALL_HEAVY:                         # one model call, typed result
        observation = Runner.run_sync(step_agent, packet, max_turns=1).final_output
    elif decision.op in (FINISH, DIRECT, HOLD, CLARIFY):
        break                                               # terminal, after host validation
    # every observation, including the model's tool proposal, goes back to the policy
```

The LlamaIndex pair has the same shape:

- **A** is a `FunctionAgent` with `FunctionTool`s.
- **B** uses one `llm.structured_predict(StepOutcome, ...)` per model operation: on the agent's own LLM for `CALL_HEAVY`, or on a separate light LLM for `CALL_LIGHT`.

## Run it

Requires Python 3.11+ (`llama-index-core` 0.14 needs it). The core loop, host and policy are stdlib-only.

```bash
pip install -r examples/architecture/requirements.txt
```

```bash
python -m examples.architecture.run_demo
```

```bash
python -m examples.architecture.run_demo --framework llamaindex
```

```bash
python -m examples.architecture.run_demo --framework all --scenario all --handoff
```

**By default nothing leaves your machine.** The frameworks run for real: the SDK `Runner`, function-tool dispatch, structured-output parsing and LlamaIndex's agent workflow. Only the model is replaced, by each framework's own offline test double: `agents.testing.ScriptedModel` and LlamaIndex's `MockFunctionCallingLLM`. Their replies come from [`simulated_model.py`](simulated_model.py), a small deterministic investigator. It reacts only to what the framework actually passes it: instructions, the task, tool results, or the Turnwise context packet. Every trace says `SIMULATED`, and no output claims inference happened.

`run_demo` is offline only; `--live` now refuses and points to the bounded smoke test below. **Real-provider runs go only through [`live_smoke.py`](live_smoke.py)**, which by default rehearses against a local provider double (free, offline):

```bash
python -m examples.architecture.live_smoke
```

A paid run needs an explicit model, prices and a spend authorisation that covers the computed worst case. It has **not been run**: see [Real-provider readiness](#real-provider-readiness) and the [decision packet](../../docs/live-smoke-decision-packet.md).

## Recorded output (offline: real SDK 0.25.0, simulated model)

From [`sample_output/openai-agents.txt`](sample_output/openai-agents.txt). CI regenerates this file and fails if it changes:

```text
=== Side by side: who chose each operation ===
A: Conventional agent                                      | B: Turnwise Core
-----------------------------------------------------------+-----------------------------------------------------------
   1  LLM -> tool error_trend                              |    1  policy -> CALL_TOOL error_trend
   2  LLM -> tool recent_deploys                           |    2  policy -> CALL_TOOL recent_deploys
   3  LLM -> tool validate_config                          |    3  policy -> CALL_HEAVY => proposes validate_config
   4  LLM -> final answer, run ends                        |    4  policy -> CALL_WORKFLOW validate_config (adopts m1)
                                                           |    5  policy -> CALL_HEAVY => answer candidate
                                                           |    6  policy -> FINISH [finished]
  result: completed (SDK final_output)                     |   result: finished
```

The step that matters is B3 to B4, where the model asks for a tool and the policy decides:

```text
STEP 3
  controller  : Turnwise policy
  decision    : CALL_HEAVY context=[r1, r2] may_propose=[service_health, validate_config,
                search_docs]
  why         : the question needs reasoning over the evidence; use the capable model
  host        : validated; called the heavy model once via OpenAI Agents SDK:
                Runner.run_sync(agent.clone(tools=[], output_type=StepOutcome), max_turns=1)
  observation : m1 tool_proposal validate_config(service=checkout): "I need validate_config evidence
                before I can answer." -> back to the policy
STEP 4
  controller  : Turnwise policy
  decision    : CALL_WORKFLOW validate_config(service=checkout) [adopts m1's proposal]
  why         : adopt m1's proposal: a registered read that has not been done
  host        : validated and executed -> r3
  ...
STEP 6
  controller  : Turnwise policy
  decision    : FINISH with answer candidate m2
  host        : accepted m2: its citations [r1, r2, r3] are executed host receipts it was shown; the
                keyword screen found no claimed side effect. Causal correctness is NOT verified.
```

In A the same request (`validate_config`) was simply executed: the model decided and the SDK ran it. In B it is data. The policy adopted it here because it is a registered read that has not been done yet. Given an unrequested `rollback_deploy` proposal, the policy declines it. Even a policy that adopts everything is refused by the host. Both behaviours are covered by the tests.

**This showcase step is authored, not discovered.** The policy's cheap-evidence playbook (symptom + change) deliberately omits the configuration check, which the simulated model wants. That mismatch is what produces the proposal at B3. Both were written by the same author, with similar keyword rules. The tests drive the same policy with other outcomes to show it reacts to state rather than replaying this route: a different proposal, an immediate answer, a write proposal, malformed output, missing evidence, and a service with no deploy.

## The operations, and where each appears

| Operation | Meaning | Seen in |
|---|---|---|
| `DIRECT` | Answer from a host-verified record. No model and no tool. | `--scenario severity` |
| `CALL_TOOL` / `CALL_WORKFLOW` | The host executes one registered read or deterministic workflow. | every scenario |
| `CALL_LIGHT` | One call to the cheaper model, with policy-selected context. | `--scenario status` |
| `CALL_HEAVY` | One call to the capable model with policy-selected context. It returns a typed outcome and executes nothing. | `--scenario investigate` |
| `FINISH` | Ask the host to accept a model's answer candidate. The host checks that the cited receipts were executed and shown to the model. A keyword screen refuses any wording of a completed side effect when no write executed. It does **not** check causal truth. | `investigate`, `status` |
| `HOLD` / `CLARIFY` | Stop visibly. A held write is **not** an executed action. | `HOLD`: `--scenario rollback`; `CLARIFY`: a request that names no service (tests) |
| `HANDOFF_AGENT` | **Contrast only, not Turnwise Core.** The native agent runs its own loop for a bounded segment. The trace labels those steps `native agent (handoff)`, and control returns to the policy afterwards. The run's title is derived from what happened: any handoff makes it "Agent handoff (contrast; NOT Turnwise Core)". The agent declares no citations; the runtime attaches the receipts it was given or produced and says so, so `FINISH`'s provenance check is weak for handoffs. | `--handoff --scenario investigate` |

## What the host enforces, for both architectures

[`incident_env.py`](incident_env.py) wraps the repository's existing `LocalHarness` and the synthetic world in [`turnwise_lab/world.py`](../../turnwise_lab/world.py). Every tool request goes through `IncidentHost.execute`, whether the LLM (A), the policy (B) or a handed-off agent proposed it. The host enforces:

- Only registered capabilities run, with exactly their declared arguments (for example, the service must be a known one).
- **A write needs the user's own explicit request**, parsed from the user's text only. It must be a plain imperative ("Roll back checkout"): any negation, condition, hedge, quotation or attribution ("the bot suggested...") disqualifies it. Model text and tool output are never inputs to this parser. It is lexical and deliberately conservative.
- Even a requested write is **held for human approval** and never executed. The world's write handlers record any attempt and raise, and `writes executed: 0` is printed for every run.
- In B, the host also validates each *decision*:
  - the operation kind must match the capability kind;
  - context may contain executed receipts only;
  - `DIRECT` needs an existing record;
  - `FINISH` needs a real answer candidate with valid citations;
  - claimed adoptions must match the model's proposal.
- In B, steps, model calls, tool calls and rejections are budgeted from the runtime's own counters, not from anything the policy holds.
- In B, the policy receives a **copy** of the state: changing its snapshot (receipts, budget) changes nothing the host relies on.
- In B, a host rejection is fed back to the policy (`snapshot.last_rejection`).
- `HOLD` / `CLARIFY` are checked only for a non-empty message and the same side-effect keyword screen. The policy never relays model text in them.
- Every result, in A and B, ends with a **host action record** built from receipts only: the authoritative statement of what was and was not executed, whatever the model's text says.

## What is real and what is simulated

| Component | Status |
|---|---|
| OpenAI Agents SDK `Agent`, `Runner.run_sync`, `FunctionTool`, `Agent.clone`, `output_type`, `max_turns` | **Real**, public APIs, pinned `openai-agents==0.25.0` |
| LlamaIndex `FunctionAgent`, `FunctionTool`, `structured_predict` | **Real**, public APIs, pinned `llama-index-core==0.14.26` |
| Host validation and tool execution | **Real** Python: the existing `LocalHarness` and `world.py` handlers |
| Synthetic incident data | Synthetic, from the existing v0.5 world |
| Policy | **Real code**, deterministic rules ([`policies.py`](policies.py)); not learned, tuned or evaluated |
| Provider classes: Agents SDK `OpenAIResponsesModel` + `openai.AsyncOpenAI`; LlamaIndex `OpenAIResponses` (pinned `llama-index-llms-openai==0.9.0`) | **Real**, tested offline against an HTTP-level provider double ([`provider_double.py`](provider_double.py)); **never run against the real provider** |
| Model replies | **SIMULATED** in the demo, the tests and the smoke rehearsal; real only via `live_smoke --provider openai`, which has **not been run** |

## Real-provider readiness

**Status (2026-11-19): ready for a bounded live smoke test; no real inference has been performed.**

The offline demo replaces each framework's *model object* with a test double (`ScriptedModel`, `MockFunctionCallingLLM`). That leaves the classes a live run actually uses untested, and for LlamaIndex those classes take a different internal path. So the live paths are now exercised one level lower:

- [`provider_double.py`](provider_double.py) is a deterministic stand-in for the OpenAI **Responses API** (`POST /v1/responses`, non-streaming).
- It is served by an `httpx2.MockTransport`.
- The real provider classes build real requests and parse real wire-format responses: the Agents SDK's `OpenAIResponsesModel` over `openai.AsyncOpenAI`, and LlamaIndex's `OpenAIResponses`.
- There is no network and no key, and socket connects are blocked in the tests.
- Reply content comes from the same `SimulatedInvestigator`. Faults can be scripted per request: refusal, prose instead of JSON, schema violation, malformed or unknown tool calls, write calls and proposals, a function call in a tool-less step, `incomplete`, HTTP 400/401/429/500, timeout, and runaway tool loops.

[`tests/test_architecture_provider_readiness.py`](../../tests/test_architecture_provider_readiness.py) checks the following, in both frameworks:

1. **Native tool calling (A).** All 6 tools are sent as function tools. The model's call goes to the host, and the result is fed back paired by `call_id`.
2. **What a Turnwise model call receives (B).** The step is sent with:
   - the agent's instructions plus the step contract;
   - the host-assembled packet: the policy-selected receipts, and the read tools the model may propose (never the write tool);
   - a strict `StepOutcome` JSON schema;
   - no tools at all;
   - one provider request per `CALL_HEAVY`.
3. **A provider-format tool proposal returns to the policy.** It becomes the next snapshot's latest observation with no new host receipt. The tool runs only after a policy decision that adopts it. A function call returned to a tool-less step executes nothing.
4. **The policy decides; the host validates.** A model write proposal is declined by `TriagePolicy`. If a naive policy adopts it, the host rejects it.
5. **Failures are visible.** Every fault becomes an `invalid` observation with a category (refusal, invalid structured output, incomplete response, provider error HTTP n, timeout) and is never accepted. In A, provider errors raise. Each failed call is exactly one request.
6. **Model output never authorises a side effect.** `requested_writes` is parsed from the user's text only. A user-requested rollback is held in all four configurations.
7. **Limits.** The native loops stop at `max_turns` / `max_iterations` = 10, and the host caps tool executions at 8. Turnwise stops at `Budget.max_model_calls`. The ledger refuses requests over its request or spend cap *before sending*, and that halts a Turnwise run (it is not fed back to the policy).
8. **Parity.** All four configurations send the same model id, `max_output_tokens` and temperature or reasoning effort. The native tool schemas agree. The remaining framework differences are asserted (see [Provider path](#provider-path-differences-observed-on-the-wire)).

**Safeguards on every provider request** ([`provider.py`](provider.py)):

- The ledger is attached via `httpx2` event hooks on the clients handed to both frameworks, so it sees every HTTP attempt, including retries or hidden calls.
- Retries are 0, at both the client and the SDK retry layer.
- The timeout is explicit.
- `max_output_tokens` is explicit.
- A request is refused unsent if it does not carry that output bound.
- There is a request cap per configuration (the framework's own limit).
- A paid run has a spend guard. Before sending, each request is priced from its own size (body bytes as a conservative text-token estimate, plus one `max_output_tokens` for every reasoning item echoed back by id, plus its own `max_output_tokens`), and refused if its reservation could take spending past the authorisation. HTTP errors with missing usage keep their reservation; actual reported usage cannot lower it. This is **not a provider-enforced billing ceiling**: it relies on operator-supplied current prices, textual payloads and the API's token reporting.
- In real mode the endpoint is pinned to `https://api.openai.com/v1/responses` for both frameworks. Environment base-URL overrides are ignored; the ledger refuses an off-target host, scheme or path **before** sending, and every request's destination is also checked in the trace.
- Every request and response is recorded.

**The smoke harness** ([`live_smoke.py`](live_smoke.py)):

- It runs the four configurations on the `investigate` scenario.
- It records provider requests, host tool calls, typed outcomes, controllers, termination and errors.
- It grades each configuration PASS / FAIL / INCONCLUSIVE on mechanism checks.
- CI rehearses it against the double.
- `--provider openai` refuses to start without an explicit `--model`, positive prices, `OPENAI_API_KEY` and an `--authorize-usd` that covers the planned worst case.
- In every mode it refuses model ids that a pinned framework does not know, and settings the two frameworks would send differently: a temperature for a model LlamaIndex treats as reasoning, a reasoning effort for one it does not, or a non-reasoning model without an explicit temperature.

The proposed paid run is in the [decision packet](../../docs/live-smoke-decision-packet.md).

Compatibility findings from building this. Each one is fixed or guarded, and covered by a test:

- **Hidden retries and long timeouts.** The previous `--live` used SDK and client defaults: `openai` retries twice with a 600 s read timeout, and `llama-index-llms-openai` retries 3 times with a 60 s timeout. There was no request or spend cap. All live use is now bounded and routed through the harness.
- **LlamaIndex took a different path live.** With `OpenAIResponses`, `structured_predict` uses the Responses API's constrained decoding (`responses.parse`, `tool_choice="none"`), not the function-calling program that the offline mock exercises.
- **It also dropped the LLM's own bounds.** That `responses.parse` call omits the LLM's `max_output_tokens`, reasoning options and sampling parameters. The Turnwise port now passes them explicitly (`step_llm_kwargs`), so A and B send the same bounds.
- **Chat Completions is not used for LlamaIndex.** The previous live path used `llama_index.llms.openai.OpenAI`. OpenAI's `gpt-6.1-sol` model page (read 2026-11-19) states *"Tool calling requires the Responses API"*, although `llama-index-llms-openai` 0.9.0 does not list that model as Responses-only. LlamaIndex now uses `OpenAIResponses`, the same API as the Agents SDK. The Chat Completions adapter also discards `refusal`.
- **Refusals and truncation are hidden by LlamaIndex.** A refused or `incomplete` structured step surfaces only as a generic `ValueError`, and a refused or truncated `FunctionAgent` turn ends as an ordinary, empty completion. The Turnwise port and the harness read the wire record to name these.
- **Model ids.** `llama-index-llms-openai==0.9.0` validates ids against its own table, which reaches `gpt-6.1-sol`. Newer ids such as `gpt-6.2-sol` fail, and the harness preflight refuses them before any request.
- **Reasoning items.** On the next turn, the Agents SDK echoes `reasoning` items by id, which works with the API's default `store`. Setting `store=false` without encrypted reasoning content would break multi-turn runs on reasoning models (the double emulates the API's rejection). LlamaIndex sends `store=false` and drops reasoning items.

## Framework integration notes and limits

**OpenAI Agents SDK.**
- No monkey-patching and no private APIs.
- The native loop is used as-is for A and for the handoff contrast.
- Turnwise does not try to keep the SDK loop running and intercept it. It calls `Runner.run_sync(..., max_turns=1)` once per model operation, on a clone with no tools, handoffs or MCP servers and a typed `output_type`. The **empty capability lists** are what guarantee the model can only propose. `max_turns=1` only bounds the run to one model call: on its own it would not stop a tool from executing in that first turn.
- A seam we did not use: function tools with `needs_approval=True` pause the run before a model tool call executes, so a policy could inspect it there. That keeps the SDK's loop as the owner between pauses and adds resume semantics.
- Tracing is disabled (`RunConfig(tracing_disabled=True)`) so that offline runs send nothing to the default trace exporter. This is a difference from a default SDK setup.

**LlamaIndex.**
- One finding: the final `AgentOutput.tool_calls` of a `FunctionAgent` run is extended with *every* tool call of the run. So the per-step trace reads each decision from the LLM's own response message, using `llm.get_tool_calls_from_response`.
- Turnwise's loop is not expressed as a LlamaIndex `Workflow`. It is kept framework-neutral so that both pairs share it.

### Parity notes

What is identical in A and B:
- the task text;
- the tool registry and handlers;
- the synthetic data and the host, with the same write authority;
- the base instructions (`AGENT_INSTRUCTIONS`);
- the model object.

What differs, by design of the two architectures:
- **The conversation.** In B, each model step sees a host-assembled JSON packet (policy-selected receipts plus the tools it may *propose*) instead of the running conversation.
- **The instructions.** B appends a step contract that overrides the "use the tools" instruction.
- **The light model.** In the offline demo, B's `CALL_LIGHT` uses a separate light model object, while A always uses the capable one; both are the same simulated stand-in. With a provider (the smoke test), `CALL_LIGHT` uses the same single selected model as `CALL_HEAVY`, and the smoke scenario uses only `CALL_HEAVY`.
- **Malformed tool calls in A.** An unknown tool name never reaches the host in A. The OpenAI SDK aborts the run (`ModelBehaviorError`). LlamaIndex returns an error to the model, and the trace shows "no host receipt". Bad *arguments* do reach the host in both and are rejected there.
- **Write tools.** B's model is never offered `rollback_deploy` to propose.
- **Budgets.** The native agents have `max_turns` / `max_iterations` = 10, and Turnwise has the `Budget` in `turnwise_core.py`.

#### Provider path: differences observed on the wire

With the provider classes, A and B in one framework share the same model object and settings. Across frameworks, both use the Responses API and the same model id, `max_output_tokens` and temperature or reasoning effort. These framework defaults still differ; `ParityTests.test_disclosed_framework_differences_match_what_is_sent` keeps the list honest:

| | OpenAI Agents SDK | LlamaIndex |
|---|---|---|
| Native tool schemas | `strict: true` | strict not set (the API's non-strict default) |
| Response storage | `store` not sent (the API default; required for its reasoning-item echo) | `store: false` |
| Instructions | the `instructions` field | a system/developer input message |
| Turnwise step | `text.format` json_schema `final_output`, no `tool_choice` | `text.format` json_schema `StepOutcome`, `tool_choice: "none"` |
| `top_p` (non-reasoning models) | not sent | `1.0` (the API default) |
| Agent response mode | `Runner.run_sync` (non-streaming) | `FunctionAgent(streaming=False)` |
| CALL_LIGHT | same model as CALL_HEAVY in provider mode (one selected model) | same |

How A's traces are built:
- Each model response is one row group.
- Tool calls are paired with host receipts **by the framework's call id**, because LlamaIndex may run one response's calls concurrently.
- Text sent alongside tool calls is shown as such.

No efficiency comparison is made.

## Limitations: what this does not establish

- **No quality, cost or latency claim.** The printed counts are operation counts for one simulated run. They are not measurements. Turnwise adds policy decisions and host checks that a native agent does not have.
- **The simulated model is not a model.** It is deterministic and was written by the same author as the policy. Offline traces prove *control flow*, not reasoning ability.
- **Real-model behaviour is still untested.** The provider classes are tested against a provider *double* that emulates the wire format and scripted faults (malformed outputs, refusals, errors). A real model may still make different tool choices or ignore the step contract, and the API may reject parameters that the double accepts. Nothing establishes this until the [bounded live smoke test](../../docs/live-smoke-decision-packet.md) is authorised and run.
- **The policy is hand-written** for this synthetic domain. It is a stand-in for a learned or decision-service policy (Jev/System One is not used). Simple host rules may do as well, which is the open research question in [#9](https://github.com/dgenio/turnwise-decision-lab/issues/9).
- **`FINISH` checks provenance, not truth.** Evidence being present is not proof of causation.
- The write-intent parser and the side-effect claim screen are keyword rules. They fail closed (they refuse more than necessary) but are not semantic checks.
- CI blocks the network only for clients that honour `HTTP(S)_PROXY` (pointed at a dead port). Only the two frameworks are pinned; their dependencies are not.
- Single-turn tasks only. There are no multi-turn referents and no approve-and-resume flow.
- **Deferred from [#49](https://github.com/dgenio/turnwise-decision-lab/issues/49):**
  - null arms: simple host rules + the native agent, and a checklist-prompted native agent ([#43](https://github.com/dgenio/turnwise-decision-lab/issues/43));
  - a follow-up/retargeting scenario;
  - prompt and schema inventory parity tooling;
  - reuse of the v0.6 runtime in [#47](https://github.com/dgenio/turnwise-decision-lab/pull/47).
- This example is self-contained on `main` and does not depend on the experimental PR chain.

## Files

| File | Role |
|---|---|
| `incident_env.py` | Shared task set, tool registry (from `world.py`), receipts and `IncidentHost` (wraps `LocalHarness`) |
| `turnwise_core.py` | Typed contracts (`Op`, `Decision`, `ModelOutcome`, `Snapshot`), host validation of decisions, and the bounded loop |
| `policies.py` | `TriagePolicy` (Turnwise Core) and `HandoffPolicy` (contrast only) |
| `simulated_model.py` | Offline stand-in for model replies, the same in both architectures |
| `step_schema.py` | `StepOutcome`, the typed result of one model step |
| `openai_agents/`, `llamaindex/` | `conventional.py` (A), `turnwise.py` (B), `models.py` (simulated model, or a bounded provider model) |
| `trace.py`, `run_demo.py` | Per-step controller traces and the offline CLI |
| `provider.py` | `ProviderLedger` (request and spend caps before sending, a record of every request and response) and the settings shared by both frameworks |
| `provider_double.py` | Deterministic Responses API stand-in, with scriptable faults (SIMULATED) |
| `live_smoke.py` | The bounded four-configuration smoke test: rehearsal by default, paid only with explicit authorisation |
| `sample_output/`, `regenerate_samples.sh` | Committed offline output, checked by CI |

Tests:

- [`tests/test_architecture_core.py`](../../tests/test_architecture_core.py): stdlib only; runs in the main CI job.
- [`tests/test_architecture_openai_agents.py`](../../tests/test_architecture_openai_agents.py) and [`tests/test_architecture_llamaindex.py`](../../tests/test_architecture_llamaindex.py): run in the `architecture-examples` CI job, where a missing framework fails the job instead of skipping.
- [`tests/test_architecture_provider_readiness.py`](../../tests/test_architecture_provider_readiness.py): the provider classes against the provider double, and the smoke harness. It runs in the same job, which also rehearses `live_smoke --provider double`.
