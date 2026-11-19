"""Which model the OpenAI Agents SDK examples use: simulated (default) or live (explicit opt-in).

Simulated: the SDK's own offline test double, ``agents.testing.ScriptedModel``,
whose every step is ``ModelStep.respond(...)``: the reply is derived from the
exact call the SDK makes (instructions, conversation items, tool schemas,
output schema). The Runner, tool dispatch and structured-output parsing are
the real SDK; only the generated text is simulated (see simulated_model.py).

Live: a model name resolved by the SDK's default OpenAI provider. This needs
OPENAI_API_KEY, costs money, and is never used unless ``live=True``. It has never
been run or tested by the authors or this repository's CI.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call

from ..simulated_model import SIMULATED_LABEL, SimulatedInvestigator


@dataclass
class ModelChoice:
    heavy: Any  # an agents Model instance, or a model name string (live)
    light: Any
    label: str
    simulated: bool


def choose_models(*, live: bool = False, brain: SimulatedInvestigator | None = None,
                  max_calls: int = 12) -> ModelChoice:
    if live:
        if not os.environ.get("OPENAI_API_KEY"):
            raise SystemExit("--live needs OPENAI_API_KEY; refusing to fall back silently.")
        heavy = os.environ.get("TURNWISE_HEAVY_MODEL", "gpt-4.1")
        light = os.environ.get("TURNWISE_LIGHT_MODEL", "gpt-4.1-mini")
        return ModelChoice(heavy, light, f"LIVE OpenAI models heavy={heavy} light={light} "
                                         "via the SDK default provider (never run or tested by the authors or CI)", False)
    brain = brain or SimulatedInvestigator()
    return ModelChoice(simulated_model(brain, "heavy", max_calls), simulated_model(brain, "light", max_calls),
                       f"{SIMULATED_LABEL}; plugged in via agents.testing.ScriptedModel", True)


def simulated_model(brain: SimulatedInvestigator, tier: str, max_calls: int) -> ScriptedModel:
    counter = {"n": 0}

    def respond(call):  # agents.testing.ModelCall -> output items
        counter["n"] += 1
        items = call.input if isinstance(call.input, list) else [{"role": "user", "content": call.input}]
        if call.output_schema is not None:  # a Turnwise step: answer with one typed StepOutcome
            packet = json.loads(_text(_first_user(items)))
            return [assistant_message(json.dumps(brain.typed_step(packet)), item_id=f"msg_{tier}_{counter['n']}")]
        task, prior = _task_and_prior_receipts(_text(_first_user(items)))
        results = prior + [i["output"] for i in items if isinstance(i, dict) and i.get("type") == "function_call_output"]
        action = brain.native_step(instructions=call.system_instructions or "", task=task, tool_results=results,
                                   tools=[t.name for t in call.tools])
        if action.kind == "tool_call":
            return [function_call(action.tool, action.arguments, call_id=f"call_{tier}_{counter['n']}")]
        return [assistant_message(action.text, item_id=f"msg_{tier}_{counter['n']}")]

    return ScriptedModel([ModelStep.respond(respond) for _ in range(max_calls)])


def _first_user(items: list[Any]) -> Any:
    return next(i for i in items if isinstance(i, dict) and i.get("role") == "user")


def _text(item: Any) -> str:
    content = item.get("content", "")
    if isinstance(content, str):
        return content
    return "".join(part.get("text", "") for part in content if isinstance(part, dict))


def _task_and_prior_receipts(text: str) -> tuple[str, list[str]]:
    """A handoff message is the task, then one JSON host receipt per line (see turnwise.handoff_message)."""
    first, *rest = text.split("\n")
    return first, [line for line in rest if line.startswith("{")]
