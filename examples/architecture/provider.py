"""Bounded, recorded access to a model provider for the architecture examples.

Every HTTP request that either framework sends to the provider passes through
one ``ProviderLedger``, via ``httpx2`` event hooks on the clients handed to the
framework (the ``openai`` client, which both frameworks use, is built on ``httpx2``):

* **Caps before sending.** The request hook refuses a request *before* it leaves
  the process once the request cap is reached, or once the next request could
  push the estimated spend over the authorised amount. A refusal raises
  ``ProviderCapReached``, a ``RunHalt``: the Turnwise runtime stops at once
  instead of treating it as one more observation.
* **No hidden retries.** The clients are built with ``max_retries=0``; the
  ledger counts every HTTP attempt anyway, so a retry would show up.
* **A record of what was actually sent and returned**: endpoint, model, offered
  tools, structured-output format, sampling parameters, output items (function
  calls, text, refusals) and token usage. Reports are built from this record,
  not from what the framework or the model claims.

The *transport* decides where requests go: ``None`` is the real provider over
the network (paid inference); a ``ProviderDouble`` transport answers locally
(``provider_double.py``) and is labelled as simulated everywhere.

Imports ``httpx2`` (installed with ``openai``); nothing here calls the network
by itself.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import httpx2

from .turnwise_core import ModelCallFailed, RunHalt

REAL_SOURCE = "REAL provider inference (OpenAI Responses API)"
DOUBLE_SOURCE = "PROVIDER DOUBLE (simulated responses; no inference performed)"
DOUBLE_BASE_URL = "https://provider-double.invalid/v1"  # .invalid never resolves, even if the double were bypassed
DOUBLE_API_KEY = "provider-double-not-a-credential"
# Only for the *worst-case estimate* of one request; the ledger also checks actual usage as it arrives.
ASSUMED_MAX_INPUT_TOKENS = 8000


class ProviderCapReached(RunHalt):
    """A request was refused before sending: request cap or spend authorisation reached."""


@dataclass(frozen=True)
class Prices:
    """USD per million tokens, as supplied by the operator (verify against the provider's price page)."""

    input_per_mtok: float
    output_per_mtok: float

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens * self.input_per_mtok + output_tokens * self.output_per_mtok) / 1_000_000

    def worst_request(self, max_output_tokens: int) -> float:
        return self.cost(ASSUMED_MAX_INPUT_TOKENS, max_output_tokens)


@dataclass(frozen=True)
class ProviderSettings:
    """Model-level settings applied identically through both frameworks. Retries are always 0."""

    model: str
    timeout_s: float = 60.0
    max_output_tokens: int = 2000  # includes reasoning tokens on reasoning models
    temperature: float | None = None  # None: not set explicitly (framework/provider default applies)
    reasoning_effort: str | None = None  # None: not set explicitly (provider default applies)


@dataclass
class Exchange:
    """One HTTP request to the provider and what came back."""

    n: int
    endpoint: str
    request: dict[str, Any]
    status: int | None = None  # None: no response received (timeout or transport error)
    response: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, int] = field(default_factory=dict)
    elapsed_ms: int | None = None

    def refusal(self) -> str | None:
        return next((o["refusal"] for o in self.response.get("output", []) if o.get("type") == "refusal"), None)


class ProviderLedger:
    """Counts, caps and records every request to the provider, whichever framework sends it."""

    def __init__(self, *, source: str, max_requests: int, prices: Prices | None = None,
                 usd_cap: float | None = None, max_output_tokens: int = 2000):
        if usd_cap is not None and prices is None:
            raise ValueError("a spend cap needs prices")
        self.source, self.max_requests, self.prices, self.usd_cap = source, max_requests, prices, usd_cap
        self.max_output_tokens = max_output_tokens
        self.exchanges: list[Exchange] = []
        self.refused: list[str] = []  # requests that were never sent, and why
        self._lock = threading.Lock()
        self._started: dict[int, float] = {}

    # -- accounting
    def usage_totals(self) -> dict[str, int]:
        keys = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens")
        return {k: sum(e.usage.get(k, 0) for e in self.exchanges) for k in keys}

    def reported_cost_usd(self) -> float | None:
        """Cost of the token usage the provider reported, at the operator-supplied prices."""
        if self.prices is None:
            return None
        u = self.usage_totals()
        return self.prices.cost(u["input_tokens"], u["output_tokens"])

    def spend_bound_usd(self) -> float | None:
        """A conservative bound: reported usage, plus the worst case for every request that got no response
        (a timeout the provider may still have billed) or a success without usage."""
        if self.prices is None:
            return None
        unknown = sum(1 for e in self.exchanges if e.status is None or (e.status < 400 and not e.usage))
        return self.reported_cost_usd() + unknown * self.prices.worst_request(self.max_output_tokens)

    def last_refusal(self) -> str | None:
        with self._lock:
            return self.exchanges[-1].refusal() if self.exchanges else None

    # -- the hooks
    def admit(self, request: httpx2.Request) -> None:
        with self._lock:
            why = None
            if len(self.exchanges) >= self.max_requests:
                why = f"provider request cap reached ({self.max_requests})"
            elif self.usd_cap is not None:
                projected = self.spend_bound_usd() + self.prices.worst_request(self.max_output_tokens)
                if projected > self.usd_cap:
                    why = f"next request could exceed the authorised spend (${projected:.4f} > ${self.usd_cap:.2f})"
            if why:
                self.refused.append(why)
                raise ProviderCapReached(why + "; the request was NOT sent")
            exchange = Exchange(len(self.exchanges) + 1, request.url.path, summarize_request(request.content))
            self.exchanges.append(exchange)
            request.extensions["turnwise_exchange"] = exchange.n
            self._started[exchange.n] = time.monotonic()

    def receive(self, response: httpx2.Response) -> None:
        n = response.request.extensions.get("turnwise_exchange")
        with self._lock:
            exchange = next((e for e in self.exchanges if e.n == n), None)
            if exchange is None:
                return
            exchange.status = response.status_code
            exchange.elapsed_ms = int((time.monotonic() - self._started.pop(n, time.monotonic())) * 1000)
            exchange.response, exchange.usage = summarize_response(response)

    def clients(self, transport: Any = None, *, timeout_s: float) -> tuple[httpx2.Client, httpx2.AsyncClient]:
        """A sync and an async client whose every request goes through this ledger."""
        def on_request(request: httpx2.Request) -> None:
            self.admit(request)

        def on_response(response: httpx2.Response) -> None:
            response.read()
            self.receive(response)

        async def a_on_request(request: httpx2.Request) -> None:
            self.admit(request)

        async def a_on_response(response: httpx2.Response) -> None:
            await response.aread()
            self.receive(response)

        timeout = httpx2.Timeout(timeout_s)
        return (httpx2.Client(transport=transport, timeout=timeout,
                              event_hooks={"request": [on_request], "response": [on_response]}),
                httpx2.AsyncClient(transport=transport, timeout=timeout,
                                   event_hooks={"request": [a_on_request], "response": [a_on_response]}))


@dataclass
class ProviderSetup:
    """Everything a framework adapter needs to reach the provider (real or doubled) within bounds."""

    settings: ProviderSettings
    ledger: ProviderLedger
    transport: Any = None  # None: the real provider over the network

    @property
    def simulated(self) -> bool:
        return self.transport is not None

    @property
    def base_url(self) -> str | None:
        return DOUBLE_BASE_URL if self.simulated else None

    def api_key(self) -> str:
        if self.simulated:
            return DOUBLE_API_KEY
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise SystemExit("real provider calls need OPENAI_API_KEY; refusing to fall back silently.")
        return key

    @property
    def label(self) -> str:
        s = self.settings
        return (f"{self.ledger.source}; model={s.model}, max_retries=0, timeout={s.timeout_s:g}s, "
                f"max_output_tokens={s.max_output_tokens}")


def classify_from_wire(ledger: ProviderLedger | None, since: int) -> ModelCallFailed | None:
    """What the provider actually returned for the requests sent after ``since``, when a framework's exception
    hides it (LlamaIndex reports a refusal as a generic ValueError). None when the wire record adds nothing."""
    if ledger is None:
        return None
    new = ledger.exchanges[since:]
    if not new or new[-1].status is None:
        return None
    last = new[-1]
    if last.refusal() is not None:
        return ModelCallFailed("refusal", last.refusal()[:160])
    if last.response.get("status") == "incomplete":
        return ModelCallFailed("incomplete response", json.dumps(last.response.get("incomplete_details"))[:160])
    return None


# ---------------------------------------------------------------- what was sent and received
def summarize_request(content: bytes) -> dict[str, Any]:
    try:
        body = json.loads(content or b"{}")
    except ValueError:
        return {"unparsed_bytes": len(content or b"")}
    if not isinstance(body, dict):
        return {"unparsed_bytes": len(content or b"")}
    tools = [t for t in body.get("tools") or [] if isinstance(t, dict)]
    fmt = (body.get("text") or {}).get("format") if isinstance(body.get("text"), dict) else None
    items = body.get("input") if isinstance(body.get("input"), list) else []
    return {
        "model": body.get("model"),
        "tools": [t.get("name") or (t.get("function") or {}).get("name") for t in tools],
        "tools_strict": sorted({str(t.get("strict")) for t in tools}),
        "tool_choice": body.get("tool_choice"),
        "text_format": None if not isinstance(fmt, dict) else {k: fmt.get(k) for k in ("type", "name", "strict")},
        "temperature": body.get("temperature"),
        "reasoning": body.get("reasoning"),
        "max_output_tokens": body.get("max_output_tokens"),
        "store": body.get("store"),
        "stream": body.get("stream"),
        "input_items": [i.get("type") or i.get("role") for i in items if isinstance(i, dict)],
    }


def summarize_response(response: httpx2.Response) -> tuple[dict[str, Any], dict[str, int]]:
    try:
        body = response.json()
    except ValueError:
        return {"unparsed": response.text[:300]}, {}
    if not isinstance(body, dict):
        return {"unparsed": str(body)[:300]}, {}
    if response.status_code >= 400 or "output" not in body:
        err = body.get("error")
        return {"error": (err.get("message") if isinstance(err, dict) else str(err or body))[:300]}, {}
    out: list[dict[str, Any]] = []
    for item in body.get("output") or []:
        kind = item.get("type")
        if kind == "function_call":
            out.append({"type": "function_call", "name": item.get("name"), "arguments": str(item.get("arguments"))[:300]})
        elif kind == "message":
            for part in item.get("content") or []:
                if part.get("type") == "refusal":
                    out.append({"type": "refusal", "refusal": str(part.get("refusal"))[:300]})
                else:
                    out.append({"type": part.get("type"), "text": str(part.get("text"))[:300]})
        else:
            out.append({"type": kind})
    u = body.get("usage") or {}
    usage = {"input_tokens": int(u.get("input_tokens") or 0),
             "cached_input_tokens": int((u.get("input_tokens_details") or {}).get("cached_tokens") or 0),
             "output_tokens": int(u.get("output_tokens") or 0),
             "reasoning_tokens": int((u.get("output_tokens_details") or {}).get("reasoning_tokens") or 0)} if u else {}
    summary = {"model": body.get("model"), "status": body.get("status"), "output": out}
    if body.get("incomplete_details"):
        summary["incomplete_details"] = body["incomplete_details"]
    return summary, usage
