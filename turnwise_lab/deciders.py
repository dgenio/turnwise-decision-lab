"""A deterministic fixture adapter and an optional real Jev adapter."""
from __future__ import annotations
from .core import Judgment

class FixtureDecider:
    """For testing contract mechanics ONLY. It is NOT trained/inference/calibrated."""
    external = False

    def __init__(self, decisions: dict[str, dict]):
        self.decisions = decisions

    def decide(self, state: dict) -> Judgment:
        key = state["new_turn"]
        if key not in self.decisions:
            raise LookupError("no fixture classifier output")
        return Judgment(**self.decisions[key])


class JevDecider:
    """Optional real provider. Requires typesafe-sdk and explicit public-data opt-in.

    Uses two Choice questions in the same request; the provider scores reflect
    model output and MUST be calibrated/validated on held-out domain labels.
    """
    external = True

    def decide(self, state: dict) -> Judgment:
        from typesafe_sdk import Choice, TypeSafeClient  # optional dependency
        with TypeSafeClient() as client:
            response = client.system_one(
                state=state,
                questions={
                    "path": Choice(
                        instructions="Classify the cheapest viable next step given the new user turn and the listed capabilities; do not authorize side effects.",
                        criteria={
                            "direct": "No LLM or tools needed; host can answer from an existing deterministic template or exact known fact.",
                            "flow": "A listed, preapproved deterministic multi-step flow is sufficient.",
                            "tool": "Read or query an available tool before generating the response.",
                            "llm": "Open-ended synthesis, explanation, planning or reasoning required.",
                        },
                    ),
                    "tier": Choice(
                        instructions="For tasks that require text generation, select the lowest capable reasoning tier; wrong answers and retries cost more than a smarter model.",
                        criteria={
                            "small": "Simple and low-risk writing or extraction.",
                            "standard": "Moderate synthesis and normal tool interpretation.",
                            "deep": "Complex reasoning, ambiguous or consequential task.",
                        },
                    ),
                    "context": Choice(
                        instructions="How much additional retrieved context is needed? The host independently enforces relevance, permissions and token budget.",
                        criteria={
                            "none": "Current request and trusted task summary suffice.",
                            "related": "A few directly relevant source excerpts are useful.",
                            "extended": "More than one relevant context source is likely needed.",
                        },
                    ),
                },
            )
        a, b, c = (response.choices[k] for k in ("path", "tier", "context"))
        return Judgment(route=a.choice, route_probability=float(a.probabilities[a.choice]),
                        tier=b.choice, tier_probability=float(b.probabilities[b.choice]),
                        context_mode=c.choice)
