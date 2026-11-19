"""B -- The same agent with Turnwise Core in control (LlamaIndex).

Same task, same ``build_agent(...)`` (system prompt, tools, LLM), same host.
What changes is who chooses the next operation: ``TurnwiseRuntime`` asks the
policy after every observation. The model is invoked as ONE bounded operation
through LlamaIndex structured prediction -- ``llm.structured_predict(StepOutcome,
...)`` on the agent's own LLM (``CALL_HEAVY``) or a separate light LLM
(``CALL_LIGHT``) -- so a tool request comes back as a typed
``StepOutcome(kind="tool_proposal")`` for the policy. No agent workflow runs
in that call, and no tool is executed on the model's say-so.

With the provider LLM (``OpenAIResponses``), ``structured_predict`` uses the
Responses API's constrained decoding (a JSON schema, ``tool_choice="none"``);
with the offline mock it uses LlamaIndex's function-calling program instead.
Both are LlamaIndex's own choice behind the same public call; the
``ProviderDouble`` tests cover the provider path.

``HANDOFF_AGENT`` (contrast only) runs the agent workflow itself for a bounded
number of iterations; for that segment the LLM controls the operations.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Mapping

from llama_index.core.agent.workflow import FunctionAgent
from llama_index.core.prompts import ChatPromptTemplate

from ..incident_env import HostSession, IncidentHost
from ..policies import TriagePolicy
from ..provider import ProviderLedger, classify_from_wire
from ..provider_double import PACKET_MARKER
from ..step_schema import StepOutcome
from ..trace import RunResult
from ..turnwise_core import STEP_CONTRACT, Budget, ModelCallFailed, Policy, TurnwiseRuntime
from .conventional import build_agent, run_agent


class LlamaIndexModelPort:
    """How Turnwise invokes the model through LlamaIndex: one structured call, no tools, no agent loop."""

    describe = ("LlamaIndex: llm.structured_predict(StepOutcome, ...) -- the agent's own LLM for heavy, "
                "a separate light LLM for light")

    def __init__(self, agent: FunctionAgent, host: IncidentHost, *, light_llm: Any, label: str,
                 ledger: ProviderLedger | None = None):
        self.agent, self.host, self.label, self.ledger = agent, host, label, ledger
        self.llms = {"heavy": agent.llm, "light": light_llm}
        # System prompt + user packet, like the agent's own messages. Each message is one template variable,
        # so the JSON braces inside them need no escaping.
        self.template = ChatPromptTemplate.from_messages([("system", "{system}"), ("user", "{packet}")])

    def call(self, tier: str, packet: Mapping[str, Any]) -> Mapping[str, Any]:
        sent_before = len(self.ledger.exchanges) if self.ledger else 0
        llm = self.llms[tier]
        try:
            outcome = llm.structured_predict(
                StepOutcome, self.template, llm_kwargs=step_llm_kwargs(llm) or None,
                system=f"{self.agent.system_prompt}\n\n{STEP_CONTRACT}",
                packet=f"{PACKET_MARKER}{json.dumps(packet, sort_keys=True)}")
        except Exception as exc:
            # LlamaIndex reports a refusal or an incomplete response as a generic ValueError ("Failed to produce
            # a structured response"); the wire record says which it was.
            wire = classify_from_wire(self.ledger, sent_before)
            if wire is not None:
                raise wire from exc
            if isinstance(exc, ValueError) and "structured response" in str(exc):
                raise ModelCallFailed("invalid structured output", str(exc)) from exc
            raise
        return outcome.model_dump()

    def handoff(self, task_text: str, max_turns: int) -> str:
        # The same agent definition, with its tools: the LLM controls this segment.
        native = build_agent(self.agent.llm, HostSession(self.host, actor="native_agent"))
        final, _, _ = asyncio.run(run_agent(native, task_text, max_turns))
        return final.response.content or ""


def step_llm_kwargs(llm: Any) -> dict[str, Any]:
    """The provider LLM's own generation bounds, passed explicitly to a Turnwise step.

    ``OpenAIResponses.structured_predict`` (llama-index-llms-openai 0.9.0) calls ``responses.parse`` with only
    the model, input, schema, ``tool_choice`` and ``store``: it drops the LLM's ``max_output_tokens``, reasoning
    options and sampling parameters, which its agent path does send. Without this, a step would run with no
    output-token bound and a different reasoning effort from the conventional agent on the same LLM. The keys
    mirror what the LLM sends on its agent path (sampling parameters only for non-reasoning models).
    """
    try:
        from llama_index.llms.openai import OpenAIResponses
        from llama_index.llms.openai.utils import O1_MODELS
    except ImportError:  # pragma: no cover - only the offline mock is in use
        return {}
    if not isinstance(llm, OpenAIResponses):
        return {}  # the offline MockFunctionCallingLLM: nothing to bound
    # Mirrors OpenAIResponses._get_model_kwargs (llama-index-llms-openai 0.9.0, responses.py:407-436).
    kwargs: dict[str, Any] = {}
    if llm.max_output_tokens is not None:
        kwargs["max_output_tokens"] = llm.max_output_tokens
    if llm.model in O1_MODELS and llm.reasoning_options is not None:
        kwargs["reasoning"] = llm.reasoning_options
    if llm.reasoning_options is None and llm.model not in O1_MODELS:
        kwargs.update(temperature=llm.temperature, top_p=llm.top_p)
    return kwargs


def run_turnwise(task: str, heavy_llm: Any, light_llm: Any, *, model_label: str,
                 policy: Policy | None = None, budget: Budget = Budget(), host: IncidentHost | None = None,
                 ledger: ProviderLedger | None = None) -> tuple[RunResult, TurnwiseRuntime]:
    host = host or IncidentHost(task)
    agent = build_agent(heavy_llm, HostSession(host, actor="llm"))  # the very same agent definition
    port = LlamaIndexModelPort(agent, host, light_llm=light_llm, label=model_label, ledger=ledger)
    policy = policy or TriagePolicy()
    runtime = TurnwiseRuntime(host, policy, port, budget=budget, framework="LlamaIndex")
    return runtime.run(), runtime
