"""Cache-aware accounting for the architecture examples (issue #85). Stdlib only; sends nothing.

"Model calls" are not what a provider bills. A provider bills input tokens it had
to process afresh, input tokens it could read from a prompt cache (far cheaper),
sometimes a premium for writing that cache, and output tokens. Two different
things live in this module and must not be confused:

1. **Billing units** (``billing_units``, ``billing_totals``, ``billed_usd``): what a
   provider *reported* for real requests, in one schema with explicit unknowns.
   A value that was not reported is ``None``, never ``0``.

2. **A structural estimate** (``structural_units``, ``structural_cost``): how much
   of each request an architecture sends is an exact prefix of its previous
   request, and what that would imply under stated billing assumptions. It is
   derived from request text, with synthetic token counts when the provider is
   the local double. It is arithmetic about request *shape*. It is NOT a cost
   measurement and must always be labelled ``SIMULATED, structural``.

Prompt caches match on an exact prefix, so the unit that matters is "how much of
this request repeats the start of the last one", not "how many requests".
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

BILLING_SCHEMA = "turnwise-billing/v1"
# input_tokens_fresh: all input NOT read from a cache. input_tokens_cache_write: the part of the fresh input the
# provider billed at a cache-write price (a subset of fresh, unknown unless the provider reports it).
# output_tokens includes reasoning tokens; reasoning_tokens is that part, for information.
UNIT_FIELDS = ("input_tokens_fresh", "input_tokens_cache_read", "input_tokens_cache_write",
               "output_tokens", "reasoning_tokens")
STRUCTURAL_LABEL = ("SIMULATED, structural: request shapes come from the offline provider double, token counts "
                    "are synthetic and replies are simulated. Arithmetic under stated assumptions, NOT a cost "
                    "measurement.")
# Billing assumptions for the structural estimate, in the order they are reported.
NO_CACHING = "no caching"
CACHE_READS = "cache reads discounted"
CACHE_READS_AND_WRITES = "cache reads discounted, fresh input billed at the cache-write price"
ASSUMPTIONS = (NO_CACHING, CACHE_READS, CACHE_READS_AND_WRITES)


# ---------------------------------------------------------------- prices
@dataclass(frozen=True)
class PriceCard:
    """USD per million tokens, operator-supplied. ``source`` says where and when the numbers were read."""

    input_per_mtok: float
    cached_input_per_mtok: float
    cache_write_per_mtok: float
    output_per_mtok: float
    source: str = "operator-supplied"

    def __post_init__(self) -> None:
        for value in (self.input_per_mtok, self.cached_input_per_mtok, self.cache_write_per_mtok,
                      self.output_per_mtok):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError("token prices must be finite, nonnegative numbers")
        if self.input_per_mtok <= 0 or self.output_per_mtok <= 0:
            raise ValueError("input and output prices must be positive")


# ---------------------------------------------------------------- billing units (reported usage)
def billing_units(usage: Mapping[str, Any] | None) -> dict[str, int | None]:
    """One request's reported usage in billing units. Unknown stays ``None``.

    ``usage`` is the ledger's per-request record: ``input_tokens`` (total), ``cached_input_tokens``,
    ``output_tokens`` (reasoning included) and ``reasoning_tokens``. An empty record (an HTTP error, a timeout)
    means the provider reported nothing: every field is unknown, which is not the same as zero. Cache-write
    tokens are not part of that record, so they are always unknown here.
    """
    if not usage:
        return {name: None for name in UNIT_FIELDS}
    total = _count(usage.get("input_tokens"))
    cached = _count(usage.get("cached_input_tokens", 0))
    fresh = None if total is None or cached is None else max(total - cached, 0)
    return {"input_tokens_fresh": fresh, "input_tokens_cache_read": cached, "input_tokens_cache_write": None,
            "output_tokens": _count(usage.get("output_tokens")),
            "reasoning_tokens": _count(usage.get("reasoning_tokens", 0))}


def billing_totals(usages: Iterable[Mapping[str, Any] | None], *, basis: str) -> dict[str, Any]:
    """Totals over the requests of one run. A field is ``None`` as soon as one request did not report it.

    ``basis`` says where the numbers come from (for example "provider-reported" or "synthetic: provider double").
    """
    units = [billing_units(u) for u in usages]
    totals: dict[str, Any] = {"schema": BILLING_SCHEMA, "basis": basis, "requests": len(units),
                              "requests_without_usage": sum(1 for u in units if u["output_tokens"] is None)}
    for name in UNIT_FIELDS:
        values = [u[name] for u in units]
        totals[name] = None if not values or any(v is None for v in values) else sum(values)
    return totals


def billed_usd(units: Mapping[str, Any], card: PriceCard) -> float | None:
    """Cost of reported billing units at ``card``, or ``None`` when a needed count is unknown.

    Unknown cache-write tokens are NOT priced: fresh input is billed at the plain input price, so on a provider
    that charges a write premium this understates the bill. ``None`` is returned, not a guess, when fresh input,
    cache reads or output are unknown.
    """
    fresh, read, out = (units.get("input_tokens_fresh"), units.get("input_tokens_cache_read"),
                        units.get("output_tokens"))
    if fresh is None or read is None or out is None:
        return None
    write = units.get("input_tokens_cache_write") or 0
    return ((fresh - write) * card.input_per_mtok + write * card.cache_write_per_mtok
            + read * card.cached_input_per_mtok + out * card.output_per_mtok) / 1_000_000


def _count(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


# ---------------------------------------------------------------- request shape
def canonical_request_text(content: bytes | str | Mapping[str, Any] | None) -> str:
    """A stable rendering of what a Responses API request asks the model to read.

    Order: instructions, tool definitions, structured-output format, then each input item. Keys are sorted, so
    two requests with the same content render identically whatever the client's field order. Transport settings
    (model id, limits, sampling) are left out: they do not belong to the prompt. Unparseable content renders as
    the empty string, which shares no prefix with anything.
    """
    if isinstance(content, Mapping):
        body: Any = content
    else:
        try:
            body = json.loads(content or b"{}")
        except (TypeError, ValueError):
            return ""
    if not isinstance(body, Mapping):
        return ""
    parts = [str(body.get("instructions") or "")]
    if body.get("tools"):
        parts.append(json.dumps(body["tools"], sort_keys=True, separators=(",", ":")))
    if body.get("text"):
        parts.append(json.dumps(body["text"], sort_keys=True, separators=(",", ":")))
    items = body.get("input")
    for item in items if isinstance(items, list) else [items]:
        if item is not None:
            parts.append(item if isinstance(item, str) else json.dumps(item, sort_keys=True, separators=(",", ":")))
    return "\n".join(parts)


def shared_prefix_len(previous: str, current: str) -> int:
    """Length of the longest common prefix, in characters."""
    return len(os.path.commonprefix([previous, current]))


@dataclass(frozen=True)
class RequestShape:
    """One request of a run, as far as the structural estimate needs it."""

    chars: int  # length of the canonical request text
    shared_prefix_chars: int  # of which an exact prefix of the previous request in the same run
    input_tokens: int | None  # as reported (synthetic under the provider double)
    output_tokens: int | None
    tool_calls: int = 0  # function_call items in the response

    @property
    def shared_share(self) -> float:
        return 0.0 if self.chars <= 0 else self.shared_prefix_chars / self.chars


def shapes_from_exchanges(exchanges: Sequence[Mapping[str, Any]]) -> list[RequestShape]:
    """Build shapes from ledger exchange records (``dataclasses.asdict(Exchange)`` or the like)."""
    shapes = []
    for e in exchanges:
        structure, usage = e.get("structure") or {}, e.get("usage") or {}
        calls = sum(1 for o in (e.get("response") or {}).get("output", []) if o.get("type") == "function_call")
        shapes.append(RequestShape(int(structure.get("request_chars", 0)), int(structure.get("shared_prefix_chars", 0)),
                                   _count(usage.get("input_tokens")), _count(usage.get("output_tokens")), calls))
    return shapes


# ---------------------------------------------------------------- structural estimate
def structural_units(shapes: Sequence[RequestShape], *, stable_prefix_tokens: int = 0,
                     min_cacheable_tokens: int = 0) -> list[dict[str, Any]] | None:
    """Split each request's input tokens into fresh and cache-read, assuming every shared prefix is a cache hit.

    ``stable_prefix_tokens`` adds the same stable prefix (a larger system prompt and tool catalogue) to every
    request of the run: fresh on the first request, shared on the later ones. ``min_cacheable_tokens`` models a
    provider's minimum cacheable prompt length: a shared prefix shorter than it is not read from cache at all.
    Returns ``None`` if a request has no token count.
    """
    out = []
    for index, shape in enumerate(shapes):
        if shape.input_tokens is None or shape.output_tokens is None:
            return None
        shared = int(shape.input_tokens * shape.shared_share) + (stable_prefix_tokens if index else 0)
        total = shape.input_tokens + stable_prefix_tokens
        if shared < max(min_cacheable_tokens, 1):
            shared = 0
        out.append({"input_tokens_fresh": total - shared, "input_tokens_cache_read": shared,
                    "output_tokens": shape.output_tokens,
                    # A prompt shorter than the minimum is neither read from nor written to a cache.
                    "cacheable": total >= min_cacheable_tokens})
    return out


def structural_cost(shapes: Sequence[RequestShape], card: PriceCard, assumption: str, *,
                    stable_prefix_tokens: int = 0, min_cacheable_tokens: int = 0) -> float | None:
    """USD for a run's request shapes under one billing assumption. Arithmetic, not a measurement."""
    if assumption not in ASSUMPTIONS:
        raise ValueError(f"unknown billing assumption {assumption!r}")
    units = structural_units(shapes, stable_prefix_tokens=stable_prefix_tokens,
                             min_cacheable_tokens=0 if assumption == NO_CACHING else min_cacheable_tokens)
    if units is None:
        return None
    total = 0.0
    for u in units:
        fresh, read = u["input_tokens_fresh"], u["input_tokens_cache_read"]
        if assumption == NO_CACHING:
            total += (fresh + read) * card.input_per_mtok
        else:
            # The write premium applies only to a prompt long enough to be written to the cache.
            premium = assumption == CACHE_READS_AND_WRITES and u["cacheable"]
            total += fresh * (card.cache_write_per_mtok if premium else card.input_per_mtok)
            total += read * card.cached_input_per_mtok
        total += u["output_tokens"] * card.output_per_mtok
    return total / 1_000_000


def breakeven_cache_read_multiplier(a: Sequence[RequestShape], b: Sequence[RequestShape]) -> float | None:
    """The cache-read price, as a multiple of the fresh input price, at which runs ``a`` and ``b`` cost the same
    in input tokens (no write premium, no minimum). ``b`` is cheaper only above it. ``None`` if undefined."""
    ua, ub = structural_units(a), structural_units(b)
    if ua is None or ub is None:
        return None
    fresh_a, read_a = sum(u["input_tokens_fresh"] for u in ua), sum(u["input_tokens_cache_read"] for u in ua)
    fresh_b, read_b = sum(u["input_tokens_fresh"] for u in ub), sum(u["input_tokens_cache_read"] for u in ub)
    if read_a == read_b:
        return None
    return (fresh_b - fresh_a) / (read_a - read_b)
