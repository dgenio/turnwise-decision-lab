"""Train turnwise-dm: a small learned decision head for the agent loop.

Input  = [generative-chooser log-scores, s1 head outputs, typed state features
         computed by the host from trusted observations] (see dm_features.py).
Output = probabilities over the 14 next operations (7 reads, 3 writes,
         finish, light_model, heavy_model, clarify).

Supervision is synthetic and procedural: phrasing templates per intent are
executed through the real Host and IncidentWorld, and each intermediate state
is labelled with the next step of that intent's oracle procedure. Nothing here
uses the v0.5 sessions, the v0.6 showcase sentences or any held-out file.
The validation split holds out whole templates; a temperature is fitted on it.

    python -m turnwise_lab.agent.dm_train        # needs the s1 model locally (~10 s)
"""
from __future__ import annotations

from pathlib import Path
import hashlib
import json
import random

import numpy as np

from .contracts import Decision, Observation
from .host import CATALOG, Host
from .world import SERVICES, IncidentWorld

ROOT = Path(__file__).resolve().parents[2]
HEAD_PATH = ROOT / "models" / "turnwise-dm-head.json"
DATA_PATH = ROOT / "fixtures" / "v06_dm_train.jsonl"

OPS = [c.id for c in CATALOG] + ["finish", "light_model", "heavy_model", "clarify"]
READS = [c.id for c in CATALOG if not c.side_effect]

# Each intent: templates ({svc} = service mention) and a procedure. A procedure
# step is an op id, or a callable(observations) -> op id for branches.
def _cause_after_errors(obs):
    f = next(v for o in obs if o.status == "ok" for k, v in o.facts.items() if k.startswith("errors:"))
    return "get_deployment_history" if f["change_point"] else "light_model"


INTENTS = {
    "smalltalk": (["hello there", "hey, good morning", "thanks a lot, that helps", "cheers, that's all for now",
                   "good afternoon! anything I should know?", "thank you, much appreciated", "hi team assistant",
                   "ok great, thanks", "morning! how's your day going?", "appreciate the help", "that's everything, bye",
                   "nice work, thank you", "yo, you around?"], False, ["light_model"]),
    "general_question": (["what does p95 latency mean?", "explain what a canary release is in one sentence",
                          "what's the difference between a rollback and a hotfix?", "how do connection pools work, briefly?",
                          "what is an error budget?", "define mean time to recovery", "summarise what an SLO is",
                          "what does a 504 status code usually indicate?", "remind me what blue-green deployment means"], False, ["light_model"]),
    "status": (["is {svc} up?", "how is {svc} doing at the moment", "give me {svc}'s current status",
                "{svc} status please", "check whether {svc} is degraded", "current latency and error rate for {svc}?",
                "is {svc} healthy now?", "quick health check on {svc}"], True, ["get_service_health", "finish"]),
    "errors": (["show me the error rate trend for {svc}", "did errors go up on {svc}?", "{svc} error metrics around the last deploy",
                "when did {svc} start throwing errors", "has the {svc} failure rate changed?", "plot of {svc} 5xx rate"],
               True, ["get_error_metrics", "finish"]),
    "deploys": (["what changed in {svc} recently?", "list the recent {svc} deployments", "who approved the last {svc} release?",
                 "when was {svc} last deployed", "show {svc} deploy history", "which build is {svc} running after the rollout"],
                True, ["get_deployment_history", "finish"]),
    "config": (["has {svc}'s config drifted from baseline?", "compare {svc} settings with the approved baseline",
                "show the {svc} configuration diff", "is {svc} running the approved configuration?"], True,
               ["get_config_diff", "finish"]),
    "owner": (["who owns {svc}?", "who is on call for {svc}", "which team is responsible for {svc}",
               "give me the {svc} on-call rotation"], True, ["get_service_owner", "finish"]),
    "runbooks": (["find the runbook about connection pool exhaustion", "is there a procedure for rollbacks?",
                  "search our notes for caching issues", "what does the timeout runbook recommend",
                  "look up the status page policy", "do we have documentation on index shards?",
                  "pull up the incident notes about the auth rate limit", "is there a runbook for upstream timeouts?",
                  "what do our docs say about rolling back safely"], False, ["search_runbooks", "finish"]),
    "smoke": (["run the smoke checks on {svc}", "execute the standard checks for {svc}", "do the smoke test workflow for {svc}",
               "kick off {svc} smoke checks"], True, ["run_smoke_checks", "finish"]),
    "deploy_cause": (["did the latest {svc} release cause the errors?", "is the {svc} deploy responsible for the failures?",
                      "could the new {svc} build be behind the error spike?", "are the {svc} errors related to the recent rollout?",
                      "why are {svc} errors up since the release", "is the recent change to {svc} to blame for the failures?",
                      "explain whether the last {svc} deployment broke something"], True,
                     ["get_error_metrics", _cause_after_errors, "heavy_model"]),
    "config_cause": (["could config drift explain the {svc} problems?", "are the {svc} issues caused by its settings?",
                      "is a configuration change behind the {svc} degradation?", "explain whether {svc}'s config is the root cause"],
                     True, ["get_config_diff", "get_error_metrics", "heavy_model"]),
    "explain_status": (["why is {svc} degraded?", "what's wrong with {svc} right now and why?", "explain the {svc} slowdown",
                        "give me a diagnosis of the {svc} incident"], True,
                       ["get_service_health", "get_deployment_history", "heavy_model"]),
    "rollback": (["roll {svc} back", "revert the last {svc} deploy", "undo the {svc} release now", "please roll back {svc} to the previous build"],
                 True, ["rollback_deployment"]),
    "page": (["page the {svc} on-call", "wake up whoever is on call for {svc}", "escalate to the {svc} on-call engineer by paging them"],
             True, ["page_oncall"]),
    "post_status": (["post a status page update about {svc}", "publish an incident notice for {svc} on the status page",
                     "announce the {svc} degradation publicly"], True, ["post_status_update"]),
    "ambiguous": (["can you check it?", "what happened?", "is it broken again", "look into the errors please",
                   "why did it fail", "roll it back", "is the service ok?", "what's the status?", "who owns that one?",
                   "did the deploy break it?", "check the metrics for me", "can you fix the thing from earlier",
                   "what changed?", "page them"], False, ["clarify"]),
    "negated_write": (["don't roll {svc} back yet, just show me what changed", "no paging needed, who owns {svc}?",
                       "before any rollback, what did the last {svc} deploy change?"], True,
                      [None, "finish"]),  # first step depends on template; see _negated
}
NEGATED_FIRST = {0: "get_deployment_history", 1: "get_service_owner", 2: "get_deployment_history"}
VARIANTS_FOR = {"deploy_cause": ("baseline", "errors_flat", "no_recent_deploy", "metrics_flaky"),
                "errors": ("baseline", "metrics_flaky")}

SIGNALS = ["errors_increased", "errors_flat", "deploys_present", "deploys_empty", "health_degraded", "health_ok",
           "config_drift", "last_error", "service_named", "multiple_services", "has_conversation"]


def typed_features(state) -> list[float]:
    """Host-computed typed features from trusted state (no request-text routing)."""
    from .providers import named_services
    ok = [o for o in state.observations if o.status == "ok"]
    done = [1.0 if any(o.target == r for o in ok) else 0.0 for r in READS]
    f = {k: 0.0 for k in SIGNALS}
    for o in ok:
        for key, v in o.facts.items():
            kind = key.split(":")[0]
            if kind == "errors":
                f["errors_increased" if v.get("change_point") else "errors_flat"] = 1.0
            elif kind == "deploys":
                f["deploys_present" if v.get("deploys") else "deploys_empty"] = 1.0
            elif kind == "health":
                f["health_ok" if v.get("status") == "healthy" else "health_degraded"] = 1.0
            elif kind == "config" and not v.get("matches_baseline", True):
                f["config_drift"] = 1.0
    f["last_error"] = 1.0 if state.observations and state.observations[-1].status == "error" else 0.0
    n = len(named_services(state.user_message))
    f["service_named"] = 1.0 if n else 0.0
    f["multiple_services"] = 1.0 if n > 1 else 0.0
    f["has_conversation"] = 1.0 if state.conversation else 0.0
    return done + [f[k] for k in SIGNALS] + [min(len(state.observations), 6) / 6.0]


def state_context(state) -> str:
    """Compact observation summary given to the encoder as its context segment (<= 600 chars)."""
    parts = [o.summary(140) for o in state.observations[-4:]]
    return (" | ".join(parts) or "(no steps yet)")[:600]


class _S:
    def __init__(self, msg, observations):
        self.user_message, self.observations, self.conversation = msg, observations, []


def _execute(host, op, svc, msg, step):
    from .providers import _decision_from_target
    d = _decision_from_target(op, svc, _S(msg, []), "trainer", "procedure", [])
    return host.execute(d, step_index=step, call_id=f"train/{step}", user_text=msg)


def generate_examples(seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    rows = []
    for intent, (templates, needs_svc, proc) in INTENTS.items():
        for ti, tmpl in enumerate(templates):
            services = SERVICES if needs_svc else (None,)
            for svc in services:
                msg = tmpl.format(svc=svc) if svc else tmpl
                for variant in VARIANTS_FOR.get(intent, ("baseline",)):
                    if variant != "baseline" and svc != "checkout":
                        continue
                    host = Host(IncidentWorld(variant))
                    obs: list[Observation] = []
                    steps = list(proc)
                    if intent == "negated_write":
                        steps = [NEGATED_FIRST[ti], "finish"]
                    i = 0
                    while i < len(steps):
                        label = steps[i](obs) if callable(steps[i]) else steps[i]
                        rows.append({"intent": intent, "template": f"{intent}#{ti}", "message": msg, "variant": variant,
                                     "observations": [o.summary(140) for o in obs], "label": label,
                                     "_obs": list(obs)})
                        if label in READS:
                            o = _execute(host, label, svc, msg, len(obs))
                            obs.append(o)
                            if o.status == "error":
                                continue  # same step again: the label for the next state is a retry
                        else:
                            break
                        i += 1
                    if label == "light_model" and intent == "deploy_cause":
                        pass
    rng.shuffle(rows)
    return rows


def featurize(rows, chooser, s1) -> tuple[np.ndarray, list[int]]:
    from .dm_features import feature_vector
    X, y = [], []
    for r in rows:
        x, _ = feature_vector(_S(r["message"], r["_obs"]), chooser, s1)
        X.append(x)
        y.append(OPS.index(r["label"]))
    return np.asarray(X, dtype=np.float64), y


def _softmax(z):
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


def train_lr(X, y, l2=1e-3, iters=600, lr=0.5):
    n, d = X.shape
    k = len(OPS)
    W = np.zeros((d, k))
    b = np.zeros(k)
    Y = np.eye(k)[y]
    counts = np.bincount(y, minlength=k).astype(float)
    w_class = np.where(counts > 0, n / (k * np.maximum(counts, 1)), 0.0)
    sw = w_class[np.asarray(y)][:, None]  # class-balanced sample weights
    for _ in range(iters):
        P = _softmax(X @ W + b)
        G = sw * (P - Y) / n
        W -= lr * (X.T @ G + l2 * W)
        b -= lr * G.sum(axis=0)
    return W, b


def fit_temperature(Z, y):
    best, best_t = 1e9, 1.0
    for t in np.linspace(0.3, 3.0, 55):
        P = _softmax(Z / t)
        nll = -np.mean(np.log(P[np.arange(len(y)), y] + 1e-12))
        if nll < best:
            best, best_t = nll, float(t)
    return best_t


def main() -> None:
    from ..local_models import LocalLM, S1Router
    from .providers import GenerativeChooser
    s1 = S1Router()
    chooser = GenerativeChooser(LocalLM("qwen3.5-0.8b-q4"))
    rows = generate_examples()
    templates = sorted({r["template"] for r in rows})
    rng = random.Random(11)
    val_templates = {t for t in templates if rng.random() < 0.2}
    tr = [r for r in rows if r["template"] not in val_templates]
    va = [r for r in rows if r["template"] in val_templates]
    Xtr, ytr = featurize(tr, chooser, s1)
    Xva, yva = featurize(va, chooser, s1)
    mu, sd = Xtr.mean(axis=0), Xtr.std(axis=0) + 1e-6
    sweep = {}
    for l2 in (0.0003, 0.001, 0.003, 0.01, 0.03, 0.1):
        Wc, bc = train_lr((Xtr - mu) / sd, ytr, l2=l2)
        sweep[l2] = float(np.mean(np.argmax(((Xva - mu) / sd) @ Wc + bc, axis=1) == np.asarray(yva)))
    l2_best = max(sweep, key=lambda k: (sweep[k], k))
    W, b = train_lr((Xtr - mu) / sd, ytr, l2=l2_best)
    Zva = ((Xva - mu) / sd) @ W + b
    T = fit_temperature(Zva, yva)
    acc_tr = float(np.mean(np.argmax(((Xtr - mu) / sd) @ W + b, axis=1) == np.asarray(ytr)))
    acc_va = float(np.mean(np.argmax(Zva, axis=1) == np.asarray(yva)))
    DATA_PATH.write_text("".join(json.dumps({k: v for k, v in r.items() if k != "_obs"}, sort_keys=True) + "\n" for r in rows),
                         encoding="utf-8")
    head = {"name": "turnwise-dm", "version": "0.6.0", "ops": OPS, "signals": SIGNALS, "reads": READS,
            "features": "14 chooser log-scores | 18 s1 head outputs | 19 typed state features",
            "chooser": chooser.version, "s1": s1.version, "feature_dim": int(Xtr.shape[1]),
            "mean": mu.round(6).tolist(), "std": sd.round(6).tolist(), "W": W.round(6).tolist(), "b": b.round(6).tolist(),
            "temperature": round(T, 4),
            "training": {"examples": len(tr), "validation_examples": len(va), "templates": len(templates),
                         "validation_templates": sorted(val_templates), "train_accuracy": round(acc_tr, 4),
                         "validation_accuracy_template_heldout": round(acc_va, 4),
                         "l2_sweep_validation_accuracy": {str(k): round(v, 4) for k, v in sweep.items()}, "l2": l2_best,
                         "data_sha256": hashlib.sha256(DATA_PATH.read_bytes()).hexdigest(),
                         "supervision": "procedural oracle labels on synthetic templates executed through the v0.6 host"}}
    HEAD_PATH.write_text(json.dumps(head) + "\n", encoding="utf-8")
    print("l2 sweep (validation accuracy):", {k: round(v, 3) for k, v in sweep.items()}, "-> l2", l2_best)
    print(f"examples {len(rows)} (train {len(tr)}, template-held-out validation {len(va)}); "
          f"train acc {acc_tr:.3f}, validation acc {acc_va:.3f}, temperature {T:.2f}")


if __name__ == "__main__":
    main()
