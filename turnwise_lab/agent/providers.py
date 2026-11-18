"""Decision providers, context selectors and generation backends.

Learned:   LocalLMDecider / LocalLMContextSelector (constrained choice with a local
           instruct model), S1TierAdvisor (fixed-head classifier, tier signal only).
Baseline:  HeuristicDecider (deterministic rules; mandatory comparison).
Tests:     ScriptedDecider (never used for the demonstration).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
import re
import time

from .context import BLOCKS_BY_ID, eligible_blocks, select_full, select_heuristic, select_lexical
from .contracts import (SCORE_LM, SCORE_RULE, SCORE_SCRIPTED, ContextDecision, Decision, Question)
from .host import CATALOG, CATALOG_BY_ID, Host
from .world import SERVICES

SERVICE_ALIASES = {"checkout": "checkout", "payments": "payments", "payment": "payments", "search": "search",
                   "auth": "auth", "authentication": "auth", "login": "auth"}


def named_services(text: str) -> list[str]:
    out = []
    for w in re.findall(r"[a-z]+", text.lower()):
        s = SERVICE_ALIASES.get(w)
        if s and s not in out:
            out.append(s)
    return out


def _decision_from_target(target: str, service: str | None, state, provider: str, model: str, qs, rationale="") -> Decision:
    cap = CATALOG_BY_ID[target]
    if "service" in cap.params:
        args = {"service": service} if service else {}
    elif "query" in cap.params:
        args = {"query": state.user_message[:300]}
    else:
        args = {"message": state.user_message[:300]}
    op = "call_workflow" if cap.kind == "workflow" else "call_tool"
    return Decision(op, target, args, provider=provider, model=model, questions=qs, rationale=rationale)


# ------------------------------------------------------------------ scripted
class ScriptedDecider:
    """Deterministic test double. Each entry may be a Decision or a callable(state) -> Decision."""
    name = "scripted"

    def __init__(self, script):
        self.script = list(script)
        self.seen_snapshots: list[dict] = []

    def decide(self, state, host) -> Decision:
        self.seen_snapshots.append(state.compact_snapshot())
        if not self.script:
            raise RuntimeError("script exhausted")
        item = self.script.pop(0)
        d = item(state) if callable(item) else item
        d.provider, d.model = "scripted", "test-script"
        d.questions = d.questions or [Question("operation", [], d.operation, score_kind=SCORE_SCRIPTED)]
        return d


# ----------------------------------------------------------------- heuristic
WRITE_RULES = [(r"\b(roll ?back|revert|undo the (deploy|release))\b", "rollback_deployment"),
               (r"\b(page|wake up|call out)\b.*\b(on.?call|engineer|them|team)\b|\bpage (them|the)\b", "page_oncall"),
               (r"\b(post|publish|announce)\b.*\bstatus\b", "post_status_update")]
LOOKUP_RULES = [(r"\b(health|healthy|status|degraded|up|down)\b", "get_service_health"),
                (r"\b(error rate|errors?|5xx|failures?|failing)\b", "get_error_metrics"),
                (r"\b(deploy\w*|release\w*|changed?|approved|rollout)\b", "get_deployment_history"),
                (r"\b(config\w*|baseline|drift\w*|settings?)\b", "get_config_diff"),
                (r"\b(owns?|owner|on.?call|team)\b", "get_service_owner"),
                (r"\b(runbooks?|procedure|playbook|notes?)\b", "search_runbooks"),
                (r"\bsmoke\b", "run_smoke_checks")]
ANALYSIS = r"\b(why|explain\w*|could|cause\w*|root cause|related|because|due to|responsible|behind|blame\w*|led to|linked)\b"
INVESTIGATION = ("get_error_metrics", "get_deployment_history")
SMALLTALK = r"^\s*(hi|hello|hey|thanks|thank you|good (morning|afternoon|evening))\b"
NEGATION = r"\b(don'?t|do not|never|without)\b"


class HeuristicDecider:
    name = "rules"
    model = "turnwise-rules-v0.6"

    def decide(self, state, host: Host) -> Decision:
        t0 = time.perf_counter()
        text = state.user_message.lower()
        services = named_services(state.user_message) or named_services(" ".join(m["content"] for m in state.conversation if m["role"] == "user")[-400:])
        service = services[0] if services else None
        done = {(o.target, o.arguments.get("service")) for o in state.observations if o.status == "ok"}
        errored = [o for o in state.observations if o.status == "error"]

        def mk(op, target=None, tier=None, why=""):
            q = [Question("operation", [], target or tier or op, score_kind=SCORE_RULE,
                          latency_ms=round((time.perf_counter() - t0) * 1000, 3), input_tokens=None, note=why)]
            if op in ("call_tool", "call_workflow"):
                return _decision_from_target(target, service, state, self.name, self.model, q, why)
            return Decision(op, model_tier=tier, provider=self.name, model=self.model, questions=q, rationale=why)

        if errored and not any(o.status == "ok" and o.target == errored[-1].target for o in state.observations):
            last = errored[-1]
            if sum(1 for o in errored if o.target == last.target) <= host.limits.max_retries_per_call:
                return Decision("call_tool", last.target, dict(last.arguments), provider=self.name, model=self.model,
                                questions=[Question("operation", [], last.target, note="retry after transient error")],
                                rationale="retry after transient error")
        if not state.observations and re.search(SMALLTALK, text) and not services:
            return mk("call_model", tier="light", why="small talk")
        if not re.search(NEGATION, text):
            for pat, cap in WRITE_RULES:
                if re.search(pat, text):
                    return mk("call_tool", cap, why="write intent: host will require approval")
        if re.search(ANALYSIS, text):
            if service is None:
                return mk("clarify", why="analysis requested but no service identified")
            for cap in INVESTIGATION:
                if (cap, service) not in done:
                    return mk("call_tool", cap, why="investigation template: gather evidence")
            return mk("call_model", tier="heavy", why="evidence gathered; synthesis needs reasoning")
        wanted = [cap for pat, cap in LOOKUP_RULES if re.search(pat, text)]
        if wanted:
            if service is None and CATALOG_BY_ID[wanted[0]].params == ("service",):
                return mk("clarify", why="lookup needs a service")
            for cap in wanted:
                key = (cap, service if CATALOG_BY_ID[cap].params == ("service",) else None)
                if key not in done:
                    return mk("call_tool" if CATALOG_BY_ID[cap].kind == "tool" else "call_workflow", cap, why="lookup rule")
            return mk("finish", why="verified data answers the lookup")
        return mk("call_model", tier="light", why="no rule matched; short general reply")


# ------------------------------------------------------------- learned (LM)
# Verbalizer: every operation is named by a word whose first token is distinct,
# so ONE forward pass yields a score for every operation.
VERB = {"get_service_health": "health", "get_error_metrics": "errors", "get_deployment_history": "deploys",
        "get_config_diff": "config", "get_service_owner": "owner", "search_runbooks": "runbooks",
        "run_smoke_checks": "smoke", "rollback_deployment": "rollback", "page_oncall": "page",
        "post_status_update": "post", "finish": "finish", "light_model": "light", "heavy_model": "heavy",
        "clarify": "clarify"}
OPS = list(VERB)
DESCR = {"finish": "show the verified data already gathered as the answer, no model",
         "light_model": "a light model writes a short reply that needs no evidence reasoning",
         "heavy_model": "a strong model reasons over the gathered evidence to explain causes or uncertainty",
         "clarify": "ask the user which service or change they mean"}
# Fixed worked examples (fictional service 'billing'; never an evaluation case).
FEW_SHOT = [
    ("Is billing healthy right now?", "none yet", "get_service_health"),
    ("Is billing healthy right now?", '1. health(service=billing) -> ok: {"status":"healthy"}', "finish"),
    ("Did the new billing release cause the spike in failures?", "none yet", "get_error_metrics"),
    ("Did the new billing release cause the spike in failures?",
     '1. errors(service=billing) -> ok: {"before_pct":0.2,"after_pct":4.1,"change_point":"09:12"}', "get_deployment_history"),
    ("Did the new billing release cause the spike in failures?",
     '1. errors(service=billing) -> ok: {...increase at 09:12...}\n2. deploys(service=billing) -> ok: {"deploys":[{"at":"09:10","change":"new retry policy"}]}',
     "heavy_model"),
    ("Did the new billing release cause the spike in failures?",
     '1. errors(service=billing) -> ok: {"before_pct":0.2,"after_pct":0.2,"change_point":null}', "light_model"),
    ("Thanks, that's all for now.", "none yet", "light_model"),
    ("Roll billing back to the previous build.", "none yet", "rollback_deployment"),
    ("Can you look into it?", "none yet", "clarify"),
]


def admissible(state, focus_service: str | None) -> list[str]:
    """Host-side action mask from trusted state: no repeat of a call that already succeeded."""
    ok = [o for o in state.observations if o.status == "ok"]
    out = []
    for op in OPS:
        cap = CATALOG_BY_ID.get(op)
        if cap is not None and not cap.side_effect:
            arg = focus_service if "service" in cap.params else state.user_message[:300]
            key = "service" if "service" in cap.params else "query"
            if any(o.target == op and o.arguments.get(key) == arg for o in ok):
                continue
        if op == "finish" and not ok:
            continue
        out.append(op)
    return out


class GenerativeChooser:
    """Qwen-class instruct model scoring all 14 operations in one cached forward pass."""

    def __init__(self, lm):
        self.lm = lm
        self.version = lm.version
        self.first = {}
        for op, w in VERB.items():
            self.first[op] = lm.tok.encode(" " + w, add_special_tokens=False).ids[0]
        if len(set(self.first.values())) != len(self.first):
            raise ValueError("verbalizer first tokens collide for this tokenizer")
        cat = "\n".join(f"- {VERB[op]}: {CATALOG_BY_ID[op].description if op in CATALOG_BY_ID else DESCR[op]}" for op in OPS)
        ex = "\n\n".join(f"Request: {r}\nSteps taken:\n{st}\nNext operation: {VERB[a]}" for r, st, a in FEW_SHOT)
        system = ("You are the decision layer of an incident-response assistant. You never answer the user; you choose the next operation. "
                  "Gather evidence with tools before explaining a cause. Answer a lookup with finish once its data has been fetched. "
                  "Never repeat a step that already succeeded. Side-effecting operations only create an approval request.")
        self.prefix = (f"<|im_start|>system\n{system}<|im_end|>\n<|im_start|>user\nOperations:\n{cat}\n\n"
                       f"Examples (fictional service 'billing'):\n\n{ex}\n\nNow the real case.\n")
        self._cache = None

    def _prefix_state(self):
        if self._cache is None:
            _, st, n = self.lm.extend(self.prefix)
            self._cache = (st, n)
        return self._cache

    @staticmethod
    def render_steps(state) -> str:
        lines = []
        for i, o in enumerate(state.observations[-6:]):
            s = o.summary(260)
            for op, w in VERB.items():
                if s.startswith(op + "("):
                    s = w + s[len(op):]
            lines.append(f"{i + 1}. {s}")
        return "\n".join(lines) or "none yet"

    def scores(self, state) -> dict:
        import numpy as np
        st, n = self._prefix_state()
        earlier = " | ".join(m["content"][:160] for m in state.conversation if m["role"] == "user")[-400:]
        dyn = ((f"Earlier messages: {earlier}\n" if earlier else "") +
               f"Request: {state.user_message}\nSteps taken:\n{self.render_steps(state)}\n"
               f"Reply with the next operation name only.<|im_end|>\n" + self.lm.assistant_header() + "Next operation:")
        t0 = time.perf_counter()
        logits, _, n2 = self.lm.extend(dyn, state=st, past_len=n)
        ms = (time.perf_counter() - t0) * 1000
        z = logits - logits.max()
        lp = z - np.log(np.exp(z).sum())
        raw = {op: float(lp[self.first[op]]) for op in OPS}
        mass = float(sum(np.exp(v) for v in raw.values()))
        m = max(raw.values())
        e = {op: np.exp(v - m) for op, v in raw.items()}
        tot = sum(e.values())
        return {"probabilities": {op: round(e[op] / tot, 5) for op in OPS}, "logprobs": raw, "mass": round(mass, 4),
                "latency_ms": round(ms, 1), "input_tokens": n2 - n, "cached_prefix_tokens": n}


def focus_services(state) -> list[str]:
    named = named_services(state.user_message)
    if named:
        return named
    seen = []
    for o in state.observations:
        s = o.arguments.get("service")
        if s and s not in seen:
            seen.append(s)
    if seen:
        return seen
    return named_services(" ".join(m["content"] for m in state.conversation if m["role"] == "user")[-400:])


class ArgumentBuilder:
    """Cheapest reliable mechanism first: deterministic -> light model -> strong model -> clarify."""

    def __init__(self, light_lm=None, strong_lm=None, light_min: float = 0.6, strong_min: float = 0.5, deterministic: bool = True):
        self.light_lm, self.strong_lm = light_lm, strong_lm
        self.light_min, self.strong_min = light_min, strong_min
        self.deterministic = deterministic

    def _choose(self, lm, state, target) -> tuple[str, dict, float, int]:
        opts = list(SERVICES) + ["unclear"]
        earlier = " | ".join(m["content"][:200] for m in state.conversation)[-600:]
        prompt = lm.chat([{"role": "system", "content": "You extract one argument for a tool call. Reply with one word."},
                          {"role": "user", "content": (f"Conversation so far: {earlier or 'none'}\nRequest: {state.user_message}\n"
                                                       f"Steps taken:\n{GenerativeChooser.render_steps(state)}\n"
                                                       f"Which service should {target} be called for? Options: {', '.join(opts)}. "
                                                       "Say unclear if the request does not identify one service.")}],
                         assistant_prefix="Service:")
        lp, n, ms = lm.next_token_logprobs(prompt)
        ids = [lm.tok.encode(" " + o, add_special_tokens=False).ids[0] for o in opts]
        import numpy as np
        sub = lp[ids]
        p = np.exp(sub - sub.max())
        p = p / p.sum()
        probs = {o: round(float(v), 4) for o, v in zip(opts, p)}
        best = max(probs, key=probs.get)
        return best, probs, round(ms, 1), n

    def build(self, target: str, state) -> tuple[dict | None, Question]:
        cap = CATALOG_BY_ID[target]
        if not cap.params:
            return {}, Question("arguments", [], "{}", None, SCORE_RULE, 0.0, None, note="mechanism: none needed")
        if "query" in cap.params:
            return {"query": state.user_message[:300]}, Question("arguments", [], "query=user request", None, SCORE_RULE, 0.0, None,
                                                                note="mechanism: deterministic (query = user request)")
        if "message" in cap.params:
            return {"message": state.user_message[:300]}, Question("arguments", [], "message=user request", None, SCORE_RULE, 0.0,
                                                                  None, note="mechanism: deterministic (message = user request)")
        cands = focus_services(state)
        if self.deterministic and len(cands) == 1:
            return {"service": cands[0]}, Question("arguments", list(SERVICES), cands[0], None, SCORE_RULE, 0.0, None,
                                                   note="mechanism: deterministic (one service named or in focus in trusted state)")
        trail = []
        for lm, floor, label in ((self.light_lm, self.light_min, "light model"), (self.strong_lm, self.strong_min, "strong model")):
            if lm is None:
                continue
            best, probs, ms, n = self._choose(lm, state, target)
            trail.append((label, best, probs, ms, n))
            if best != "unclear" and probs[best] >= floor:
                return {"service": best}, Question("arguments", list(SERVICES) + ["unclear"], best, probs, SCORE_LM,
                                                   round(sum(t[3] for t in trail), 1), sum(t[4] for t in trail),
                                                   note=f"mechanism: {label} extraction ({' -> '.join(t[0] + ':' + t[1] for t in trail)})")
        note = "mechanism: " + (" -> ".join(f"{t[0]}:{t[1]}({t[2][t[1]]:.2f})" for t in trail) or "no extractor") + " -> clarify"
        return None, Question("arguments", list(SERVICES) + ["unclear"], "unclear", trail[-1][2] if trail else None,
                              SCORE_LM if trail else SCORE_RULE, round(sum(t[3] for t in trail), 1),
                              sum(t[4] for t in trail) or None, note=note)


def _finalize_op(op, state, provider, model, qs, args_builder, rationale=""):
    if op in CATALOG_BY_ID:
        args, aq = args_builder.build(op, state)
        qs.append(aq)
        if args is None:
            return Decision("clarify", provider=provider, model=model, questions=qs,
                            rationale="argument could not be constructed reliably")
        cap = CATALOG_BY_ID[op]
        return Decision("call_workflow" if cap.kind == "workflow" else "call_tool", op, args, provider=provider, model=model,
                        questions=qs, rationale=rationale)
    if op in ("light_model", "heavy_model"):
        return Decision("call_model", model_tier=op.split("_")[0], provider=provider, model=model, questions=qs, rationale=rationale)
    return Decision(op, provider=provider, model=model, questions=qs, rationale=rationale)


class LocalLMDecider:
    """Mechanism 2: the generative chooser alone (argmax over admissible operations)."""
    name = "generative-chooser"

    def __init__(self, chooser: GenerativeChooser, args_builder: ArgumentBuilder):
        self.chooser, self.args = chooser, args_builder
        self.model = chooser.version

    def decide(self, state, host) -> Decision:
        sc = self.chooser.scores(state)
        cands = focus_services(state)
        allowed = admissible(state, cands[0] if len(cands) == 1 else None)
        p = {op: sc["probabilities"][op] for op in allowed}
        z = sum(p.values()) or 1.0
        p = {k: round(v / z, 4) for k, v in p.items()}
        op = max(p, key=p.get)
        q = Question("operation", allowed, op, p, SCORE_LM, sc["latency_ms"], sc["input_tokens"],
                     note=f"{sc['cached_prefix_tokens']} cached prefix tokens; label mass {sc['mass']}; masked {sorted(set(OPS) - set(allowed))}")
        return _finalize_op(op, state, self.name, self.model, [q], self.args)


class LearnedDecider:
    """Mechanism 1: turnwise-dm, a trained head over (chooser scores, s1 heads, typed state)."""
    name = "turnwise-dm"

    def __init__(self, head: dict, chooser: GenerativeChooser, s1, args_builder: ArgumentBuilder, *, gate: float | None = None):
        import numpy as np
        self.np = np
        self.head, self.chooser, self.s1, self.args = head, chooser, s1, args_builder
        self.mu, self.sd = np.asarray(head["mean"]), np.asarray(head["std"])
        self.W, self.b, self.T = np.asarray(head["W"]), np.asarray(head["b"]), head["temperature"]
        self.gate = head.get("gate", 0.5) if gate is None else gate
        self.model = f"{head['name']}-{head['version']} (head) + {chooser.version} + {s1.version}"

    def features(self, state):
        from .dm_features import feature_vector
        return feature_vector(state, self.chooser, self.s1)

    def decide(self, state, host) -> Decision:
        np = self.np
        t0 = time.perf_counter()
        x, parts = self.features(state)
        z = ((x - self.mu) / self.sd) @ self.W + self.b
        e = np.exp((z - z.max()) / self.T)
        p_all = e / e.sum()
        cands = focus_services(state)
        allowed = admissible(state, cands[0] if len(cands) == 1 else None)
        idx = {op: i for i, op in enumerate(self.head["ops"])}
        p = {op: float(p_all[idx[op]]) for op in allowed}
        zt = sum(p.values()) or 1.0
        p = {k: round(v / zt, 4) for k, v in p.items()}
        ranked = sorted(p.items(), key=lambda kv: -kv[1])
        op, top = ranked[0]
        ms = round((time.perf_counter() - t0) * 1000, 1)
        q = Question("operation", allowed, op, p, "temperature-scaled probability from turnwise-dm "
                     "(calibrated on its synthetic template-held-out validation split only)", ms,
                     parts["chooser_tokens"] + parts["s1_tokens"],
                     note=f"chooser {parts['chooser_ms']} ms + s1 {parts['s1_ms']} ms; masked {sorted(set(OPS) - set(allowed))}")
        qs = [q]
        if top < self.gate and op != "heavy_model":
            qs.append(Question("escalation", ["keep", "escalate"], "escalate", None, SCORE_RULE, 0.0, None,
                               note=f"top probability {top:.2f} < gate {self.gate}: conservative escalation to the strong model"))
            return Decision("call_model", model_tier="heavy", provider=self.name, model=self.model, questions=qs,
                            rationale=f"uncertain ({op} at {top:.2f}); escalate to the strong model with verification")
        return _finalize_op(op, state, self.name, self.model, qs, self.args)


class LocalLMContextSelector:
    """One yes/no question per eligible optional block, sharing one cached prefix per call."""
    name = "decision-model blocks"

    def __init__(self, lm):
        self.lm = lm
        self.yes = lm.tok.encode(" yes", add_special_tokens=False).ids[0]
        self.no = lm.tok.encode(" no", add_special_tokens=False).ids[0]

    def select(self, state, tier, permitted) -> ContextDecision:
        import numpy as np
        elig, _ = eligible_blocks(state, tier, permitted)
        base = ("<|im_start|>system\nYou decide which context blocks a response step needs. Include a block only if the reply "
                "would be wrong or incomplete without it.<|im_end|>\n<|im_start|>user\n"
                f"Request: {state.user_message}\nSteps taken:\n{GenerativeChooser.render_steps(state)}\n"
                f"Next step: a {tier} model writes the reply.\n")
        t0 = time.perf_counter()
        _, st, n = self.lm.extend(base)
        shared = (time.perf_counter() - t0) * 1000
        qs, chosen = [], []
        for i, bid in enumerate(elig):
            b = BLOCKS_BY_ID[bid]
            suffix = (f"Block '{bid}': {b.purpose}\nShould the reply prompt include this block? Answer yes or no.<|im_end|>\n"
                      + self.lm.assistant_header() + "Answer:")
            t1 = time.perf_counter()
            logits, _, n2 = self.lm.extend(suffix, state=st, past_len=n)
            ms = (time.perf_counter() - t1) * 1000 + (shared if i == 0 else 0)
            ly, ln = float(logits[self.yes]), float(logits[self.no])
            yes = 1.0 / (1.0 + np.exp(ln - ly))
            if yes >= 0.5:
                chosen.append(bid)
            qs.append(Question(f"include:{bid}", ["yes", "no"], "yes" if yes >= 0.5 else "no",
                               {"yes": round(yes, 4), "no": round(1 - yes, 4)}, SCORE_LM, round(ms, 1),
                               (n2 - n) + (n if i == 0 else 0)))
        return ContextDecision(chosen, "decision_model", qs, self.name, self.lm.version)


class RuleContextSelector:
    def __init__(self, policy: str):
        self.name = policy
        self.policy = policy
        self.fn: Callable = {"full": select_full, "lexical": select_lexical, "heuristic": select_heuristic,
                             "minimal": lambda s, t, p: []}[policy]

    def select(self, state, tier, permitted) -> ContextDecision:
        t0 = time.perf_counter()
        chosen = self.fn(state, tier, permitted)
        q = Question("blocks", [], ",".join(chosen), None, SCORE_RULE, round((time.perf_counter() - t0) * 1000, 3))
        return ContextDecision(chosen, self.policy, [q], f"{self.policy} policy", "rule")


class S1TierAdvisor:
    """Tier from s1-llm-auto-router difficulty (its own head; it cannot choose tools)."""

    def __init__(self, s1, threshold: float = 1.5):
        self.s1, self.threshold = s1, threshold

    def advise(self, state) -> tuple[str, Question]:
        ctx = " | ".join(o.summary(160) for o in state.observations[-3:]) or "(new conversation)"
        r = self.s1.classify(state.user_message, ctx)
        tier = "heavy" if r["difficulty_expected"] >= self.threshold else "light"
        q = Question("tier(s1 difficulty)", ["light", "heavy"], tier, r["difficulty_probabilities"],
                     "s1 temperature-scaled probabilities over difficulty levels", r["latency_ms"], r["input_tokens"],
                     note=f"expected difficulty {r['difficulty_expected']} vs threshold {self.threshold}")
        return tier, q


# --------------------------------------------------------------- generators
class PendingGenerator:
    """No backend: the prompt is assembled and recorded; nothing is generated."""

    def counter(self, tier):
        return None

    def generate(self, prompt, tier, max_new_tokens):
        return {"status": "pending", "tier": tier, "model": None, "text": "[generation pending: no backend configured]",
                "prompt_tokens": prompt.tokens, "completion_tokens": None, "prefill_ms": None, "decode_ms": None}


class LocalGenerator:
    def __init__(self, light, heavy):
        self.models = {"light": light, "heavy": heavy}

    def counter(self, tier):
        return self.models[tier].count_tokens

    def generate(self, prompt, tier, max_new_tokens):
        lm = self.models[tier]
        g = lm.generate(lm.chat(prompt.messages), max_new_tokens=max_new_tokens)
        return {"status": "ok", "tier": tier, "model": lm.version, "text": g.text, "prompt_tokens": g.prompt_tokens,
                "completion_tokens": g.completion_tokens, "prefill_ms": g.prefill_ms, "decode_ms": g.decode_ms,
                "stopped": g.stopped}
