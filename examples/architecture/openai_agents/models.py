"""Which model the OpenAI Agents SDK examples use: simulated (default) or a bounded provider (explicit).

Simulated: the SDK's own offline test double, ``agents.testing.ScriptedModel``,
whose every step is ``ModelStep.respond(...)``: the reply is derived from the
exact call the SDK makes (instructions, conversation items, tool schemas,
output schema). The Runner, tool dispatch and structured-output parsing are
the real SDK; only the generated text is simulated (see simulated_model.py).

Provider: ``OpenAIResponsesModel`` -- the class the SDK's default provider uses
for OpenAI models -- over an ``openai.AsyncOpenAI`` client whose every HTTP
request goes through a ``ProviderLedger`` (request cap, spend cap, record of
what was sent and received; see provider.py). Retries are off at both layers
(``max_retries=0`` on the client, ``ModelRetrySettings(max_retries=0)`` in the
SDK) and the timeout and output-token limit are explicit. Its transport is the
real provider (paid; only via ``live_smoke --provider openai`` with an explicit
spend authorisation) or the local ``ProviderDouble`` (simulated, offline).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call

from ..provider import ProviderSetup
from ..simulated_model import SIMULATED_LABEL, SimulatedInvestigator


@dataclass
class ModelChoice:
    heavy: Any  # an agents Model instance
    light: Any
    label: str
    simulated: bool  # True unless real provider inference is performed
    settings: Any = None  # agents.ModelSettings applied to the agent (provider mode), else None


def choose_models(*, brain: SimulatedInvestigator | None = None, max_calls: int = 12,
                  provider: ProviderSetup | None = None) -> ModelChoice:
    if provider is not None:
        model, settings = provider_model(provider)
        # One explicitly selected model: CALL_LIGHT uses the same model and settings as CALL_HEAVY.
        return ModelChoice(model, model, provider.label + "; via agents OpenAIResponsesModel", provider.simulated,
                           settings)
    brain = brain or SimulatedInvestigator()
    return ModelChoice(simulated_model(brain, "heavy", max_calls), simulated_model(brain, "light", max_calls),
                       f"{SIMULATED_LABEL}; plugged in via agents.testing.ScriptedModel", True)


def provider_model(setup: ProviderSetup) -> tuple[Any, Any]:
    """An ``OpenAIResponsesModel`` and the ``ModelSettings`` that bound it. Building it sends nothing."""
    from openai import AsyncOpenAI
    from openai.types.shared import Reasoning

    from agents import ModelSettings, OpenAIResponsesModel
    from agents.retry import ModelRetrySettings

    s = setup.settings
    _, async_http = setup.ledger.clients(setup.transport, timeout_s=s.timeout_s)
    client = AsyncOpenAI(api_key=setup.api_key(), base_url=setup.base_url, max_retries=0, timeout=s.timeout_s,
                         http_client=async_http)
    settings = ModelSettings(
        max_tokens=s.max_output_tokens, temperature=s.temperature,
        reasoning=Reasoning(effort=s.reasoning_effort) if s.reasoning_effort else None,
        retry=ModelRetrySettings(max_retries=0))  # also disables the openai client's own retries in the SDK
    return OpenAIResponsesModel(s.model, client), settings


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
