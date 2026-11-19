# Same task, same tools: who decides the next step?

This is the smallest working demonstration of the architectural difference behind Turnwise ([#49](https://github.com/dgenio/turnwise-decision-lab/issues/49)):

- **Native agent (OpenAI Agents SDK, LlamaIndex):** a capable model chooses every next tool call, and the framework executes it.
- **Turnwise:** a small typed policy chooses every next operation. Calling the model is one of those operations. Whatever the model asks for comes back as an **observation**, and the policy decides again what runs.

It is **not a benchmark**. It makes no quality, cost or latency claim, and it is not an agent framework. Everything runs offline and deterministically: no keys, no network, no model weights and no paid inference.

```bash
python -m turnwise_lab.control_demo                 # Turnwise only (no dependencies)
pip install "turnwise-decision-lab[demo-openai,demo-llamaindex]"
python -m turnwise_lab.control_demo                 # all three configurations
python -m turnwise_lab.control_demo --remediation   # the model also proposes an unrequested rollback
python -m turnwise_lab.control_demo --json          # machine-readable traces
```

## What is shared, and what is not

| Shared by every configuration | Where it lives |
|---|---|
| One synthetic incident snapshot (as of 2026-11-01 11:40Z) | `control_demo/world.py` |
| One tool catalog: 4 reads and 1 write | `CATALOG` |
| One argument schema per tool | `ToolSpec.json_schema()` |
| One host, the only component that executes. It validates every call, executes reads and never executes a write. | `Host` |
| One principal (`demo-reader`, read only) | `Host` |
| One system instruction | `model.INSTRUCTIONS` |
| One deterministic "capable model". The native configurations drive it through each framework's own official test double: `agents.testing.ScriptedModel` and `MockFunctionCallingLLM`. | `model.IncidentModel` |
| Tool results shown to the model in the same JSON form | `as_model_text` |

The tests check this parity: tool names, schemas and instructions as each native framework actually offered them to the model. LlamaIndex adds `title` keys to schemas; the properties, enum and required fields match.

**What differs is only the controller.** The framework differences below are part of each framework, not architectural claims:

- **OpenAI Agents SDK.**
  - The Runner returns each tool result to the model, which picks the next step. The final output is whatever the model returns, with no host grounding check.
  - Writes use the SDK's `needs_approval`, so the run pauses for a human.
  - `max_turns=8` counts model turns.
- **LlamaIndex `FunctionAgent`.**
  - Same loop as the SDK.
  - There is no per-tool approval pause, so a write reaches the host as an approval request.
  - `max_iterations=8`.
- **Turnwise.** `max_steps=8` counts policy steps.

## The traces

Each table shows the operation, who chose it, what the host did with it, and **who controls the next step**. The traces below are real output of the command above.

```text
== OpenAI Agents SDK native agent
request: Could the latest checkout deployment explain the increase in errors?
 #  decided by                   operation              host validation   next controller              observation
 1  native model (SDK Runner)    call_tool              accepted          native model (SDK Runner)    ok: ['errors:checkout'] -> back to the model
 2  native model (SDK Runner)    call_tool              accepted          native model (SDK Runner)    ok: ['deploys:checkout'] -> back to the model
 3  native model (SDK Runner)    call_tool              accepted          native model (SDK Runner)    ok: ['config:checkout'] -> back to the model
 4  native model (SDK Runner)    answer                 -                 -                            final output
    terminated: model produced the final output; the Runner ended the run
final (answer, decided by native model (SDK Runner)): checkout errors rose from 0.4% to 6.4% at 11:05, three minutes after deployment d-142 at 11:02 (connection pool max 20 -> 5); config differs from baseline (pool_max 20 -> 5). d-142 is a likely contributor. This is a timing and config match, not proof of cause.
model calls: 4; host receipts: 3; writes executed: 0
```

The LlamaIndex `FunctionAgent` trace has exactly the same shape, with every step owned by `native model (FunctionAgent)`.

```text
== Turnwise per-step policy
request: Could the latest checkout deployment explain the increase in errors?
 #  decided by                   operation              host validation   next controller              observation
 1  turnwise policy              call_tool              accepted          turnwise policy              ok: ['errors:checkout']
 2  turnwise policy              call_tool              accepted          turnwise policy              ok: ['deploys:checkout']
 3  turnwise policy              call_model             -                 turnwise policy              model output -> observation: tool request get_config_diff({'service...
 4  turnwise policy              adopt_model_request    accepted          turnwise policy              ok: ['config:checkout']
 5  turnwise policy              call_model             -                 turnwise policy              model output -> observation: answer candidate citing ['errors:check...
 6  turnwise policy              finish                 grounded          -                            answer cites only host-returned evidence
    terminated: policy finished; host checked grounding
final (answer, decided by turnwise policy): checkout errors rose from 0.4% to 6.4% at 11:05, three minutes after deployment d-142 at 11:02 (connection pool max 20 -> 5); config differs from baseline (pool_max 20 -> 5). d-142 is a likely contributor. This is a timing and config match, not proof of cause.
model calls: 2; host receipts: 3; writes executed: 0
```

Both configurations reach the same answer from the same three tool results. Here is how the controller differs, step by step:

1. **Steps 1–2.** The policy requests the evidence a causal question needs without spending a model call.
2. **Step 3.** The model is called as an operation. Its request for `get_config_diff` is **recorded, not executed**, and control returns to the policy.
3. **Step 4.** The policy adopts that request, and the host validates and executes it.
4. **Step 5.** The model is called again. Its answer candidate is again an observation.
5. **Step 6.** The policy finishes, and the host checks that the answer cites only evidence it returned.

At no step does control pass to the model.

### With an unrequested write (`--remediation`)

The scripted model also proposes `rollback_deployment(checkout)` before answering. The user asked a question, not for an action.

| Configuration | What happens to the proposal | End of turn |
|---|---|---|
| OpenAI Agents SDK | The Runner sends it to the SDK approval gate (`needs_approval`) | Run paused, awaiting a human |
| LlamaIndex | The agent executes the tool call, and the host records an approval request | The model then answers |
| Turnwise | The policy declines it (`not_submitted`); it never reaches the host or an approver | The policy asks the model again and finishes |

This shows where each design can say no. It is **not** evidence that real models propose such writes, or that Turnwise is safer than a native agent plus host rules. That native-plus-host-rules comparison is the mandatory null in #49 and is not implemented here.

## Why the Turnwise loop wraps the model instead of hooking the Runner

The OpenAI Agents SDK lets you act around a tool call the model has already chosen:
- tool input guardrails can veto it;
- `needs_approval` can pause it;
- `RunHooks` can observe it;
- `tool_use_behavior` can stop after tool results.

None of these lets an outside policy choose the **next operation**. After tool results, `tool_use_behavior` can only run the model again or stop with a final output, so the next step always belongs to the model or ends the run. The policy also cannot issue a tool call the model did not request.

The Turnwise configuration therefore calls the model as one operation of its own loop. This is a reversible composition; the SDK is not forked. LlamaIndex's `FunctionAgent` loop has the same shape. A workflow-level integration is out of scope here.

## What is deliberately not here

The following parts of #49 are out of scope for this smallest demonstration:
- the two null configurations (host rules plus a native agent; a native agent with an evidence checklist);
- a native handoff configuration;
- the direct-lookup, approval-receipt and follow-up scenarios;
- the v0.7 L56 regression.

Also excluded:
- real models;
- any evaluation;
- any reuse of the unmerged experimental chain (#6, #37, #47). This package depends only on the standard library and, optionally, on the two frameworks above.

The policy is a handful of explicit rules for one task type. It stands in for a cheap typed policy; it is not a learned model. Whether such a policy is worth having at all is the open question in #9.
