"""Offline regression tests for #17: budget accounting on concurrent/uncertain requests.

No provider credentials, network calls, model downloads or frozen evaluation data.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import os
import unittest
from unittest.mock import patch

from turnwise_lab.agent.loop import TurnState
from turnwise_lab.agent.remote import OpenAIDecisionsProvider, Spend, SystemOneProvider


class SpendReservationTests(unittest.TestCase):
    def test_parallel_calls_cannot_all_spend_the_same_remaining_budget(self):
        spend = Spend(cap_usd=3.0)
        start = Barrier(12)

        def attempt(_):
            start.wait()
            try:
                return spend.reserve(1.0)
            except PermissionError:
                return None

        with ThreadPoolExecutor(max_workers=12) as pool:
            result = list(pool.map(attempt, range(12)))
        tickets = [v for v in result if v is not None]
        self.assertEqual(len(tickets), 3)
        self.assertEqual(len(set(tickets)), 3)
        self.assertEqual(spend.requests, 3)
        self.assertEqual(spend.reserved_usd, 3.0)
        self.assertEqual(spend.spent_usd, 0.0)

    def test_actual_usage_underestimated_can_breach_cap_but_blocks_all_future_calls(self):
        spend = Spend(1.0)
        ticket = spend.reserve(0.6)
        spend.reconcile(ticket, 1.1, {"input_tokens": 1100})
        self.assertEqual(spend.spent_usd, 1.1)
        self.assertEqual(spend.reserved_usd, 0)
        with self.assertRaises(PermissionError):
            spend.reserve(0.01)
        self.assertEqual(spend.requests, 1)  # no attempted second call

    def test_failed_or_unmetered_request_retains_liability(self):
        spend = Spend(1.0)
        ticket = spend.reserve(0.8)
        spend.mark_unknown(ticket, "timeout")
        spend.mark_unknown(ticket, "timeout")  # idempotent
        self.assertEqual(spend.reserved_usd, 0.8)
        self.assertEqual(spend.spent_usd, 0.0)
        self.assertEqual(len(spend.usage), 1)
        with self.assertRaises(PermissionError):
            spend.reserve(0.3)
        spend.reconcile(ticket, 0.5, {"input_tokens": 500})
        self.assertAlmostEqual(spend.spent_usd, 0.5)
        self.assertAlmostEqual(spend.reserved_usd, 0.0)
        with self.assertRaises(ValueError):
            spend.mark_unknown(ticket, "double_close")

    def test_duplicate_reconciliation_and_invalid_amounts(self):
        spend = Spend(2.0)
        for amount in (-1.0, 0.0, float("nan"), float("inf")):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                spend.reserve(amount)
        ticket = spend.reserve(0.5)
        for amount in (-1.0, float("nan"), float("inf")):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                spend.reconcile(ticket, amount, {})
        spend.reconcile(ticket, 0.2, {"input_tokens": 2})
        with self.assertRaises(KeyError):
            spend.reconcile(ticket, 0.2, {"input_tokens": 2})


class ProviderReservationTests(unittest.TestCase):
    def provider(self):
        return OpenAIDecisionsProvider(
            endpoint="http://127.0.0.1:9876/v1/decisions",
            api_key_env="TW_TEST_FAKE", allow_remote=True, spend_cap_usd=1.0)

    def test_transport_failure_retains_budget_and_no_automatic_retry(self):
        with patch.dict(os.environ, {"TW_TEST_FAKE": "local-test-only"}):
            provider = self.provider()
            with patch.object(provider, "_post", side_effect=TimeoutError("offline fake")) as post:
                with self.assertRaises(TimeoutError):
                    provider.decide(TurnState("r1", "Get checkout error metrics"), None)
                self.assertEqual(provider.spend.requests, 1)
                self.assertGreater(provider.spend.reserved_usd, 0)
                self.assertEqual(provider.spend.usage[0]["reason"], "transport_or_protocol_failure")
                provider.spend.cap_usd = provider.spend.reserved_usd
                with self.assertRaises(PermissionError):
                    provider.decide(TurnState("r2", "Get checkout error metrics"), None)
                post.assert_called_once()

    def test_missing_usage_fails_closed_instead_of_guessing_actual_charge(self):
        with patch.dict(os.environ, {"TW_TEST_FAKE": "local-test-only"}):
            provider = self.provider()
            with patch.object(provider, "_post", return_value=({"answers": []}, 2.0)):
                with self.assertRaisesRegex(ValueError, "valid input-token usage"):
                    provider.decide(TurnState("r1", "Get checkout error metrics"), None)
            self.assertEqual(provider.spend.requests, 1)
            self.assertGreater(provider.spend.reserved_usd, 0)
            self.assertEqual(provider.spend.spent_usd, 0)
            self.assertEqual(provider.spend.usage[0]["reason"], "missing_or_invalid_usage")

    def test_metered_usage_reconciles_and_does_not_conceal_overrun(self):
        with patch.dict(os.environ, {"TW_TEST_FAKE": "local-test-only"}):
            provider = self.provider()
            payload = {"answers": [{"name": "next_operation", "type": "refusal"}],
                       "usage": {"input_tokens": 900}}
            with patch.object(provider, "_post", return_value=(payload, 3.0)):
                decision = provider.decide(TurnState("r1", "Get checkout error metrics"), None)
            self.assertEqual(decision.operation, "abstain")
            self.assertEqual(provider.spend.reserved_usd, 0)
            self.assertAlmostEqual(provider.spend.spent_usd, 900 * 0.10 / 1e6)
            self.assertEqual(provider.spend.usage[0]["status"], "metered")

    def test_unmetered_provider_is_not_reported_as_actual_spend(self):
        with patch.dict(os.environ, {"TW_TEST_FAKE": "local-test-only"}):
            provider = SystemOneProvider(
                model="local-contract-only", endpoint="http://127.0.0.1:9876/v1/choice",
                api_key_env="TW_TEST_FAKE", allow_remote=True, spend_cap_usd=1.0,
                price_per_input_token=1e-6)
            payload = {"choices": {"next_operation": {"choice": "get_error_metrics", "probabilities": {}}}}
            with patch.object(provider, "_post", return_value=(payload, 1.0)):
                decision = provider.decide(TurnState("r1", "Get checkout error metrics"), None)
            self.assertEqual(decision.target, "get_error_metrics")
            self.assertEqual(provider.spend.spent_usd, 0.0)
            self.assertGreater(provider.spend.reserved_usd, 0)
            self.assertEqual(provider.spend.usage[0]["reason"], "provider_does_not_report_usage")

    def test_invalid_cap_and_price_are_rejected_before_any_call(self):
        with patch.dict(os.environ, {"TW_TEST_FAKE": "local-test-only"}):
            for cap in (0.0, float("nan"), float("inf")):
                with self.subTest(cap=cap), self.assertRaises(PermissionError):
                    OpenAIDecisionsProvider(endpoint="http://127.0.0.1:9876/v1/decisions",
                                            api_key_env="TW_TEST_FAKE", allow_remote=True, spend_cap_usd=cap)
            for price in (0.0, -1.0, float("nan"), float("inf")):
                with self.subTest(price=price), self.assertRaises(PermissionError):
                    SystemOneProvider(model="test", endpoint="http://127.0.0.1:9876/v1/choice",
                                      api_key_env="TW_TEST_FAKE", allow_remote=True, spend_cap_usd=1.0,
                                      price_per_input_token=price)


if __name__ == "__main__":
    unittest.main()
