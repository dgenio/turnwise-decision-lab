"""Opt-in v0.8 entrypoints. All v0.7 locked traces and source remain untouched.

Local runner is a small composition around existing agents, NOT a new agent
framework. Hosted runner needs a caller-created, explicitly approved HostedChat
and inherits its API-key, spend-cap and allow_remote guardrails.
"""
from __future__ import annotations

from ..agent.heavy_agent import run_heavy_agent
from ..v07.controllers import run_contract_turn
from ..v07.evidence import type_claim
from ..v07.hosted import run_hosted_agent
from .guard import IntentBoundHost, NoSyntheticHoldGate, user_history


def run_local_turn(message: str, *, world, generator, heavy_lm, turn_id: str,
                   conversation: list[dict] | None = None, arm: str = "v08-local") -> dict:
    """Use frozen v0.7 contract planner only for non-action requests.

    Potential actions, unresolved references and untyped requests go to the
    existing tool-capable heavy agent. No text-only fallback or synthesized
    approval. History remains visible to the native agent for reasoning, while
    all deterministic referent decisions use only user-owned turns.
    """
    history = list(conversation or [])
    host = IntentBoundHost(world)
    host.bind_request(message, history)
    gate = NoSyntheticHoldGate()
    claim = type_claim(message, user_history(history))
    if claim.type in ("action", "ambiguous", "untyped") or claim.declined_action:
        return run_heavy_agent(message, host=host, lm=heavy_lm, turn_id=turn_id,
                               conversation=history, gate=gate, arm=arm).as_json()
    return run_contract_turn(message, host=host, generator=generator, heavy_lm=heavy_lm,
                             turn_id=turn_id, conversation=user_history(history),
                             gate=gate, arm=arm)


def run_hosted_turn(message: str, *, world, chat, turn_id: str,
                    conversation: list[dict] | None = None, arm: str = "v08-hosted") -> dict:
    """Native hosted tool-calling agent + independent write guard.

    This function cannot enable remote access or set spend limits. The caller
    must construct a HostedChat with the existing explicit opt-in and cap.
    """
    history = list(conversation or [])
    host = IntentBoundHost(world)
    host.bind_request(message, history)
    return run_hosted_agent(message, host=host, chat=chat, turn_id=turn_id,
                            conversation=history, gate=NoSyntheticHoldGate(), arm=arm)
