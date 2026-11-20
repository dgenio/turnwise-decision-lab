"""Offline provider-ledger configuration gate; no provider transport or credentials."""
from __future__ import annotations

import unittest

try:
    import httpx2
    from examples.architecture.provider import (
        DOUBLE_SOURCE, Prices, ProviderCapReached, ProviderLedger
    )
    HAVE_PROVIDER = True
except ImportError:
    HAVE_PROVIDER = False


@unittest.skipUnless(HAVE_PROVIDER, "provider's pinned httpx2 dependency is required")
class ProviderLimitConfigurationTests(unittest.TestCase):
    def test_nonfinite_and_nonnumeric_price_rejected(self):
        for value in (float("nan"), float("inf"), -float("inf"),
                      0.0, -1.0, True, "2.5"):
            with self.subTest(value=repr(value)):
                with self.assertRaises(ValueError):
                    Prices(value, 10)
                with self.assertRaises(ValueError):
                    Prices(2.5, value)

    def test_nonfinite_and_invalid_spend_cap_rejected_before_transport(self):
        prices = Prices(2.5, 10)
        for cap in (float("nan"), float("inf"), -float("inf"),
                    -1, True, "2.0"):
            with self.subTest(cap=repr(cap)), self.assertRaises(ValueError):
                ProviderLedger(source=DOUBLE_SOURCE, max_requests=10, prices=prices,
                               usd_cap=cap)
        with self.assertRaises(ValueError):
            ProviderLedger(source=DOUBLE_SOURCE, max_requests=10, usd_cap=1)

    def test_request_and_output_limits_must_be_integers(self):
        for count in (-1, True, 1.5, float("nan"), float("inf")):
            with self.subTest(count=repr(count)), self.assertRaises(ValueError):
                ProviderLedger(source=DOUBLE_SOURCE, max_requests=count)
        for count in (-1, 0, True, 1.5, float("nan"), float("inf")):
            with self.subTest(output=repr(count)), self.assertRaises(ValueError):
                ProviderLedger(source=DOUBLE_SOURCE, max_requests=2,
                               max_output_tokens=count)

    def test_zero_cap_and_zero_requests_are_valid_denial_configurations(self):
        prices = Prices(2.5, 10)
        for cap, requests in ((0, 1), (1.0, 0)):
            with self.subTest(cap=cap, requests=requests):
                ledger = ProviderLedger(source=DOUBLE_SOURCE, max_requests=requests,
                                        prices=prices, usd_cap=cap)
                request = httpx2.Request(
                    "POST", "https://provider-double.invalid/v1/responses",
                    json={"model": "offline-test", "max_output_tokens": 2000, "input": []})
                with self.assertRaises(ProviderCapReached):
                    ledger.admit(request)
                self.assertEqual(ledger.exchanges, [])
                self.assertEqual(len(ledger.refused), 1)

    def test_finite_budget_and_prices_still_admit_bounded_request(self):
        prices = Prices(2.5, 10)
        ledger = ProviderLedger(source=DOUBLE_SOURCE, max_requests=2,
                                prices=prices, usd_cap=1.0)
        request = httpx2.Request(
            "POST", "https://provider-double.invalid/v1/responses",
            json={"model": "offline-test", "max_output_tokens": 2000, "input": []})
        ledger.admit(request)
        self.assertEqual(len(ledger.exchanges), 1)
        self.assertGreater(ledger.spend_bound_usd(), 0)
        self.assertLess(ledger.spend_bound_usd(), 1)


if __name__ == "__main__":
    unittest.main()
