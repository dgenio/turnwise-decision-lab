"""Defects of the frozen v0.6 system, reproduced without changing it (no model needed).

Each test pins a behaviour of v0.6 code that the v0.7 audit names as a failure
mechanism, next to the v0.7 behaviour for the same input. If someone later
"fixes" the frozen v0.6 code path, these tests fail and the audit must be
updated: the recorded v0.6 traces depend on the old behaviour.
"""
from __future__ import annotations

import unittest

from turnwise_lab.agent import bench as v06
from turnwise_lab.agent.contracts import Decision
from turnwise_lab.agent.host import Host
from turnwise_lab.agent.loop import TurnState, execute_user_turn
from turnwise_lab.agent.providers import HeuristicDecider, PendingGenerator, RuleContextSelector, ScriptedDecider
from turnwise_lab.agent.world import IncidentWorld
from turnwise_lab.v07 import bench as v07
from turnwise_lab.v07.evidence import compile_contract, type_claim
from turnwise_lab.v07.gate import ACQUIRE, CLARIFY, HOLD, ExitGate

CONVO = [{"role": "user", "content": "how's checkout holding up"}, {"role": "assistant", "content": "checkout is degraded"},
         {"role": "user", "content": "anything deployed to search today?"}, {"role": "assistant", "content": "yes: d-141 at 10:40"}]


class FrozenV06Defects(unittest.TestCase):
    def test_follow_up_resolves_to_the_first_service_in_history_not_the_latest(self):
        """providers.py: HeuristicDecider joins earlier user messages and takes services[0]."""
        d = HeuristicDecider().decide(TurnState("t", "who approved that deploy", CONVO), Host(IncidentWorld()))
        self.assertEqual(d.arguments, {"service": "checkout"})  # the user was talking about search
        self.assertEqual(type_claim("who approved that deploy", CONVO).entities, ["search"])

    def test_unmatched_action_request_falls_through_to_a_text_only_model(self):
        """providers.py: 'no rule matched; short general reply' turns an action request into light-model text."""
        d = HeuristicDecider().decide(TurnState("t", "roll it back", []), Host(IncidentWorld()))
        self.assertEqual((d.operation, d.model_tier), ("call_model", "light"))
        v = ExitGate().review(message="roll it back", conversation=[], observations=[], terminal="answer")
        self.assertEqual(v.action, CLARIFY)

    def test_host_accepts_finish_after_any_single_receipt(self):
        """host.py validate(): finish needs 'at least one verified observation', whatever the question was (v0.6 H09, H12)."""
        msg = "search p95 has been ugly since mid-morning. any chance the reindex did that?"
        tr = execute_user_turn(msg, host=Host(IncidentWorld()), turn_id="T", context=RuleContextSelector("heuristic"), generator=PendingGenerator(),
                               decider=ScriptedDecider([Decision("call_tool", "get_error_metrics", {"service": "search"}), Decision("finish")]))
        self.assertEqual(tr.final["kind"], "verified")
        self.assertNotIn("p95", tr.final["text"])  # the question was about p95; the receipt has no latency in it
        from turnwise_lab.agent.contracts import Observation
        obs = [Observation(o["step_index"], o["call_id"], o["operation"], o["target"], o["arguments"], o["status"], o["facts"]) for o in tr.observations]
        v = ExitGate().review(message=msg, conversation=[], observations=obs, terminal="finish")
        self.assertEqual(v.action, ACQUIRE)
        self.assertEqual(v.missing, ["health:search", "deploys:search"])

    def test_verification_marker_is_only_recognised_at_the_start_of_a_reply(self):
        """loop.py: text.upper().startswith('NEED_MORE_EVIDENCE'); v0.6 H19 emitted it after prose and it was ignored."""
        class Gen:
            def generate(self, prompt, tier, n):
                return {"status": "ok", "tier": tier, "model": "x", "text": "I cannot confirm this.\nNEED_MORE_EVIDENCE: logs from the search team",
                        "prompt_tokens": 1, "completion_tokens": 1, "prefill_ms": 0.0, "decode_ms": 0.0}
        msg = "Could you please get someone from the search team on the line?"
        tr = execute_user_turn(msg, host=Host(IncidentWorld()), turn_id="T", context=RuleContextSelector("heuristic"), generator=Gen(),
                               decider=ScriptedDecider([Decision("call_model", model_tier="heavy")]), verification=True)
        self.assertEqual(tr.final["kind"], "answer")
        self.assertEqual(tr.totals["verification_requests"], 0)
        self.assertEqual(ExitGate().review(message=msg, conversation=[], observations=[], terminal="answer").action, HOLD)

    def test_v06_scorer_ignores_required_evidence_on_compound_action_requests(self):
        """bench.py score(): for outcome=approval, required_facts are never checked (v0.6 H30)."""
        task = next(s for s in v06.load_scenarios(v06.SETS["heldout"]) if s["id"] == "H30")
        tr = {"final": {"kind": "approval_required", "text": "needs approval"}, "totals": {}, "steps": [],
              "observations": [{"step_index": 0, "call_id": "c", "operation": "call_tool", "target": "rollback_deployment",
                                "arguments": {"service": "checkout"}, "status": "approval_required", "facts": {}}]}
        self.assertTrue(v06.score(task, tr)["success"])
        self.assertEqual(v06.score(task, tr)["missing_facts"], ["errors:checkout"])
        self.assertFalse(v07.score({**task, "message": task["message"], "conversation": []}, tr)["success"])
        k = compile_contract(type_claim(task["message"]), task["message"])
        self.assertEqual(([r.key for r in k.requirements], k.hold[0]), (["errors:checkout"], "rollback_deployment"))


if __name__ == "__main__":
    unittest.main()
