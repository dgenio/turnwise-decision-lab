# Canonical provider input-budget gate — 2026-11-20

**Scope:** narrowly port the fail-closed whole-request budget invariant from experimental [PR #31](https://github.com/dgenio/turnwise-decision-lab/pull/31) to the canonical provider HTTP boundary. This is **not** a merge of the historical `turnwise_lab/agent` runtime or evidence of model performance.

## Mechanism

The shared `ProviderLedger` already guarded request count, output tokens and estimated USD liability at the HTTP request hook. It now also takes an optional `max_input_bound_tokens`, rejecting requests **before transport** when `request_bound(request.content, max_output_tokens, reasoning_refs)[0]` exceeds the bound. The estimate uses the **complete serialized provider request**, including instructions, tool schemas, selected context, and a formatting margin; it is not based solely on the user prompt. Echoed reasoning references are additionally charged conservatively.

The bounded smoke CLI exposes `--max-input-bound-tokens` (default **8,000**). Its planned worst-case USD calculation uses that **same enforced value** rather than an unenforced input-size assumption. Both conventional and Turnwise configurations use the common transport hook, including requests made during native agent handoffs. The existing response/output request and estimated-spend guards remain in place. **The Python `run_matrix` entrypoint now independently rejects paid mode without explicit prices, a positive finite USD authorization and an authorization that covers its planned worst case**; the CLI check alone is not the sole guard.

## Strict limitations

- **Not an exact tokenizer count.** Wire bytes plus margin provide a conservative bound; no model-specific tokenizer is available at this hook. When an adapter supplies a trustworthy model tokenizer later, compare its exact *fully assembled* prompt counts against this upper-bound safeguard.
- **Not a billing guarantee.** Provider-side retained state, dynamic reasoning usage, server-side formatting and provider invoices may differ. Estimated liabilities and actual provider-reported usage must be reported separately, including requests without usage data.
- **No truncation.** Overflow is rejected explicitly before sending rather than discarding mandatory safety instructions or silently omitting evidence.
- **No improvement claim.** This is a budget invariant, not a test of cheaper routing, end-to-end correctness or latency. Research comparisons remain gated by [#9](https://github.com/dgenio/turnwise-decision-lab/issues/9).
- The default `ProviderLedger` argument remains `None` for other callers; the bounded smoke runner explicitly supplies the enforced limit. Future paid entrypoints should supply their own hard bound.

## Developer tests

`tests/test_architecture_provider_input_bound.py` verifies invalid configurations, an exact-bound admission, pre-send oversized rejection, whole-envelope counting and agreement between the plan and the bound. Run the existing provider readiness and cross-framework offline matrix as well; **no provider calls are required**.

Related: [#16](https://github.com/dgenio/turnwise-decision-lab/issues/16), [#31](https://github.com/dgenio/turnwise-decision-lab/pull/31), [#37](https://github.com/dgenio/turnwise-decision-lab/pull/37), [#24](https://github.com/dgenio/turnwise-decision-lab/issues/24).
