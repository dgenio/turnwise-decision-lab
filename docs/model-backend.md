# Optional hosted generation: strictly opt-in

`turnwise_lab.provider_cli` can send **one synthetic task** to an explicitly selected OpenAI-compatible Chat Completions endpoint. This is an integration hook for later work, **not** a live model benchmark or an evaluated production path.

The remote adapter is exercised in CI through a **localhost mock HTTP endpoint** which returns a canned response. That test checks request format, usage extraction, and opt-in logic only. No claim about provider compatibility, model quality or price can be derived from it.

Safety/usage boundaries:

- Both `--allow-remote` and a nonempty `OPENAI_API_KEY` environment variable are required. This never runs in the default demo.
- Request/sources must be labeled public; only explicitly authored synthetic fixtures belong here.
- HTTPS is required for non-loopback endpoints. Loopback HTTP is permitted only for local development/tests.
- An obvious-pattern detector rejects some emails/secret text. It is not sufficient to clear real company/customer data.
- The explicit endpoint and model ID are chosen by the operator. An OpenAI-compatible API is not guaranteed to support all backends identically; invalid endpoints fail rather than silently running another route.
- The API key is sent **only to the endpoint the operator names**: HTTP redirects are refused, because `urllib` would otherwise follow a 301/302/303 and copy the `Authorization` header to the new location, even on another host (fixed 2026-11-20, #17; `tests/test_provider.py` reproduces the leak). Any HTTPS host is accepted by design (OpenAI-compatible providers differ), so the operator remains responsible for naming a trusted one.
- One request, no retries, and output is bounded (`max_tokens`, default 800, at most 8192). There is no spend ledger here; the bounded real-provider path with a pre-send spend reservation is `examples/architecture/provider.py`.
- Usage counts are read only when returned by the provider. **Cost is always unknown/null** without a verified provider price schedule.
- The prompt asks the model to treat retrieved evidence as untrusted and cite IDs; it does not prove prompt-injection resistance or factual correctness.
- Do not enter confidential data, corporate contexts, credentials in arguments, or authorization tokens in prompts.

Sample invocation is in the README. For a meaningful provider comparison, first add an exact model/config receipt and deterministic task-level answer checker, use a measured per-task budget, and preserve both failures and successes.
