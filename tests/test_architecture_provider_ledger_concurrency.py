"""Spend-reservation regressions ported from experimental PR #44 onto the canonical ``ProviderLedger``.

#44 fixed concurrent over-admission and unknown-cost liabilities in the v0.6 ``turnwise_lab/agent/remote.py``
adapter, which is not on ``main``. The canonical provider path already admits under a lock and reserves
every admitted request's bound (including HTTP errors without usage, tested in
``test_architecture_provider_readiness.py``). This file keeps #44's two remaining properties pinned on
that path:

* simultaneous requests cannot all spend the same remaining authorisation;
* reported usage larger than the pre-send bound counts against the cap and blocks later requests.

Offline: no transport, credentials or provider calls. The ledger is a per-process estimate, not a
provider billing cap (issue #17).
"""
from __future__ import annotations

import json
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

try:
    import httpx2
    from examples.architecture.provider import (
        DOUBLE_SOURCE, Prices, ProviderCapReached, ProviderLedger, request_bound)
    HAVE_PROVIDER = True
except ImportError:  # the pinned SDKs bring httpx2; CI's architecture job requires them
    HAVE_PROVIDER = False

URL = "https://provider-double.invalid/v1/responses"
PAYLOAD = json.dumps({"model": "offline-test", "max_output_tokens": 2000, "input": "q"}).encode()


@unittest.skipUnless(HAVE_PROVIDER, "optional pinned httpx2 dependency required")
class LedgerReservationTests(unittest.TestCase):
    def test_simultaneous_requests_cannot_all_spend_the_same_remaining_authorisation(self):
        prices = Prices(input_per_mtok=2.0, output_per_mtok=8.0)
        one = prices.cost(*request_bound(PAYLOAD, 2000))
        ledger = ProviderLedger(source=DOUBLE_SOURCE, max_requests=100, prices=prices, usd_cap=3.5 * one)
        # Widen the check-to-reserve window so a non-atomic admit would reliably over-admit (verified by
        # removing the ledger's lock: all twelve requests then pass). With the lock, admits serialise.
        read_bound = ledger.spend_bound_usd

        def slow_bound():
            value = read_bound()
            time.sleep(0.005)
            return value

        ledger.spend_bound_usd = slow_bound
        start = Barrier(12)

        def attempt(_):
            request = httpx2.Request("POST", URL, content=PAYLOAD)
            start.wait()
            try:
                ledger.admit(request)
                return True
            except ProviderCapReached:
                return False

        with ThreadPoolExecutor(max_workers=12) as pool:
            admitted = sum(pool.map(attempt, range(12)))
        self.assertEqual(admitted, 3)
        self.assertEqual(len(ledger.exchanges), 3)
        self.assertEqual(len(ledger.refused), 9)
        self.assertEqual(sorted(e.n for e in ledger.exchanges), [1, 2, 3])
        self.assertLessEqual(read_bound(), 3.5 * one)

    def test_reported_usage_above_the_bound_counts_and_blocks_later_requests(self):
        prices = Prices(input_per_mtok=2.0, output_per_mtok=8.0)
        one = prices.cost(*request_bound(PAYLOAD, 2000))
        ledger = ProviderLedger(source=DOUBLE_SOURCE, max_requests=10, prices=prices, usd_cap=2.5 * one)
        first = httpx2.Request("POST", URL, content=PAYLOAD)
        ledger.admit(first)
        usage = {"input_tokens": 400_000, "output_tokens": 2000}  # far above the byte-derived bound
        ledger.receive(httpx2.Response(200, request=first, json={
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}],
            "usage": usage}))
        reported = prices.cost(usage["input_tokens"], usage["output_tokens"])
        self.assertGreater(reported, 2.5 * one)
        self.assertAlmostEqual(ledger.spend_bound_usd(), reported)  # never reduced to the smaller estimate
        with self.assertRaises(ProviderCapReached):
            ledger.admit(httpx2.Request("POST", URL, content=PAYLOAD))
        self.assertEqual(len(ledger.exchanges), 1)


if __name__ == "__main__":
    unittest.main()
