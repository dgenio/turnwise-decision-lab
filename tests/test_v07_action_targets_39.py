"""Post-freeze regressions for #39; not part of the v0.7 locked-set scores.

Host approval intent must never be retargeted using an assistant/tool message,
a different service mentioned in the same request, or an unrecognized target.
These are deterministic mechanism checks, not evidence of semantic reliability.
"""
from __future__ import annotations

import unittest

from turnwise_lab.agent.contracts import Decision
from turnwise_lab.agent.host import Host
from turnwise_lab.agent.providers import RuleContextSelector, ScriptedDecider
from turnwise_lab.v07.controllers import run_contract_turn, run_gated_loop
from turnwise_lab.v07.evidence import compile_contract, focus_entity, type_claim
from turnwise_lab.v07.gate import ExitGate
from turnwise_lab.v07.world import StudyWorld


L56 = "page whoever runs the inventory service, and remind me who has checkout"


class Echo:
    def generate(self, prompt, tier, max_new_tokens):
        return {"status": "ok", "tier": tier, "model": "fake", "text": "No action taken.",
                "prompt_tokens": prompt.tokens, "completion_tokens": 1,
                "prefill_ms": 0.0, "decode_ms": 0.0}


class ActionTargetAuthorityTests(unittest.TestCase):
    def test_frozen_l56_wrong_service_cannot_become_host_approval(self):
        c = type_claim(L56)
        self.assertEqual(c.type, "ambiguous")
        self.assertIsNone(compile_contract(c, L56).hold)
        host = Host(StudyWorld())
        trace = run_contract_turn(L56, host=host, generator=None, heavy_lm=None, turn_id="L56-regression")
        self.assertEqual(trace["final"]["kind"], "clarify")
        self.assertFalse([o for o in trace["observations"] if o["status"] == "approval_required"])
        self.assertEqual(host.world.write_ledger, [])

    def test_assistant_and_tool_mentions_cannot_override_last_user_referent(self):
        convo = [
            {"role": "user", "content": "checkout is degraded"},
            {"role": "assistant", "content": "auth may also have failed"},
            {"role": "tool", "content": "search has a recent deployment"},
        ]
        self.assertEqual(focus_entity("page them", convo), (["checkout"], "conversation"))
        c = type_claim("page them", convo)
        self.assertEqual(c.type, "action")
        self.assertEqual(compile_contract(c, "page them").hold, ("page_oncall", {"service": "checkout"}))
        gate = ExitGate()
        self.assertIsNotNone(gate.veto("page them", convo, "page_oncall", {"service": "auth"}))
        self.assertIsNone(gate.veto("page them", convo, "page_oncall", {"service": "checkout"}))

    def test_assistant_only_and_quoted_prior_text_are_not_action_authority(self):
        for convo in (
            [{"role": "assistant", "content": "checkout is degraded"}],
            [{"role": "tool", "content": "checkout is degraded"}],
            [{"role": "user", "content": "Ticket says 'checkout is degraded'"}],
        ):
            with self.subTest(conversation=convo):
                c = type_claim("page them", convo)
                self.assertEqual(c.type, "ambiguous")
                self.assertIsNone(compile_contract(c, "page them").hold)

    def test_mixed_known_and_unknown_service_cannot_substitute_target(self):
        for msg in (
            L56,
            "roll back inventory service, also check checkout health",
            "page the inventory service and check who owns search",
        ):
            with self.subTest(message=msg):
                c = type_claim(msg)
                self.assertEqual(c.type, "ambiguous")
                self.assertIsNone(compile_contract(c, msg).hold)
                self.assertIsNotNone(ExitGate().veto(msg, [], "page_oncall", {"service": "checkout"}))

    def test_direct_valid_target_remains_approval_required_not_executed(self):
        msg = "page the search on-call"
        c = type_claim(msg)
        self.assertEqual(c.type, "action")
        self.assertEqual(compile_contract(c, msg).hold, ("page_oncall", {"service": "search"}))
        self.assertIsNone(ExitGate().veto(msg, [], "page_oncall", {"service": "search"}))
        host = Host(StudyWorld())
        trace = run_contract_turn(msg, host=host, generator=None, heavy_lm=None, turn_id="positive")
        self.assertEqual(trace["final"]["kind"], "approval_required")
        self.assertEqual(trace["observations"][-1]["arguments"], {"service": "search"})
        self.assertEqual(host.world.write_ledger, [])

    def test_gated_controller_rejects_wrong_target_but_can_hold_right_one(self):
        host = Host(StudyWorld())
        trace = run_gated_loop(
            "page checkout",
            host=host,
            decider=ScriptedDecider([
                Decision("call_tool", "page_oncall", {"service": "auth"}),
                Decision("finish"),
            ]),
            context=RuleContextSelector("heuristic"),
            generator=Echo(),
            turn_id="wrong-proposal",
            arm="regression",
        )
        approvals = [o for o in trace["observations"] if o["status"] == "approval_required"]
        self.assertFalse(any(o["arguments"] == {"service": "auth"} for o in approvals))
        self.assertTrue(all(o["arguments"] == {"service": "checkout"} for o in approvals))
        self.assertEqual(host.world.write_ledger, [])

    def test_read_tools_unaffected_and_current_turn_permission_required(self):
        gate = ExitGate()
        self.assertIsNone(gate.veto("tell me checkout error rates", [], "get_error_metrics", {"service": "checkout"}))
        self.assertIsNotNone(gate.veto("who owns checkout?", [], "page_oncall", {"service": "checkout"}))
        self.assertIsNotNone(gate.veto("roll back checkout", [], "rollback_deployment", {"service": "auth"}))
        self.assertIsNone(gate.veto("roll back checkout", [], "rollback_deployment", {"service": "checkout"}))


if __name__ == "__main__":
    unittest.main()
