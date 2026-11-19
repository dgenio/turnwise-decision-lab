"""Which LLM the LlamaIndex examples use: simulated (default) or a bounded provider (explicit).

Simulated: LlamaIndex's own offline test double,
``llama_index.core.llms.mock.MockFunctionCallingLLM``, with a
``response_generator`` that derives each reply from the exact messages and
tools LlamaIndex sends. The agent workflow, tool dispatch and structured
prediction are the real framework; only the generated text is simulated
(see simulated_model.py). Note that the mock is a *function-calling* LLM, so
``structured_predict`` takes LlamaIndex's function-calling program with it.

Provider: ``llama_index.llms.openai.OpenAIResponses`` (package
``llama-index-llms-openai``), the LlamaIndex class for the OpenAI **Responses
API** -- the same API the Agents SDK uses. Current OpenAI models document that
tool calling requires the Responses API, so the Chat Completions class
(``llama_index.llms.openai.OpenAI``) is not used. Its ``structured_predict``
uses the API's constrained decoding (``responses.parse`` with
``tool_choice="none"``), not the mock's function-calling path: only the
``ProviderDouble`` tests exercise it offline. Every HTTP request goes through a
``ProviderLedger``; retries are 0 and the timeout and output-token limit are
explicit (see provider.py).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from llama_index.core.base.llms.types import ToolCallBlock
from llama_index.core.llms import ChatMessage, MessageRole
from llama_index.core.llms.mock import MockFunctionCallingLLM

from ..provider import ProviderSetup
from ..provider_double import PACKET_MARKER
from ..simulated_model import SIMULATED_LABEL, SimulatedInvestigator


@dataclass
class LLMChoice:
    heavy: Any
    light: Any
    label: str
    simulated: bool  # True unless real provider inference is performed


def choose_llms(*, brain: SimulatedInvestigator | None = None, provider: ProviderSetup | None = None) -> LLMChoice:
    if provider is not None:
        llm = provider_llm(provider)
        # One explicitly selected model: CALL_LIGHT uses the same LLM as CALL_HEAVY.
        return LLMChoice(llm, llm, provider.label + "; via llama_index OpenAIResponses", provider.simulated)
    brain = brain or SimulatedInvestigator()
    return LLMChoice(simulated_llm(brain, "heavy"), simulated_llm(brain, "light"),
                     f"{SIMULATED_LABEL}; plugged in via llama_index MockFunctionCallingLLM", True)


def provider_llm(setup: ProviderSetup) -> Any:
    """An ``OpenAIResponses`` LLM bounded by ``setup``. Building it sends nothing; an unknown model id fails here."""
    try:
        from llama_index.llms.openai import OpenAIResponses
    except ImportError as exc:  # pragma: no cover - pinned in requirements.txt
        raise SystemExit("LlamaIndex provider runs need: pip install -r examples/architecture/requirements.txt") from exc
    s = setup.settings
    sync_http, async_http = setup.ledger.clients(setup.transport, timeout_s=s.timeout_s)
    kwargs: dict[str, Any] = dict(model=s.model, api_key=setup.api_key(), max_retries=0, timeout=s.timeout_s,
                                  max_output_tokens=s.max_output_tokens, http_client=sync_http,
                                  async_http_client=async_http)
    if setup.base_url:
        kwargs["api_base"] = setup.base_url
    if s.temperature is not None:
        kwargs["temperature"] = s.temperature
    if s.reasoning_effort:
        kwargs["reasoning_options"] = {"effort": s.reasoning_effort}
    llm = OpenAIResponses(**kwargs)
    try:
        llm.metadata  # llama-index-llms-openai validates the model id against its own table here
    except ValueError as exc:
        raise SystemExit(f"llama-index-llms-openai does not support model {s.model!r}: {exc}") from exc
    return llm


def simulated_llm(brain: SimulatedInvestigator, tier: str) -> MockFunctionCallingLLM:
    counter = {"n": 0}

    def generate(messages: list[ChatMessage], **kwargs: Any) -> ChatMessage:
        counter["n"] += 1
        tools = kwargs.get("tools") or []
        names = [t.metadata.name for t in tools]
        if names == ["StepOutcome"]:  # a Turnwise step via structured prediction
            prompt = next(m.content for m in reversed(messages) if m.role == MessageRole.USER) or ""
            packet = json.loads(prompt.split(PACKET_MARKER, 1)[1])
            return ChatMessage(role=MessageRole.ASSISTANT, blocks=[ToolCallBlock(
                tool_call_id=f"call_{tier}_{counter['n']}", tool_name="StepOutcome",
                tool_kwargs=brain.typed_step(packet))])
        system = next((m.content or "" for m in messages if m.role == MessageRole.SYSTEM), "")
        user = next(m.content or "" for m in messages if m.role == MessageRole.USER)
        task, *rest = user.split("\n")
        results = [line for line in rest if line.startswith("{")]
        results += [m.content or "" for m in messages if m.role == MessageRole.TOOL]
        action = brain.native_step(instructions=system, task=task, tool_results=results, tools=names)
        if action.kind == "tool_call":
            return ChatMessage(role=MessageRole.ASSISTANT, blocks=[ToolCallBlock(
                tool_call_id=f"call_{tier}_{counter['n']}", tool_name=action.tool, tool_kwargs=action.arguments)])
        return ChatMessage(role=MessageRole.ASSISTANT, content=action.text)

    return MockFunctionCallingLLM(response_generator=generate, is_chat_model=True)
