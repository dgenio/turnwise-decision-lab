"""Dependency-free, genuinely fitted (not fixture-fed) synthetic route baseline.

A tiny multinomial Naive Bayes text classifier. Probabilities are uncalibrated;
this is not a decision model or a comparison to Jev / vLLM / LiteLLM.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import math

from .core import terms


@dataclass(frozen=True)
class Prediction:
    route: str
    score: float
    probabilities: dict[str, float]


class TinyMultinomialNB:
    def __init__(self, *, alpha: float = 1.0):
        if alpha <= 0:
            raise ValueError("alpha must be positive")
        self.alpha = alpha
        self.class_counts: Counter = Counter()
        self.token_counts: dict[str, Counter] = defaultdict(Counter)
        self.vocab: set[str] = set()
        self.fitted = False

    def fit(self, rows: list[dict]) -> "TinyMultinomialNB":
        if not rows:
            raise ValueError("Cannot fit without training rows")
        self.class_counts.clear()
        self.token_counts.clear()
        self.vocab.clear()
        for row in rows:
            label = row["label"]
            self.class_counts[label] += 1
            tokens = terms(row["text"] + " " + row.get("task_summary", ""))
            self.token_counts[label].update(tokens)
            self.vocab.update(tokens)
        self.fitted = True
        return self

    def predict(self, text: str) -> Prediction:
        if not self.fitted:
            raise RuntimeError("Call fit() first")
        tokens = terms(text)
        n = sum(self.class_counts.values())
        classes = sorted(self.class_counts)
        scores: dict[str, float] = {}
        for label in classes:
            token_count = sum(self.token_counts[label].values())
            denom = token_count + self.alpha * max(len(self.vocab), 1)
            logp = math.log(self.class_counts[label] / n)
            for token in sorted(tokens):
                if token not in self.vocab:
                    continue
                logp += math.log((self.token_counts[label][token] + self.alpha) / denom)
            scores[label] = logp
        maximum = max(scores.values())
        normalizer = sum(math.exp(v - maximum) for v in scores.values())
        probs = {label: math.exp(value - maximum) / normalizer for label, value in scores.items()}
        route = max(classes, key=lambda label: (probs[label], label))
        return Prediction(route, probs[route], probs)
