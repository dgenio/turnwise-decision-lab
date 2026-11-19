"""Opt-in hosted decision providers (never used by default, never used in CI).

* ``OpenAIDecisionsProvider``: POST /v1/decisions (model gpt-6-luna). Observations
  are passed natively as function_call / function_call_output input items; the
  next operation is a ``choice`` question, context blocks are ``predicate``
  questions in the same request (they depend only on shared input).
  Pricing used for the spend cap: USD 0.10 per 1M uncached input tokens, output
  not charged (OpenAI Decisions guide, checked 2026-11-18).
* ``SystemOneProvider``: TypeSafe / decisionmodels.io System One style requests
  (``state`` + typed ``questions``: choice / score / noul), e.g. Jev.

Nothing is sent unless ``allow_remote=True``, an API key is present and a
spending cap is declared. The cap is enforced *before* each request from a
conservative token estimate, and actual usage is recorded from the response.
Only public synthetic data may be sent; the same obvious-secret preflight as the
v0.4 provider adapter runs on every request.

STATUS: exercised against local fake HTTP servers only. Not run against a live
provider in this repository (no credentials, no approved spend).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from threading import Lock
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request as HTTPRequest, urlopen
import json
import os
import time

from ..core import _OBVIOUS_PRIVATE
from .contracts import SCORE_PROVIDER, Decision, Question
from .host import CATALOG_BY_ID
from .providers import DESCR, OPS, ArgumentBuilder, _finalize_op

OPENAI_PRICE_PER_INPUT_TOKEN = 0.10 / 1_000_000


def _endpoint_ok(url: str) -> bool:
    p = urlparse(url)
    if p.username or p.password or p.query or p.fragment:
        return False
    return (p.scheme == "https" and p.hostname not in (None, "localhost", "127.0.0.1")) or \
           (p.scheme == "http" and p.hostname in ("localhost", "127.0.0.1"))


@dataclass
class Spend:
    """Thread-safe per-process budget ledger, not a provider-enforced billing limit.

    A reservation is held until trustworthy metering arrives. Failed/uncertain
    requests and providers without usage reporting keep their liability reserved:
    a timeout does not prove a request was free. This intentionally fails closed.
    """
    cap_usd: float
    spent_usd: float = 0.0  # reported, metered cost only
    requests: int = 0       # attempted requests, including transport failures
    usage: list = field(default_factory=list)
    reserved_usd: float = 0.0  # in-flight or unknown-cost liability
    _lock: Any = field(default_factory=Lock, repr=False, compare=False)
    _pending: dict[int, float] = field(default_factory=dict, repr=False, compare=False)
    _uncertain: set[int] = field(default_factory=set, repr=False, compare=False)
    _next_id: int = field(default=0, repr=False, compare=False)

    def reserve(self, est_usd: float) -> int:
        if not isfinite(est_usd) or est_usd <= 0:
            raise ValueError("reservation estimate must be positive and finite")
        with self._lock:
            if self.spent_usd + self.reserved_usd + est_usd > self.cap_usd:
                raise PermissionError(f"spending cap {self.cap_usd} USD would be exceeded; no request sent")
            ticket = self._next_id
            self._next_id += 1
            self._pending[ticket] = est_usd
            self.reserved_usd += est_usd
            self.requests += 1
            return ticket

    def reconcile(self, ticket: int, actual_usd: float, usage: dict) -> None:
        """Replace a reservation with reported cost, even if larger than estimate.

        A provider charging more than estimated may breach the cap; subsequent
        reservations are blocked, but the charge cannot be undone by this client.
        """
        if not isfinite(actual_usd) or actual_usd < 0:
            raise ValueError("reported cost must be nonnegative and finite")
        with self._lock:
            estimated = self._pending.pop(ticket)
            self._uncertain.discard(ticket)
            self.reserved_usd -= estimated
            self.spent_usd += actual_usd
            self.usage.append({"status": "metered", "reported_usage": dict(usage), "usd": actual_usd})

    def mark_unknown(self, ticket: int, reason: str) -> None:
        """Retain the reservation for possible charges; never refund on timeout."""
        with self._lock:
            if ticket not in self._pending:
                raise ValueError("cannot mark a settled reservation as unknown")
            if ticket not in self._uncertain:
                self._uncertain.add(ticket)
                self.usage.append({"status": "unknown", "reason": reason,
                                   "reserved_usd": self._pending[ticket]})


class _Remote:
    def __init__(self, *, endpoint: str, api_key_env: str, allow_remote: bool, spend_cap_usd: float | None, timeout_s: int = 20):
        if not allow_remote:
            raise PermissionError("allow_remote=True is required; nothing is sent by default")
        if spend_cap_usd is None or not isfinite(spend_cap_usd) or spend_cap_usd <= 0:
            raise PermissionError("a positive finite spending cap (USD) must be declared")
        if not _endpoint_ok(endpoint):
            raise ValueError("HTTPS endpoint (or loopback for tests) required")
        key = os.getenv(api_key_env)
        if not key:
            raise PermissionError(f"missing {api_key_env}; nothing sent")
        self.endpoint, self.key, self.timeout = endpoint, key, timeout_s
        self.spend = Spend(spend_cap_usd)

    def _post(self, body: dict) -> tuple[dict, float]:
        blob = json.dumps(body)
        if _OBVIOUS_PRIVATE.search(blob):
            raise PermissionError("possible private content detected; nothing sent")
        req = HTTPRequest(self.endpoint, data=blob.encode("utf-8"), method="POST",
                          headers={"Authorization": "Bearer " + self.key, "Content-Type": "application/json"})
        t0 = time.perf_counter()
        with urlopen(req, timeout=self.timeout) as r:
            payload = json.loads(r.read(2_000_001))
        return payload, round((time.perf_counter() - t0) * 1000, 1)

    def _budgeted_post(self, body: dict, estimated_usd: float) -> tuple[int, dict, float]:
        # Reservation occurs immediately before the network call, atomically
        # across callers sharing this provider instance. No automatic retries.
        ticket = self.spend.reserve(estimated_usd)
        try:
            payload, ms = self._post(body)
        except Exception:
            self.spend.mark_unknown(ticket, "transport_or_protocol_failure")
            raise
        return ticket, payload, ms


class OpenAIDecisionsProvider(_Remote):
    name = "openai-decisions"

    def __init__(self, *, model: str = "gpt-6-luna", endpoint: str = "https://api.openai.com/v1/decisions",
                 api_key_env: str = "OPENAI_API_KEY", allow_remote: bool = False, spend_cap_usd: float | None = None,
                 args_builder: ArgumentBuilder | None = None):
        super().__init__(endpoint=endpoint, api_key_env=api_key_env, allow_remote=allow_remote, spend_cap_usd=spend_cap_usd)
        self.model = model
        self.args = args_builder or ArgumentBuilder()

    @staticmethod
    def build_input(state) -> list[dict]:
        items = [{"role": "developer", "content": "You are the control layer of an incident assistant. Choose the next operation; "
                                                 "gather evidence before explaining causes; never repeat a successful call."}]
        for m in state.conversation:
            items.append({"role": m["role"], "content": m["content"]})
        items.append({"role": "user", "content": state.user_message})
        for o in state.observations:
            if o.target in CATALOG_BY_ID:
                items.append({"type": "function_call", "call_id": o.call_id[-64:], "name": o.target, "arguments": json.dumps(o.arguments)})
                items.append({"type": "function_call_output", "call_id": o.call_id[-64:],
                              "output": json.dumps(o.facts) if o.status == "ok" else f"{o.status}: {o.reason}"})
        return items

    def build_request(self, state) -> dict:
        choices = [{"value": op, "description": CATALOG_BY_ID[op].description if op in CATALOG_BY_ID else DESCR[op]} for op in OPS]
        return {"model": self.model, "input": self.build_input(state),
                "questions": [{"type": "choice", "name": "next_operation",
                               "instructions": "Which operation should run next for this user request?", "choices": choices}]}

    def decide(self, state, host) -> Decision:
        body = self.build_request(state)
        # Bytes are a deliberately cautious estimate of BPE input tokens, with
        # headroom for server-side framing. Still NOT a hard bound on billing.
        est_tokens = len(json.dumps(body).encode("utf-8")) + 512
        ticket, payload, ms = self._budgeted_post(body, est_tokens * OPENAI_PRICE_PER_INPUT_TOKEN)
        usage = payload.get("usage") if isinstance(payload, dict) else None
        input_tokens = usage.get("input_tokens") if isinstance(usage, dict) else None
        if isinstance(input_tokens, bool) or not isinstance(input_tokens, int) or input_tokens < 0:
            self.spend.mark_unknown(ticket, "missing_or_invalid_usage")
            raise ValueError("decision provider did not report valid input-token usage")
        cost = input_tokens * OPENAI_PRICE_PER_INPUT_TOKEN
        self.spend.reconcile(ticket, cost, usage)
        ans = next(a for a in payload["answers"] if a.get("name") == "next_operation")
        if ans.get("type") == "refusal":
            return Decision("abstain", provider=self.name, model=self.model, rationale="provider refusal",
                            questions=[Question("next_operation", OPS, None, None, SCORE_PROVIDER, ms, usage.get("input_tokens"))])
        probs = {p["value"]: p["probability"] for p in ans.get("probabilities", [])}
        q = Question("next_operation", OPS, ans["choice"], probs, SCORE_PROVIDER, ms, usage.get("input_tokens"),
                     note=f"provider confidence {ans.get('confidence')}; cost {cost:.8f} USD at the documented rate")
        return _finalize_op(ans["choice"], state, self.name, self.model, [q], self.args)


class SystemOneProvider(_Remote):
    """TypeSafe / decisionmodels.io System One request shape (state + typed questions)."""
    name = "system-one"

    def __init__(self, *, model: str, endpoint: str, api_key_env: str, allow_remote: bool = False,
                 spend_cap_usd: float | None = None, price_per_input_token: float | None = None,
                 args_builder: ArgumentBuilder | None = None):
        super().__init__(endpoint=endpoint, api_key_env=api_key_env, allow_remote=allow_remote, spend_cap_usd=spend_cap_usd)
        if price_per_input_token is None or not isfinite(price_per_input_token) or price_per_input_token <= 0:
            raise PermissionError("declare a positive finite input-token price for the budget preflight")
        self.model, self.price = model, price_per_input_token
        self.args = args_builder or ArgumentBuilder()

    def build_request(self, state) -> dict:
        obs = [o.summary(300) for o in state.observations]
        return {"model": self.model,
                "state": {"request": state.user_message, "earlier_messages": [m["content"][:300] for m in state.conversation],
                          "observations": obs or ["none yet"]},
                "questions": {"next_operation": {"type": "choice",
                                                 "instructions": "Choose the next operation for this incident-assistant turn.",
                                                 "criteria": {op: (CATALOG_BY_ID[op].description if op in CATALOG_BY_ID else DESCR[op]) for op in OPS}}}}

    def decide(self, state, host) -> Decision:
        body = self.build_request(state)
        est = len(json.dumps(body).encode("utf-8")) + 512
        ticket, payload, ms = self._budgeted_post(body, est * self.price)
        # This provider adapter has no verified usage field. The estimated
        # liability stays reserved rather than being mislabeled actual spend.
        self.spend.mark_unknown(ticket, "provider_does_not_report_usage")
        ans = payload["choices"]["next_operation"]
        q = Question("next_operation", OPS, ans["choice"], ans.get("probabilities"), SCORE_PROVIDER, ms, None,
                     note="cost estimated from request size at the declared price (provider usage not reported)")
        return _finalize_op(ans["choice"], state, self.name, self.model, [q], self.args)
