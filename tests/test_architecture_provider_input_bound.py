"""Offline, transport-free whole-request input-budget regressions (#16).

The bound is intentionally conservative (UTF-8 wire bytes + overhead), not an
exact tokenizer count or a guarantee about final provider billing.
"""
from __future__ import annotations

import json
import unittest
from unittest import mock

try:
    import httpx2
    from examples.architecture.provider import (
        DOUBLE_SOURCE, Prices, ProviderCapReached, ProviderLedger, ProviderSettings, request_bound)
    from examples.architecture.live_smoke import plan, worst_case_usd, run_matrix
    HAVE_PROVIDER = True
except ImportError:
    HAVE_PROVIDER = False


def request(extra=""):
    return httpx2.Request(
        "POST", "https://provider-double.invalid/v1/responses",
        json={"model": "offline-test", "max_output_tokens": 2000,
              "input": [{"role": "user", "content": extra}]})


@unittest.skipUnless(HAVE_PROVIDER, "optional pinned httpx2 dependency required")
class WholeRequestInputCapTests(unittest.TestCase):
    def test_rejects_invalid_configurations(self):
        for cap in (-1, 1.5, True, "8000", float("inf")):
            with self.subTest(cap=cap), self.assertRaises(ValueError):
                ProviderLedger(source=DOUBLE_SOURCE, max_requests=2,
                               max_input_bound_tokens=cap)
        with self.assertRaises(ValueError):
            run_matrix(ProviderSettings("offline-test"), max_input_bound_tokens=-1)

    def test_exact_bound_is_admitted_without_a_paid_provider(self):
        r = request("ordinary synthetic question")
        n = request_bound(r.content, 2000)[0]
        ledger = ProviderLedger(source=DOUBLE_SOURCE, max_requests=2,
                                max_input_bound_tokens=n)
        ledger.admit(r)
        self.assertEqual(len(ledger.exchanges), 1)
        self.assertEqual(ledger.exchanges[0].bound_tokens[0], n)

    def test_oversized_request_fails_before_any_transport_or_spend(self):
        tiny = request("short")
        limit = request_bound(tiny.content, 2000)[0]
        oversized = request("x" * 2500)
        ledger = ProviderLedger(source=DOUBLE_SOURCE, max_requests=2,
                                max_input_bound_tokens=limit, prices=Prices(1, 10),
                                usd_cap=10.0)
        with self.assertRaisesRegex(ProviderCapReached, "whole-request input token upper bound"):
            ledger.admit(oversized)
        self.assertEqual(ledger.exchanges, [])
        self.assertEqual(len(ledger.refused), 1)
        self.assertEqual(ledger.spend_bound_usd(), 0)

    def test_budget_includes_serialized_envelope_not_just_user_text(self):
        r = request("")
        # Even an empty user string has JSON envelope, model, schema and safety margin.
        total, output = request_bound(r.content, 2000)
        self.assertGreater(total, 512)
        self.assertEqual(output, 2000)
        ledger = ProviderLedger(source=DOUBLE_SOURCE, max_requests=1,
                                max_input_bound_tokens=512)
        with self.assertRaises(ProviderCapReached):
            ledger.admit(r)

    def test_python_paid_entrypoint_refuses_missing_or_insufficient_authorization(self):
        settings = ProviderSettings("offline-test")
        prices = Prices(2.0, 8.0)
        invalid = (
            {},
            {"prices": prices},
            {"authorize_usd": 10.0},
            {"prices": prices, "authorize_usd": 0.0001},
            {"prices": prices, "authorize_usd": float("nan")},
            {"prices": prices, "authorize_usd": True},
        )
        for options in invalid:
            with self.subTest(options=options):
                # No import of an SDK or provider transport is permitted here.
                with mock.patch("examples.architecture.live_smoke.run_config",
                                side_effect=AssertionError("provider must never be called")) as call:
                    with self.assertRaises(ValueError):
                        run_matrix(settings, **options)
                    call.assert_not_called()

    def test_run_matrix_enforces_the_bound_in_every_configuration_before_transport(self):
        # Review finding: the plan/bound agreement was tested, but not that run_matrix hands the bound to the
        # ledger. With a bound below any real request, nothing may reach the (simulated) provider.
        from examples.architecture.provider_double import ProviderDouble
        double = ProviderDouble()
        report = run_matrix(ProviderSettings("gpt-4.1", temperature=0.0), double=double,
                            max_input_bound_tokens=600)
        self.assertEqual(double.requests, [])
        self.assertEqual(report["max_input_bound_tokens"], 600)
        self.assertEqual(len(report["configs"]), 4)
        for record in report["configs"]:
            with self.subTest(config=(record.get("framework"), record.get("architecture"))):
                self.assertIn("whole-request input token upper bound", json.dumps(record))

    def test_echoed_reasoning_items_count_against_the_input_bound(self):
        # Each echoed reasoning id is charged max_output_tokens, so a long native-agent run on a reasoning model
        # can hit the bound and halt before its own turn limit. That is the intended fail-closed behaviour.
        def with_reasoning(n):
            return httpx2.Request("POST", "https://provider-double.invalid/v1/responses", json={
                "model": "offline-test", "max_output_tokens": 2000,
                "input": [{"role": "user", "content": "q"}] + [{"type": "reasoning", "id": f"rs_{i}"}
                                                               for i in range(n)]})
        ledger = ProviderLedger(source=DOUBLE_SOURCE, max_requests=4, max_input_bound_tokens=8000)
        ledger.admit(with_reasoning(3))
        with self.assertRaisesRegex(ProviderCapReached, "whole-request input token upper bound"):
            ledger.admit(with_reasoning(4))
        self.assertEqual(len(ledger.exchanges), 1)

    def test_plan_and_cap_use_identical_input_assumption(self):
        p = Prices(2.0, 8.0)
        settings = ProviderSettings("offline-test", max_output_tokens=700)
        configs = (("openai-agents", "turnwise"),)
        expected = 4 * p.cost(1600, 700)
        self.assertAlmostEqual(worst_case_usd(p, settings, configs, 1600), expected)
        report = plan(settings, p, configs, 1600)
        self.assertIn("hard per-request input upper bound: 1600", report)
        self.assertIn("1600 input", report)
        self.assertIn(f"${expected:.4f}", report)


if __name__ == "__main__":
    unittest.main()
