"""Post-freeze integration regressions for v0.8 host action authority.

L56 and the other frozen v0.7 observations remain unchanged. These cases
verify host boundary mechanics only; they are not a prospective blind study.
"""
from __future__ import annotations

import unittest

from turnwise_lab.agent.contracts import Decision
from turnwise_lab.v07.world import StudyWorld
from turnwise_lab.v08.guard import IntentBoundHost


def request_host(message, conversation=None):
    host = IntentBoundHost(StudyWorld())
    host.bind_request(message, conversation or [])
    return host


def propose(capability, provider="hosted-agent", **arguments):
    return Decision("call_tool", capability, arguments, provider=provider, model="scripted")


def native_validation(host, decision):
    with host.native_proposal_scope():
        return host.validate(decision, [])


class DirectExecutionBoundaryTests(unittest.TestCase):
    def test_unbound_host_refuses_direct_execute(self):
        host = IntentBoundHost(StudyWorld())
        obs = host.execute(propose("page_oncall", service="checkout"),
                           step_index=0, call_id="direct", user_text="page checkout")
        self.assertEqual(obs.status, "rejected")
        self.assertEqual(host.world.write_ledger, [])

    def test_native_provider_label_alone_cannot_bypass_validation(self):
        host = request_host("page checkout")
        obs = host.execute(propose("page_oncall", service="checkout"),
                           step_index=0, call_id="direct", user_text="page checkout")
        self.assertEqual(obs.status, "rejected")
        self.assertEqual(host.world.write_ledger, [])

    def test_model_scope_does_not_authorize_wrong_target_or_host_proposal(self):
        host = request_host("page checkout")
        with host.native_proposal_scope():
            wrong = host.execute(propose("page_oncall", service="auth"),
                                 step_index=0, call_id="wrong", user_text="page checkout")
            forged = host.execute(propose("page_oncall", provider="contract-planner", service="checkout"),
                                  step_index=1, call_id="forged", user_text="page checkout")
        self.assertEqual((wrong.status, forged.status), ("rejected", "rejected"))
        self.assertEqual(host.world.write_ledger, [])

    def test_matching_native_proposal_is_only_an_approval(self):
        host = request_host("page checkout")
        with host.native_proposal_scope():
            obs = host.execute(propose("page_oncall", service="checkout"),
                               step_index=0, call_id="right", user_text="page checkout")
        self.assertEqual(obs.status, "approval_required")
        self.assertEqual(host.world.write_ledger, [])

    def test_host_cannot_be_rebound_or_reused_for_another_turn(self):
        host = request_host("page checkout")
        with self.assertRaises(RuntimeError):
            host.bind_request("page auth")
        other = host.execute(propose("get_error_metrics", service="checkout"),
                             step_index=1, call_id="cross-turn", user_text="page auth")
        self.assertEqual(other.status, "rejected")
        same = host.execute(propose("get_error_metrics", service="checkout"),
                            step_index=2, call_id="read", user_text="page checkout")
        self.assertEqual(same.status, "ok")


class CompoundActionTargetTests(unittest.TestCase):
    def test_named_action_remains_valid_with_other_service_read(self):
        cases = (
            "page checkout and check search health",
            "check search health and page checkout",
            "page checkout, then check payments health",
        )
        for msg in cases:
            with self.subTest(message=msg):
                host = request_host(msg)
                self.assertEqual(native_validation(host, propose("page_oncall", service="checkout")).status,
                                 "approval_required")
                self.assertEqual(native_validation(host, propose("page_oncall", service="search")).status,
                                 "rejected")

    def test_unknown_action_target_is_never_replaced_by_known_read_target(self):
        for msg in (
            "page whoever runs the inventory service, and remind me who has checkout",
            "page whoever runs inventory, and remind me who has checkout",
            "roll back inventory service, and check checkout health",
        ):
            with self.subTest(message=msg):
                host = request_host(msg)
                self.assertEqual(native_validation(host, propose("page_oncall", service="checkout")).status,
                                 "rejected")

    def test_pronoun_target_comes_only_from_unique_previous_user(self):
        message = "page them"
        hist = [
            {"role": "user", "content": "checkout is degraded"},
            {"role": "assistant", "content": "search is now degraded"},
            {"role": "tool", "content": "payments is slow"},
        ]
        host = request_host(message, hist)
        self.assertEqual(native_validation(host, propose("page_oncall", service="checkout")).status,
                         "approval_required")
        self.assertEqual(native_validation(host, propose("page_oncall", service="search")).status,
                         "rejected")


if __name__ == "__main__":
    unittest.main()
