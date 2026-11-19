"""Which LLM the LlamaIndex examples use: simulated (default) or live (explicit opt-in).

Simulated: LlamaIndex's own offline test double,
``llama_index.core.llms.mock.MockFunctionCallingLLM``, with a
``response_generator`` that derives each reply from the exact messages and
tools LlamaIndex sends. The agent workflow, tool dispatch and structured
prediction are the real framework; only the generated text is simulated
(see simulated_model.py).

Live: ``llama_index.llms.openai.OpenAI`` (separate package
``llama-index-llms-openai``) with OPENAI_API_KEY. Never used unless
``live=True``; never run or tested by the authors or this repository's CI.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from llama_index.core.base.llms.types import ToolCallBlock
from llama_index.core.llms import ChatMessage, MessageRole
from llama_index.core.llms.mock import MockFunctionCallingLLM

from ..simulated_model import SIMULATED_LABEL, SimulatedInvestigator

PACKET_MARKER = "TURNWISE STEP PACKET:"


@dataclass
class LLMChoice:
    heavy: Any
    light: Any
    label: str
    simulated: bool


def choose_llms(*, live: bool = False, brain: SimulatedInvestigator | None = None) -> LLMChoice:
    if live:
        if not os.environ.get("OPENAI_API_KEY"):
            raise SystemExit("--live needs OPENAI_API_KEY; refusing to fall back silently.")
        try:
            from llama_index.llms.openai import OpenAI
        except ImportError as exc:  # pragma: no cover - optional package
            raise SystemExit("--live with LlamaIndex needs: pip install llama-index-llms-openai") from exc
        heavy = os.environ.get("TURNWISE_HEAVY_MODEL", "gpt-4.1")
        light = os.environ.get("TURNWISE_LIGHT_MODEL", "gpt-4.1-mini")
        return LLMChoice(OpenAI(model=heavy), OpenAI(model=light),
                         f"LIVE OpenAI models heavy={heavy} light={light} via llama-index-llms-openai "
                         "(never run or tested by the authors or CI)", False)
    brain = brain or SimulatedInvestigator()
    return LLMChoice(simulated_llm(brain, "heavy"), simulated_llm(brain, "light"),
                     f"{SIMULATED_LABEL}; plugged in via llama_index MockFunctionCallingLLM", True)


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
