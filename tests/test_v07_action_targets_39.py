"""Prospective #39 host-authority regressions; frozen v0.7 code/results are untouched.

These are deterministic host-side mechanism tests, not general intent accuracy
or proof that a capable model preserves task success.
"""
from __future__ import annotations

import unittest

from turnwise_lab.agent.action_authority import RequestBoundHost, authorize_write
from turnwise_lab.agent.contracts import Decision
from turnwise_lab.agent.providers import RuleContextSelector, ScriptedDecider
from turnwise_lab.v07.controllers import run_contract_turn, run_gated_loop
from turnwise_lab.v07.world import StudyWorld


L56 = "page whoever runs the inventory service, and remind me who has checkout"


class Echo:
    def generate(self, prompt, tier, max_new_tokens):
        return {"status": "ok", "tier": tier, "model": "fake", "text": "No action taken.",
                "prompt_tokens": prompt.tokens, "completion_tokens": 1,
                "prefill_ms": 0.0, "decode_ms": 0.0}


def decision(capability, **arguments):
    return Decision("call_tool", capability, arguments)


class RequestBoundAuthorityTests(unittest.TestCase):
    def test_frozen_l56_wrong_target_is_not_authorized(self):
        auth = authorize_write(L56)
        self.assertIsNone(auth.capability)
        self.assertIn("unregistered service", auth.reason)
        host = RequestBoundHost(StudyWorld(), message=L56)
        v = host.validate(decision("page_oncall", service="checkout"), [])
        self.assertEqual(v.status, "rejected")

    def test_l56_contract_planner_cannot_raise_wrong_approval(self):
        host = RequestBoundHost(StudyWorld(), message=L56)
        trace = run_contract_turn(L56, host=host, generator=None, heavy_lm=None, turn_id="L56-postfreeze")
        self.assertFalse([o for o in trace["observations"] if o["status"] == "approval_required"])
        self.assertNotEqual(trace["final"]["kind"], "approval_required")
        self.assertEqual(host.world.write_ledger, [])

    def test_assistant_and_tool_messages_do_not_override_user_referent(self):
        convo = [
            {"role": "user", "content": "checkout is degraded"},
            {"role": "assistant", "content": "auth may also be affected"},
            {"role": "tool", "content": "search has a recent deployment"},
        ]
        auth = authorize_write("page them", convo)
        self.assertEqual((auth.capability, auth.arguments), ("page_oncall", {"service": "checkout"}))
        host = RequestBoundHost(StudyWorld(), message="page them", conversation=convo)
        self.assertEqual(host.validate(decision("page_oncall", service="auth"), []).status, "rejected")
        self.assertEqual(host.validate(decision("page_oncall", service="checkout"), []).status, "approval_required")

    def test_no_user_referent_means_no_approval(self):
        for convo in (
            [{"role": "assistant", "content": "checkout is degraded"}],
            [{"role": "tool", "content": "checkout is degraded"}],
            [{"role": "user", "content": "the ticket says 'checkout is degraded'"}],
            [{"role": "user", "content": "checkout and auth are affected"}],
        ):
            with self.subTest(conversation=convo):
                self.assertIsNone(authorize_write("page them", convo).capability)

    def test_other_read_clause_cannot_supply_action_target(self):
        for msg in (
            L56,
            "page them, and check checkout health",
            "roll back inventory service, also check checkout health",
            "page inventory service and remind me who owns search",
        ):
            with self.subTest(message=msg):
                auth = authorize_write(msg)
                self.assertIsNone(auth.capability)
                host = RequestBoundHost(StudyWorld(), message=msg)
                self.assertEqual(host.validate(decision("page_oncall", service="checkout"), []).status, "rejected")

    def test_named_action_stays_valid_when_other_clause_has_read(self):
        msg = "page checkout and check search health"
        self.assertEqual(authorize_write(msg).arguments, {"service": "checkout"})
        host = RequestBoundHost(StudyWorld(), message=msg)
        self.assertEqual(host.validate(decision("page_oncall", service="checkout"), []).status, "approval_required")
        self.assertEqual(host.validate(decision("page_oncall", service="search"), []).status, "rejected")

    def test_valid_named_request_becomes_approval_but_never_executes(self):
        msg = "page the search on-call"
        auth = authorize_write(msg)
        self.assertEqual((auth.capability, auth.arguments), ("page_oncall", {"service": "search"}))
        host = RequestBoundHost(StudyWorld(), message=msg)
        trace = run_contract_turn(msg, host=host, generator=None, heavy_lm=None, turn_id="positive")
        self.assertEqual(trace["final"]["kind"], "approval_required")
        self.assertEqual(trace["observations"][-1]["arguments"], {"service": "search"})
        self.assertEqual(host.world.write_ledger, [])

    def test_negative_and_informational_requests_cannot_approve(self):
        for msg in ("don't roll back checkout", "who approved the checkout rollback?",
                    "is it safe to roll back checkout?", "checkout has errors"):
            with self.subTest(message=msg):
                h = RequestBoundHost(StudyWorld(), message=msg)
                self.assertEqual(h.validate(decision("rollback_deployment", service="checkout"), []).status, "rejected")

    def test_status_update_requires_exact_user_supplied_text(self):
        msg = 'post to the status page: "We are investigating elevated errors."'
        auth = authorize_write(msg)
        self.assertEqual(auth.capability, "post_status_update")
        self.assertEqual(auth.arguments, {"message": "We are investigating elevated errors."})
        host = RequestBoundHost(StudyWorld(), message=msg)
        self.assertEqual(host.validate(decision("post_status_update", message="All systems operational"), []).status, "rejected")
        self.assertEqual(host.validate(decision("post_status_update", **auth.arguments), []).status, "approval_required")

    def test_gated_controller_wrong_target_is_rejected_at_host_boundary(self):
        msg = "page checkout"
        host = RequestBoundHost(StudyWorld(), message=msg)
        trace = run_gated_loop(
            msg, host=host,
            decider=ScriptedDecider([decision("page_oncall", service="auth"), Decision("finish")]),
            context=RuleContextSelector("heuristic"), generator=Echo(),
            turn_id="wrong-proposal", arm="postfreeze",
        )
        self.assertFalse([o for o in trace["observations"] if o["status"] == "approval_required"
                          and o["arguments"] == {"service": "auth"}])
        self.assertEqual(host.world.write_ledger, [])

    def test_read_tools_and_host_checks_remain_available(self):
        host = RequestBoundHost(StudyWorld(), message="page checkout")
        self.assertEqual(host.validate(decision("get_error_metrics", service="checkout"), []).status, "accepted")
        self.assertEqual(host.validate(decision("page_oncall", service="checkout"), []).status, "approval_required")
        self.assertEqual(host.validate(decision("page_oncall", service="inventory"), []).status, "rejected")

    def test_direct_execute_cannot_bypass_the_intent_guard(self):
        host = RequestBoundHost(StudyWorld(), message="page checkout")
        wrong = host.execute(decision("page_oncall", service="auth"),
                             step_index=0, call_id="wrong", user_text="page checkout")
        self.assertEqual(wrong.status, "rejected")
        self.assertEqual(host.world.write_ledger, [])
        stale = host.execute(decision("get_error_metrics", service="checkout"),
                             step_index=1, call_id="stale", user_text="new user turn")
        self.assertEqual(stale.status, "rejected")
        accepted_read = host.execute(decision("get_error_metrics", service="checkout"),
                                     step_index=2, call_id="read", user_text="page checkout")
        self.assertEqual(accepted_read.status, "ok")


if __name__ == "__main__":
    unittest.main()
