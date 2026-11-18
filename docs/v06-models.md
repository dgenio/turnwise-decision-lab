# v0.6 model investigation (local inference, measured 2026-11-18)

Everything in this document was measured in this repository's development container. No hosted model or decision service was called.

## Hardware and runtime

- 4 vCPU Intel Xeon @ 2.1 GHz (AVX-512, AVX-512 VNNI, AMX), 15 GB RAM, **no GPU**.
- `onnxruntime` 1.29 CPU, `tokenizers` 0.23, `numpy`. **No PyTorch or transformers**.
- `onnx` is used once, to make two mechanical graph edits (below).
- No model repository code was executed and nothing used `trust_remote_code`. s1's `example.py` was read as data, never run.
- Weights live in `$TURNWISE_MODEL_DIR` (default `~/.cache/turnwise-models`), outside the repository. CI fails if a weight file is ever committed.
- Total downloaded: **2.99 GB**, under the ~4 GB working budget. Every file is pinned to a commit revision and checked against its LFS sha256 (`models/local_models.json`, `scripts/fetch_models.py`).

## Candidates

| Model (pinned revision) | License | Size | Role | Verdict and measured behaviour |
|---|---|---|---|---|
| `decisionmodels/s1-llm-auto-router` @572c5b6 | MIT | 218 MB | fixed-head classifier | **Used**, but only for what its heads mean (category, difficulty, stakes, needs_tools, needs_vision, needs_long_context, follow_up). 6–10 ms per call. It **cannot choose a tool**, and it rated the multi-step investigation question "easy" (expected difficulty 1.07 of 4, needs_tools 0.18), so on its own it would under-provision that question. Its 18 calibrated head outputs are features of turnwise-dm. Its pooled encoder vector alone gave only 0.656 template-held-out accuracy for next-operation prediction. |
| `onnx-community/Qwen3.5-0.8B-ONNX` @8fe9dbe (q4) | Apache-2.0 | 668 MB | decision scorer, heavy tier, heavy-only agent | **Used.** A hybrid linear-attention model, run with plain onnxruntime: separate embedding graph, 3-axis position ids, conv and recurrent state tensors. Decoding at 16.7–19.9 tok/s. Constrained choice put 75–99% of probability mass on the option labels. As a *zero/few-shot controller alone*, it picked the right first tool but **repeated tools it had already used**, picked `health` for a greeting, and did not integrate observations (see "Decision mechanisms"). It was the best evidence-based explainer among the candidates, so it is the heavy tier. |
| `onnx-community/Qwen2.5-0.5B-Instruct` @22942cb (int8) | Apache-2.0 (base) | 519 MB | light tier, light argument extractor | **Used.** 6.5 tok/s, slowed by the int8 `MatMulInteger` decode path. Fine for greetings and one-sentence answers. As a letter chooser only 20% of mass fell on the labels. |
| `onnx-community/Qwen2.5-1.5B-Instruct` @d54957e (int8) | Apache-2.0 (base) | 1.59 GB | planned heavy tier | **Rejected after measurement.** 3.9–4.3 tok/s. My first test omitted the system message, which the model's own template supplies by default, and produced nonsense; that was my bug. With a system message it was coherent on small talk. On the evidence-synthesis prompt, however, it **inverted before/after values and fell into repetition loops**, while Qwen3.5-0.8B answered correctly. As a decision scorer, almost none of its probability went to the option words. |
| `onnx-community/Qwen3.5-2B-ONNX` (q4) | Apache-2.0 | 1.54 GB | possible heavy tier | **Not downloaded.** It would have taken the total to about 4.5 GB, over budget. |
| `Qwen/Qwen3.5-0.8B` safetensors | Apache-2.0 | 1.75 GB | (transformers path) | Not used. The ONNX q4 export runs without PyTorch and is about 2.6× smaller. |

### Graph edits (cached next to the weights, not committed)

1. **Last-position logits.** The exports return logits for every position (`[T × vocab]`, ~490 MB at T = 800). A `Slice` inserted before the LM head keeps only the last position. The output at that position is identical.
2. **s1 pooled vector.** The `[CLS]` vector after the final norm, which feeds all seven s1 heads, is exposed as an extra output. This was used for the embeddings-only experiment.

## Decision mechanisms tried (development data only)

| Mechanism | What happened |
|---|---|
| Qwen3.5-0.8B, 14 options as letters, zero-shot | Scenario C: chose `heavy_model` immediately (0.28) and never gathered evidence. After a successful health lookup it re-proposed the same call three times; the host rejected all three. |
| + few-shot examples (fictional service, cached prefix) | First steps improved (health lookup 0.95). Sequencing was still wrong: repeated tools, and a greeting sent to `health`. |
| Hierarchical "kind of step" question | Real signal, but every state leaned towards "tool" (0.57 even with all evidence gathered). Not separable by a threshold. |
| Verbalizer (operation words; distinct first tokens) + `Next operation:` prefix | Best first steps (`errors` 0.72, `health` 0.98). Sequencing still poor. Qwen2.5-1.5B put almost no mass on the words. |
| s1 pooled embedding + typed state → logistic head | 1.00 train / **0.656** template-held-out validation. Intent from text was the bottleneck: 51% correct on first steps. |
| **turnwise-dm**: logistic head over [14 chooser log-scores, 18 s1 head outputs, 19 typed state features] | 0.989 train / **0.911** template-held-out validation, on synthetic data. L2 and temperature were picked on that same split, so the figure is optimistic. Used for the evaluation. |

Lesson: a small instruct model used as a controller is good at reading *intent*, but bad at *sequencing* over observations. A tiny trained head can combine the model's scores with typed observation features the host computes, and that fixes most of the sequencing errors.

## Hosted decision services (investigated, adapters written, not called)

- **OpenAI Decisions API** (`POST /v1/decisions`, model `gpt-6-luna`; guide and reference checked 2026-11-18).
  - Question types: `choice` (with probabilities and confidence), `predicate` (probability), `score` (2–10 ordered levels), plus refusals.
  - Takes up to 400 questions per request. Input can include `function_call` / `function_call_output` items, so observations can be passed natively.
  - Price: USD 0.10 per 1M uncached input tokens; output is free. `usage.input_tokens` is reported per request.
  - The docs say decisions that depend on an earlier answer need **separate requests**, which is exactly the per-step loop.
  - `agent/remote.py` builds the request (next operation as a `choice`, observations as function-call items), enforces a declared USD cap *before* sending, and records actual usage. Tested only against a local fake server.
- **TypeSafe / Jev** (`typesafe-sdk` 0.7.5, MIT): `client.system_one(state=..., questions={name: Choice(instructions, criteria={...})})`.
  - The decisionmodels.io System One HTTP shape (`choice` / `score` / `noul` questions over a `state` object) is documented on the s1 model card.
  - `SystemOneProvider` targets that shape. It requires a declared price per input token so the cap can be enforced. Tested only against a fake server.
- **Can one request decide everything?** Independent questions about the *same* state can share one request: next operation, tier, and a yes/no per context block. Arguments and the next step after a tool cannot, because they depend on observations that do not exist yet. The local loop mirrors this: one cached shared prefix with several questions per step, and a new inference after every observation.
