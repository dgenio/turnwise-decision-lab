"""Optional local inference with pinned public ONNX models (CPU, no torch).

Two kinds of learned decision model are wrapped here:

* ``S1Router`` - decisionmodels/s1-llm-auto-router, a fine-tuned mmBERT-small
  classifier with fixed heads (category, difficulty, stakes, needs_tools,
  needs_vision, needs_long_context, follow_up). It is used ONLY for what those
  heads mean; it cannot choose a tool.
* ``LocalLM`` - a small instruct model (Qwen2.5 or Qwen3.5 ONNX exports) used
  two ways: constrained choice (one forward pass; probabilities are read from
  the next-token distribution restricted to the option letters, i.e. a
  normalised model score, NOT a calibrated probability) and greedy generation
  with a KV/state cache.

Requires ``onnxruntime``, ``numpy``, ``tokenizers`` (and ``onnx`` once, to add
a last-position slice before the LM head). Weights come from
``scripts/fetch_models.py``; nothing here downloads, and nothing executes code
shipped with a model repository.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import os
import time

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "models" / "local_models.json"


def model_dir() -> Path:
    return Path(os.environ.get("TURNWISE_MODEL_DIR", Path.home() / ".cache" / "turnwise-models"))


def manifest_entry(key: str) -> dict:
    for e in json.loads(MANIFEST.read_text(encoding="utf-8"))["models"]:
        if e["key"] == key:
            return e
    raise KeyError(key)


def available(key: str) -> bool:
    try:
        entry = manifest_entry(key)
    except KeyError:
        return False
    base = model_dir() / key
    return all((base / f["path"]).exists() for f in entry["files"])


def _session(path: Path, threads: int):
    import onnxruntime as ort
    so = ort.SessionOptions()
    so.intra_op_num_threads = threads
    so.log_severity_level = 3
    return ort.InferenceSession(str(path), so, providers=["CPUExecutionProvider"])


def _sha256_prefix(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        h.update(f.read(1 << 20))
    return h.hexdigest()[:16]


# --------------------------------------------------------------------- s1
S1_CATEGORIES = ["coding", "agentic", "math", "knowledge", "long_context", "tool_use", "design", "summarisation", "general"]
S1_DIFFICULTY = ["trivial", "easy", "moderate", "hard", "frontier"]
S1_STAKES = ["negligible", "low", "medium", "high"]
S1_FLAGS = ["needs_tools", "needs_vision", "needs_long_context", "follow_up"]


class S1Router:
    key = "s1-llm-auto-router"

    def __init__(self, threads: int = 4):
        import numpy as np
        from tokenizers import Tokenizer
        self.np = np
        base = model_dir() / self.key
        self.entry = manifest_entry(self.key)
        self.temps = json.loads((base / "meta.json").read_text())["temperatures"]
        self.tok = Tokenizer.from_file(str(base / "tokenizer" / "tokenizer.json"))
        self.tok.enable_truncation(512, strategy="only_second")
        self.sess = _session(base / "model.gq.onnx", threads)
        self.threads = threads
        self.version = f"{self.entry['repo']}@{self.entry['revision'][:12]}"

    def embed(self, request: str, context: str = "(new conversation)"):
        """Pooled [CLS] vector after the final norm: the representation all s1 heads read."""
        np = self.np
        if not hasattr(self, "_pooled"):
            self._pooled = _session(_pooled_output_graph(model_dir() / self.key / "model.gq.onnx"), self.threads)
        enc = self.tok.encode(context[:600], request)
        ids = np.asarray([enc.ids], dtype=np.int64)
        t0 = time.perf_counter()
        out = self._pooled.run(["pooled"], {"input_ids": ids, "attention_mask": np.ones_like(ids)})[0][0]
        return out, int(ids.shape[1]), round((time.perf_counter() - t0) * 1000, 2)

    def classify(self, request: str, context: str = "(new conversation)") -> dict:
        np = self.np
        enc = self.tok.encode(context[:600], request)
        ids = np.asarray([enc.ids], dtype=np.int64)
        t0 = time.perf_counter()
        cat, dif, stk, flg = self.sess.run(None, {"input_ids": ids, "attention_mask": np.ones_like(ids)})
        ms = (time.perf_counter() - t0) * 1000

        def sm(x, t):
            e = np.exp((x - x.max()) / t)
            return e / e.sum()
        pd, ps, pc = sm(dif[0], self.temps["difficulty"]), sm(stk[0], self.temps["stakes"]), sm(cat[0], self.temps["category"])
        pf = 1 / (1 + np.exp(-flg[0] / self.temps["flags"]))
        return {
            "difficulty_probabilities": {k: round(float(v), 4) for k, v in zip(S1_DIFFICULTY, pd)},
            "difficulty_expected": round(float((np.arange(5) * pd).sum()), 3),
            "stakes_expected": round(float((np.arange(4) * ps).sum()), 3),
            "category": S1_CATEGORIES[int(pc.argmax())],
            "category_probabilities": {k: round(float(v), 4) for k, v in zip(S1_CATEGORIES, pc)},
            "flags": {k: round(float(v), 4) for k, v in zip(S1_FLAGS, pf)},
            "input_tokens": int(ids.shape[1]),
            "latency_ms": round(ms, 2),
            "score_kind": "temperature-scaled probabilities (vendor-calibrated on its own dev set, not on this domain)",
        }


def _pooled_output_graph(src: Path) -> Path:
    """Expose the pooled encoder vector that feeds s1's heads as an extra output ("pooled")."""
    dst = src.with_name(src.stem + ".pooled.onnx")
    if dst.exists():
        return dst
    import onnx
    from onnx import helper
    m = onnx.load(str(src), load_external_data=False)
    g = m.graph
    head = next(n for n in g.node if n.output[0] == "category")
    producer = {o: n for n in g.node for o in n.output}
    node = producer[head.input[0]] if head.input[0] in producer else head
    while node.op_type != "Gather":
        node = producer[node.input[0]]
    g.node.append(helper.make_node("Identity", [node.output[0]], ["pooled"], name="tw_pooled"))
    g.output.append(helper.make_tensor_value_info("pooled", onnx.TensorProto.FLOAT, ["b", "h"]))
    onnx.save(m, str(dst))
    return dst


# --------------------------------------------------------------- local LM
@dataclass
class Generation:
    text: str
    prompt_tokens: int
    completion_tokens: int
    prefill_ms: float
    decode_ms: float
    stopped: str


def _last_position_graph(src: Path) -> Path:
    """Insert Slice(seq=-1) before the LM head so only last-position logits are produced.

    Mathematically identical for the last position; avoids a [T x vocab] tensor.
    Cached next to the source graph (outside the repository).
    """
    dst = src.with_name(src.stem + ".lastpos.onnx")
    if dst.exists():
        return dst
    import numpy as np
    import onnx
    from onnx import helper, numpy_helper
    m = onnx.load(str(src), load_external_data=False)
    g = m.graph
    producer = {o: n for n in g.node for o in n.output}
    node = producer["logits"]
    while node.op_type not in ("MatMul", "MatMulNBits", "Gemm"):
        node = producer[node.input[0]]
    hidden = node.input[0]
    consts = {"tw_s": -1, "tw_e": 2 ** 62, "tw_a": 1}
    for name, v in consts.items():
        g.initializer.append(numpy_helper.from_array(np.array([v], dtype=np.int64), name=name))
    sl = helper.make_node("Slice", [hidden, "tw_s", "tw_e", "tw_a"], ["tw_last_hidden"], name="tw_last_position")
    node.input[0] = "tw_last_hidden"
    idx = list(g.node).index(node)
    g.node.insert(idx, sl)
    for out in g.output:
        if out.name == "logits":
            out.type.tensor_type.shape.dim[1].dim_param = "one"
    onnx.save(m, str(dst))
    return dst


class LocalLM:
    def __init__(self, key: str, threads: int = 4):
        import numpy as np
        from tokenizers import Tokenizer
        self.np = np
        self.key = key
        self.entry = manifest_entry(key)
        base = model_dir() / key
        paths = {f["path"] for f in self.entry["files"]}
        self.arch = "qwen3_5" if any("embed_tokens" in p for p in paths) else "qwen2"
        dec = next(p for p in paths if p.endswith(".onnx") and "embed_tokens" not in p)
        self.graph = _last_position_graph(base / dec)
        self.sess = _session(self.graph, threads)
        self.embed = _session(base / next(p for p in paths if p.endswith("embed_tokens_q4.onnx")), threads) if self.arch == "qwen3_5" else None
        self.tok = Tokenizer.from_file(str(base / "tokenizer.json"))
        self.inputs = {i.name: i for i in self.sess.get_inputs()}
        self.state_inputs = [n for n in self.inputs if n.startswith("past")]
        self.version = f"{self.entry['repo']}@{self.entry['revision'][:12]}"
        self.im_end = self.tok.token_to_id("<|im_end|>")
        self.eos = {i for i in (self.im_end, self.tok.token_to_id("<|endoftext|>")) if i is not None}
        self.graph_fingerprint = _sha256_prefix(self.graph)

    # prompts --------------------------------------------------------------
    def chat(self, messages: list[dict], *, assistant_prefix: str = "") -> str:
        parts = [f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>\n" for m in messages]
        head = "<|im_start|>assistant\n"
        if self.arch == "qwen3_5":
            head += "<think>\n\n</think>\n\n"  # non-thinking mode, as in the model's own template
        return "".join(parts) + head + assistant_prefix

    def count_tokens(self, text: str) -> int:
        return len(self.tok.encode(text, add_special_tokens=False).ids)

    # forward ----------------------------------------------------------------
    def _empty_state(self):
        np = self.np
        state = {}
        for n in self.state_inputs:
            shape = [1 if d == "batch_size" else (0 if isinstance(d, str) else d) for d in self.inputs[n].shape]
            state[n] = np.zeros(shape, dtype=np.float32)
        return state

    def _step(self, ids, past_len: int, state):
        np = self.np
        n = ids.shape[1]
        feeds = dict(state)
        feeds["attention_mask"] = np.ones((1, past_len + n), dtype=np.int64)
        pos = np.arange(past_len, past_len + n, dtype=np.int64)[None, :]
        if self.arch == "qwen3_5":
            feeds["inputs_embeds"] = self.embed.run(None, {"input_ids": ids})[0]
            feeds["position_ids"] = np.stack([pos, pos, pos])
        else:
            feeds["input_ids"] = ids
            feeds["position_ids"] = pos
        outs = self.sess.run(None, feeds)
        names = [o.name for o in self.sess.get_outputs()]
        logits = outs[0][0, -1]
        new_state = {}
        for name, val in zip(names[1:], outs[1:]):
            new_state[name.replace("present_", "past_").replace("present.", "past_key_values.")] = val
        return logits, new_state

    def assistant_header(self) -> str:
        return "<|im_start|>assistant\n" + ("<think>\n\n</think>\n\n" if self.arch == "qwen3_5" else "")

    def extend(self, text: str, state=None, past_len: int = 0):
        """Run `text` after a cached state (prefix caching). Returns (last logits, new state, new length)."""
        np = self.np
        ids = np.asarray([self.tok.encode(text, add_special_tokens=False).ids], dtype=np.int64)
        logits, new_state = self._step(ids, past_len, state if state is not None else self._empty_state())
        return logits, new_state, past_len + int(ids.shape[1])

    def restrict(self, logits, labels: list[str]) -> dict:
        """Normalised scores over single-token labels (uncalibrated)."""
        np = self.np
        ids = []
        for lab in labels:
            enc = self.tok.encode(lab, add_special_tokens=False).ids
            if len(enc) != 1:
                raise ValueError(f"label {lab!r} is not a single token")
            ids.append(enc[0])
        z = logits - logits.max()
        lp = z - np.log(np.exp(z).sum())
        sub = lp[ids]
        p = np.exp(sub - sub.max())
        p = p / p.sum()
        return {"probabilities": {lab: round(float(v), 4) for lab, v in zip(labels, p)},
                "mass": round(float(np.exp(sub).sum()), 4)}

    def next_token_logprobs(self, prompt: str):
        np = self.np
        ids = np.asarray([self.tok.encode(prompt, add_special_tokens=False).ids], dtype=np.int64)
        t0 = time.perf_counter()
        logits, _ = self._step(ids, 0, self._empty_state())
        ms = (time.perf_counter() - t0) * 1000
        z = logits - logits.max()
        return z - np.log(np.exp(z).sum()), int(ids.shape[1]), ms

    def choose(self, prompt: str, labels: list[str]) -> dict:
        """Constrained choice: read the next-token distribution over single-token labels."""
        np = self.np
        ids = []
        for lab in labels:
            enc = self.tok.encode(lab, add_special_tokens=False).ids
            if len(enc) != 1:
                raise ValueError(f"label {lab!r} is not a single token")
            ids.append(enc[0])
        lp, n_tokens, ms = self.next_token_logprobs(prompt)
        sub = lp[ids]
        p = np.exp(sub - sub.max())
        p = p / p.sum()
        top_any = int(lp.argmax())
        return {"probabilities": {lab: round(float(v), 4) for lab, v in zip(labels, p)},
                "mass_on_labels": round(float(np.exp(lp[ids]).sum()), 4),
                "unconstrained_top_token": self.tok.decode([top_any]),
                "prompt_tokens": n_tokens, "latency_ms": round(ms, 1)}

    def generate_continue(self, text: str, state=None, past_len: int = 0, max_new_tokens: int = 160):
        """Append `text` to a cached conversation state, then decode greedily.

        Returns (Generation, new_state, new_past_len). The new state includes the
        generated tokens (but not the stop token), so a later call can append the
        stop token and the next message: KV-cache reuse across agent steps.
        """
        np = self.np
        ids = np.asarray([self.tok.encode(text, add_special_tokens=False).ids], dtype=np.int64)
        t0 = time.perf_counter()
        logits, state = self._step(ids, past_len, state if state is not None else self._empty_state())
        past = past_len + int(ids.shape[1])
        prefill = (time.perf_counter() - t0) * 1000
        out: list[int] = []
        stopped = "max_new_tokens"
        t1 = time.perf_counter()
        for _ in range(max_new_tokens):
            nxt = int(logits.argmax())
            if nxt in self.eos:
                stopped = "eos"
                break
            out.append(nxt)
            logits, state = self._step(np.asarray([[nxt]], dtype=np.int64), past, state)
            past += 1
        decode = (time.perf_counter() - t1) * 1000
        gen = Generation(self.tok.decode(out).strip(), int(ids.shape[1]), len(out), round(prefill, 1), round(decode, 1), stopped)
        return gen, state, past

    def generate(self, prompt: str, max_new_tokens: int = 160) -> Generation:
        np = self.np
        ids = np.asarray([self.tok.encode(prompt, add_special_tokens=False).ids], dtype=np.int64)
        t0 = time.perf_counter()
        logits, state = self._step(ids, 0, self._empty_state())
        prefill = (time.perf_counter() - t0) * 1000
        out: list[int] = []
        past = ids.shape[1]
        stopped = "max_new_tokens"
        t1 = time.perf_counter()
        for _ in range(max_new_tokens):
            nxt = int(logits.argmax())
            if nxt in self.eos:
                stopped = "eos"
                break
            out.append(nxt)
            logits, state = self._step(np.asarray([[nxt]], dtype=np.int64), past, state)
            past += 1
        decode = (time.perf_counter() - t1) * 1000
        return Generation(self.tok.decode(out).strip(), int(ids.shape[1]), len(out), round(prefill, 1), round(decode, 1), stopped)
