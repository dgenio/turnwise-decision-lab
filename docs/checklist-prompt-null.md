# Native-agent checklist null (A+P, issue #43)

**Status: implemented for opt-in, offline mechanism checks only. No capable-model experiment, quality result, cost result or paid authorization.**

This is the cheapest meaningful challenge to the claimed value of an external decision/exit gate. The native agent receives the same host, tools, permissions, synthetic task, simulated model and execution budget as **A**; **A+P** differs only by a short fixed checklist appended to its normal system instructions. There is **no new policy, host exit gate, model selection or prompt generation**. Both OpenAI Agents SDK and LlamaIndex import the exact same prompt from `examples/architecture/checklist_null.py`.

Prompt version: `native-evidence-checklist-v1`. SHA-256 of the UTF-8 checklist text: `c362d861e2f983a6a35007a68efb5d9b1fa132a0028c793e1d856808e49683ed`. The existing baseline remains byte-identical when the opt-in flag is absent.

Offline exercise (pinned SDKs required):

```bash
python -m examples.architecture.run_demo --framework all --scenario investigate --checklist-null
TURNWISE_REQUIRE_FRAMEWORKS=1 python -m unittest discover -s tests -p 'test_architecture*.py'
```

The flag **does not** change the four-arm real-provider smoke workflow or dispatch any paid API request. The offline scripted model is not a test of whether the checklist improves reasoning, and identical simulated answers do not establish non-inferiority.

## Prospective study, not yet run

Before new locked tasks or any paid call, preregister a capable model/revision, real request and cache-token accounting, prompt hashes, independent tasks/adjudication, task/session-level quality and critical errors, matched host-side write policy, complete tool/evidence access, comparable tool-action budgets and economic thresholds. Compare **A**, **A+P**, **A+G**, optionally **A+P+G**, **R+G**, and **C**, with action-scoped context selection as a separate factor. A+P's extra input and cache tokens count toward its total cost; prompt guidance cannot replace host permission enforcement. Preserve historical v0.6/v0.7 conclusions unchanged.

If A+P matches or beats host-exit/controller alternatives without material safety or efficiency loss, **SHRINK** the external controller's claimed benefit for the tested workload. This preparatory implementation does not close #43 or #9.
