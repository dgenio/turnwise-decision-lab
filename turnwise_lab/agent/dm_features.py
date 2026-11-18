"""Feature vector for turnwise-dm (shared by training and inference).

[ 14 generative-chooser log-scores | 18 s1 head outputs | 19 typed state features ]

* chooser log-scores: one cached forward pass of the local instruct model
  (text understanding of the request and of the rendered observations);
* s1 outputs: category (9), difficulty (5), flags (4) from the fixed-head classifier;
* typed state: which reads already succeeded, observation signals, step count
  (computed by the host from trusted tool output, never from model text).
"""
from __future__ import annotations

import numpy as np

from .dm_train import state_context, typed_features
from .providers import OPS


def feature_vector(state, chooser, s1) -> tuple[np.ndarray, dict]:
    sc = chooser.scores(state)
    lp = np.clip(np.asarray([sc["logprobs"][op] for op in OPS], dtype=np.float64), -20.0, 0.0)
    r = s1.classify(state.user_message, state_context(state))
    s1v = (list(r["category_probabilities"].values()) + list(r["difficulty_probabilities"].values()) + list(r["flags"].values()))
    x = np.concatenate([lp, np.asarray(s1v, dtype=np.float64), np.asarray(typed_features(state), dtype=np.float64)])
    return x, {"chooser_ms": sc["latency_ms"], "chooser_tokens": sc["input_tokens"], "s1_ms": r["latency_ms"],
               "s1_tokens": r["input_tokens"], "chooser_mass": sc["mass"], "s1_difficulty": r["difficulty_expected"]}
