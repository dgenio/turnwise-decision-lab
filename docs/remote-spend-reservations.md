# Remote decision budget reservations — offline engineering note (#17)

**Scope:** a focused, independently reviewable safety fix on the experimental v0.6 branch. No hosted call, model download, publication or release. Historical v0.6 results and traces are unchanged.

## Before / after

Before: `Spend.reserve(estimate)` only read `spent_usd`. Two concurrent callers could both see the same available budget, send their requests, and record spending afterwards. A failed or unmetered request could be counted as free.

After: each caller atomically reserves an estimated USD liability **before transport**. All reservations, metered charges and undecidable liabilities count against later requests. A failed request or missing usage retains its reservation: failure, timeout or absent accounting is **not** evidence of zero charges. OpenAI's response `usage.input_tokens` must be a nonnegative integer to reconcile metered cost; if missing or malformed, the caller fails closed. System One's unverified usage stays as reserved estimated liability rather than being reported as measured spend. The process does not retry automatically. Counter and ledger mutations are lock protected.

The budget ledger distinguishes:
- `spent_usd`: metered, reported charges in this process.
- `reserved_usd`: in-flight or unknown-cost liability in this process.
- `requests`: attempts admitted by the gate, even if transport later failed.
- `usage`: a minimal accounting/status record, not request prompts.

## What this does **not** guarantee

**This is not an absolute provider billing cap.** The provider can charge more than the client's estimate; network timeouts and missing usage can leave the actual amount unknowable. An overrun is recorded and prevents new reservations, but cannot undo the charge. Per-process state is not shared across worker processes and does not survive restart. Pricing can change, and server-side framing, cache write charges and retries outside this code may not be covered. The input-byte estimator plus allowance is conservative but is not a proven server billing bound. The code makes no promise that a provider will honor a client-side budget.

**Never enable for real data or real spend on the strength of this PR.** The remaining #17 gates still include current provider contract/pricing validation; stronger sensitive-data allowlists (the regex is not DLP); redirect and endpoint credential-exfiltration controls; global/persistent budgets and maximum-response-cost accounting; provider errors and retries; separately approved, opt-in live smoke tests. Provider APIs are **not_run** against live services here.

## Verification

`python -m unittest tests.test_remote_spend_reservations` (or test discovery) runs nine deterministic local cases, including 12 simultaneous reservation attempts, underestimated actual charges, double reconciliation, transport failures, missing usage, the unmetered provider and invalid budget/prices. No network is used in those tests. Existing offline CI should continue to pass, including byte-identical frozen evidence regeneration.

Integration remains gated by #5, #9, #17 and tracker #24. Do not close #17 for this partial fix.
