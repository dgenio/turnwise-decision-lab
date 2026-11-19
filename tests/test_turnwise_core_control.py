"""Turnwise Core per-step control mechanism (#34): fake policy, fake heavy model, real v0.6 host.

Mechanism test only. It shows WHO controls each step when a strong model returns
an unresolved result. It says nothing about decision quality, answer quality or
cost savings. No model is loaded and nothing leaves the process.

Arm C (Turnwise Core): a decision policy chooses every operation; a heavy-model
call is one operation; its typed result is an observation that goes back to the
policy. Arm D (handoff) is shown only for contrast, through the existing native
heavy agent (``run_heavy_agent``); #32/#33 are not reimplemented here.
"""
from __future__ import annotations

import unittest

from turnwise_lab.agent.contracts import Decision
from turnwise_lab.agent.heavy_agent import run_heavy_agent
from turnwise_lab.agent.host import Host, Limits
from turnwise_lab.agent.loop import execute_user_turn
from turnwise_lab.agent.providers import HeuristicDecider, RuleContextSelector, ScriptedDecider
from turnwise_lab.agent.world import IncidentWorld
from turnwise_lab.local_models import Generation

MSG = "Could the latest checkout deployment explain the increase in errors?"
OWNER = {"scripted": "decision_policy", "heavy-agent": "native_heavy_agent"}


def tool(target, **args):
    return Decision("call_tool", target, args)


def heavy(**kw):
    return Decision("call_model", model_tier="heavy", **kw)


# Typed outcomes the fake heavy model can return (text, outcome).
def proposal(target, text="", operation="call_tool", **args):
    return text, {"kind": "tool_proposal", "proposed_call": {"operation": operation, "target": target, "arguments": args}}


def needs_evidence(text):
    return text, {"kind": "needs_evidence"}


def answer(text):
    return text, {"kind": "answer_candidate"}


def untyped(text):
    return text, None


class FakeHeavyModel:
    """Generator double for a strong model. It only returns text and a typed outcome; it executes nothing."""

    def __init__(self, outcomes, default=None):
        self.outcomes, self.default, self.calls = list(outcomes), default, []

    def generate(self, prompt, tier, max_new_tokens):
        self.calls.append({"tier": tier, "max_new_tokens": max_new_tokens, "prompt": prompt.text()})
        if not self.outcomes and self.default is None:
            raise AssertionError("fake heavy model called more often than scripted")
        text, outcome = self.outcomes.pop(0) if self.outcomes else self.default
        gen = {"status": "ok", "tier": tier, "model": "fake-heavy", "text": text, "prompt_tokens": prompt.tokens,
               "completion_tokens": min(max(1, len(text.split())), max_new_tokens), "prefill_ms": 0.0, "decode_ms": 0.0}
        if outcome is not None:
            gen["outcome"] = outcome
        return gen


def adopt_latest_proposal(state):
    """Policy step: decide to run the call a model proposed. Only the host can then accept or reject it."""
    obs = state.latest_observation
    p = getattr(obs, "proposal", None)
    if obs is None or obs.status != "tool_proposal" or not p:
        return Decision("abstain", rationale=f"expected a typed tool proposal, saw {obs.status if obs else None!r}")
    return Decision(p["operation"], p["target"], dict(p["arguments"]), rationale="policy adopts the model's proposal")


def run_core(script, outcomes, *, message=MSG, variant="baseline", default=None, limits=None, **kw):
    host = Host(IncidentWorld(variant), limits=limits)
    policy, model = ScriptedDecider(script), FakeHeavyModel(outcomes, default)
    tr = execute_user_turn(message, host=host, decider=policy, context=RuleContextSelector("heuristic"),
                           generator=model, turn_id="C", arm="turnwise_core", **kw).as_json()
    return tr, host, policy, model


def control_rows(tr, owner="scripted"):
    """(step, controller, operation, host validation, executor, result) for each step of a decision-loop trace."""
    rows = []
    for s in tr["steps"]:
        d = s["decision"]
        executor = f"{d['model_tier']}_model" if d["operation"] == "call_model" else "host"
        result = s["observation"]["status"] if s.get("observation") else "final:" + tr["final"]["kind"]
        controller = "decision_policy" if d["provider"] == owner else OWNER.get(d["provider"], d["provider"])
        rows.append((s["step_index"], controller, f"{d['operation']}:{d['target'] or d['model_tier'] or ''}",
                     s["validation"]["status"], executor, result))
    return rows


def native_rows(tr):
    """The same table for the native heavy agent (the controller a handoff transfers to)."""
    rows = []
    for s in tr["steps"]:
        for c in s.get("tool_calls", []):
            rows.append((s["step_index"], OWNER[c["decision"]["provider"]], f"{c['decision']['operation']}:{c['decision']['target']}",
                         c["validation"]["status"], "host", c["observation"]["status"]))
        if not s.get("tool_calls"):
            rows.append((s["step_index"], OWNER[s["decision"]["provider"]], s["decision"]["operation"], "none", "heavy_model",
                         "final:" + tr["final"]["kind"]))
    return rows


class ExistingMechanismTests(unittest.TestCase):
    """What v0.6 already does. These pass before and after this change."""

    def test_predeclared_requires_continuation_returns_control_to_the_policy(self):
        tr, _, policy, _ = run_core([tool("get_error_metrics", service="checkout"), heavy(requires_continuation=True),
                                     tool("get_deployment_history", service="checkout"), heavy()],
                                    [untyped("need deployment history"), untyped("d-142 explains it.")])
        self.assertEqual(len(policy.seen_snapshots), 4)
        self.assertEqual(tr["observations"][1]["status"], "generated")  # untyped free text, no typed proposal
        self.assertEqual(tr["final"]["kind"], "answer")

    def test_untyped_generation_keeps_frozen_v06_semantics(self):
        # Without a typed outcome, a heavy reply that asks for a tool still ends the turn as the answer.
        # This is the frozen v0.6 behaviour, kept unchanged for recorded traces and untyped generators.
        raw = "<tool_call>{\"name\": \"get_deployment_history\", \"arguments\": {\"service\": \"checkout\"}}</tool_call>"
        tr, host, policy, _ = run_core([tool("get_error_metrics", service="checkout"), heavy()], [untyped(raw)])
        self.assertEqual((tr["final"]["kind"], tr["final"]["text"]), ("answer", raw))
        self.assertEqual(len(policy.seen_snapshots), 2)
        self.assertNotIn("model_outcome", tr["steps"][1])
        self.assertNotIn("model_proposals", tr["final"])
        self.assertEqual(host.world.write_ledger, [])


class DiscriminatingSequenceTests(unittest.TestCase):
    """Policy -> read tool -> policy -> heavy -> typed tool proposal -> POLICY -> host -> policy -> heavy -> host-accepted end."""

    def run_sequence(self):
        script = [tool("get_error_metrics", service="checkout"),  # 1. policy selects a read tool
                  heavy(),                                        # 3. policy selects a heavy call (no continuation flag)
                  adopt_latest_proposal,                          # 6. policy, not the model, chooses the next operation
                  heavy()]
        outcomes = [proposal("get_deployment_history", "Need the deployment history before attributing the spike.",
                             service="checkout"),                 # 4. typed proposal requiring more evidence
                    answer("Errors rose 0.4% -> 6.4% at 11:05, three minutes after deploy d-142.")]
        return run_core(script, outcomes)

    def test_control_returns_to_the_policy_after_a_heavy_tool_proposal(self):
        tr, host, policy, model = self.run_sequence()
        self.assertEqual(control_rows(tr), [
            (0, "decision_policy", "call_tool:get_error_metrics", "accepted", "host", "ok"),
            (1, "decision_policy", "call_model:heavy", "accepted", "heavy_model", "tool_proposal"),
            (2, "decision_policy", "call_tool:get_deployment_history", "accepted", "host", "ok"),
            (3, "decision_policy", "call_model:heavy", "accepted", "heavy_model", "final:answer"),
        ])
        self.assertEqual(len(policy.seen_snapshots), 4)   # the policy was asked after EVERY observation
        self.assertEqual(len(model.calls), 2)
        self.assertEqual(tr["totals"]["tool_calls"], 2)
        self.assertEqual(host.world.write_ledger, [])

    def test_policy_sees_the_typed_proposal_and_the_host_executes_only_the_policy_decision(self):
        tr, _, policy, _ = self.run_sequence()
        self.assertIn("tool_proposal", policy.seen_snapshots[2]["observations"][-1])
        self.assertIn("get_deployment_history(service=checkout)", policy.seen_snapshots[2]["observations"][-1])
        self.assertEqual(tr["steps"][1]["model_outcome"]["kind"], "tool_proposal")
        self.assertEqual(tr["observations"][1]["proposal"],
                         {"operation": "call_tool", "target": "get_deployment_history", "arguments": {"service": "checkout"}})
        self.assertEqual(tr["observations"][2]["facts"]["deploys:checkout"]["deploys"][0]["id"], "d-142")
        self.assertEqual(tr["steps"][2]["decision"]["provider"], "scripted")

    def test_termination_is_a_host_accepted_answer_and_the_proposal_is_accounted_for(self):
        tr, _, _, model = self.run_sequence()
        self.assertEqual(tr["final"]["kind"], "answer")
        self.assertIn("typed answer candidate accepted after host action-claim check", tr["final"]["reason"])
        self.assertEqual([(p["proposed_call"]["target"], p["disposition"]) for p in tr["final"]["model_proposals"]],
                         [("get_deployment_history", "executed")])
        # The second heavy prompt carries the host-executed evidence; the proposal itself is never presented as evidence.
        self.assertIn("d-142", model.calls[1]["prompt"])
        self.assertNotIn("d-142", model.calls[0]["prompt"])

    def test_needs_evidence_also_returns_control_and_the_policy_picks_the_tool(self):
        tr, _, policy, _ = run_core([tool("get_error_metrics", service="checkout"), heavy(),
                                     tool("get_deployment_history", service="checkout"), heavy()],
                                    [needs_evidence("I cannot attribute the spike without the deployment history."),
                                     answer("d-142 is the likely cause.")])
        self.assertEqual([r[5] for r in control_rows(tr)], ["ok", "needs_evidence", "ok", "final:answer"])
        self.assertEqual(len(policy.seen_snapshots), 4)
        self.assertNotIn("model_proposals", tr["final"])  # needs_evidence carries no proposed call

    def test_unmodified_rules_policy_also_regains_control(self):
        # The mechanism is policy-agnostic: the v0.6 rules policy (arm B) is asked again after each model outcome.
        host = Host(IncidentWorld())
        model = FakeHeavyModel([("", {"kind": "error"}), proposal("get_config_diff", service="checkout"),
                                answer("d-142 is the likely cause.")])
        tr = execute_user_turn(MSG, host=host, decider=HeuristicDecider(), context=RuleContextSelector("heuristic"),
                               generator=model, turn_id="B").as_json()
        self.assertEqual([r[5] for r in control_rows(tr, owner="rules")],
                         ["ok", "ok", "model_error", "tool_proposal", "final:answer"])
        self.assertEqual({r[1] for r in control_rows(tr, owner="rules")}, {"decision_policy"})
        self.assertEqual(tr["final"]["model_proposals"][0]["disposition"], "not_adopted")  # these rules ignore proposals


class NegativeTests(unittest.TestCase):
    def test_heavy_model_cannot_become_the_controller(self):
        # The model keeps proposing tools. The policy picks something else; nothing the model proposed runs.
        tr, host, policy, _ = run_core(
            [heavy(), tool("get_service_health", service="checkout"), heavy(), Decision("abstain")],
            [proposal("get_config_diff", service="checkout"), proposal("get_service_owner", service="checkout")])
        self.assertEqual({r[1] for r in control_rows(tr)}, {"decision_policy"})
        self.assertEqual(len(policy.seen_snapshots), 4)
        executed = [o["target"] for o in tr["observations"] if o["status"] == "ok"]
        self.assertEqual(executed, ["get_service_health"])
        self.assertEqual([p["disposition"] for p in tr["final"]["model_proposals"]], ["not_adopted", "not_adopted"])
        self.assertEqual(tr["final"]["kind"], "abstain")

    def test_model_proposed_tools_cannot_bypass_host_validation(self):
        script = [heavy(), adopt_latest_proposal, heavy(), adopt_latest_proposal, heavy()]
        tr, host, _, _ = run_core(script, [proposal("delete_database", service="checkout"),
                                           proposal("get_service_health", service="mars"),
                                           answer("I could not verify anything.")])
        self.assertEqual([r[3] for r in control_rows(tr)], ["accepted", "rejected", "accepted", "rejected", "accepted"])
        self.assertEqual(tr["totals"]["tool_calls"], 0)
        self.assertEqual(host.world.write_ledger, [])
        reasons = [p["reason"] for p in tr["final"]["model_proposals"]]
        self.assertIn("unknown capability", reasons[0])
        self.assertIn("not one of", reasons[1])
        self.assertEqual({p["disposition"] for p in tr["final"]["model_proposals"]}, {"rejected_by_host"})

    def test_a_tool_request_never_becomes_an_ungrounded_final_answer(self):
        malformed = [("x", {"kind": "banana"}), ("y", {"kind": "tool_proposal"}),
                     ("z", {"kind": "answer_candidate", "proposed_call": {"operation": "call_tool", "target": "page_oncall",
                                                                           "arguments": {"service": "checkout"}}}),
                     ("", {"kind": "answer_candidate"})]
        for text, outcome in malformed:
            with self.subTest(outcome=outcome):
                tr, _, policy, _ = run_core([heavy(), Decision("abstain")], [(text, outcome)])
                self.assertEqual(tr["observations"][0]["status"], "model_error")
                self.assertEqual(len(policy.seen_snapshots), 2)
                self.assertEqual(tr["final"]["kind"], "abstain")

    def test_unrequested_model_write_is_not_an_approval_hold(self):
        rollback = proposal("rollback_deployment", "Roll it back.", service="checkout")
        # (a) Policy declines the model's write: no hold, the proposal is reported, nothing is written.
        tr, host, _, _ = run_core([tool("get_error_metrics", service="checkout"), heavy(), heavy()],
                                  [rollback, answer("Errors rose after d-142; no action was taken.")])
        self.assertEqual(tr["final"]["kind"], "answer")
        self.assertNotIn("approval_required", [o["status"] for o in tr["observations"]])
        self.assertEqual(tr["final"]["model_proposals"][0]["disposition"], "not_adopted")
        self.assertEqual(host.world.write_ledger, [])
        # (b) Policy naively adopts it: the host still refuses to turn a model-originated write into an approval request.
        tr, host, _, _ = run_core([tool("get_error_metrics", service="checkout"), heavy(), adopt_latest_proposal, heavy()],
                                  [rollback, answer("Errors rose after d-142; no action was taken.")])
        self.assertEqual(tr["steps"][2]["validation"]["status"], "rejected")
        self.assertIn("not_requested", tr["steps"][2]["validation"]["reason"])
        self.assertEqual(tr["final"]["kind"], "answer")
        self.assertNotIn("approval_required", [o["status"] for o in tr["observations"]])
        self.assertEqual(tr["final"]["model_proposals"][0]["disposition"], "rejected_by_host")
        self.assertEqual(host.world.write_ledger, [])

    def test_requested_write_is_still_held_and_proposals_are_never_silently_dropped(self):
        # The user's own request, chosen by the policy: still a visible approval hold (v0.6 host semantics), not executed.
        tr, host, _, _ = run_core([tool("rollback_deployment", service="checkout")], [], message="Roll back checkout.")
        self.assertEqual(tr["final"]["kind"], "approval_required")
        self.assertEqual(host.world.write_ledger, [])
        # A legitimate model proposal left pending when the step budget ends is reported, not lost.
        tr, _, _, _ = run_core([tool("get_error_metrics", service="checkout"), heavy()],
                               [proposal("get_deployment_history", service="checkout")], limits=Limits(max_steps=2))
        self.assertEqual(tr["final"]["kind"], "step_limit")
        self.assertEqual([(p["proposed_call"]["target"], p["disposition"]) for p in tr["final"]["model_proposals"]],
                         [("get_deployment_history", "not_adopted")])

    def test_step_and_token_budgets_bound_a_model_that_never_answers(self):
        limits = Limits(max_steps=5)
        tr, _, policy, model = run_core([heavy()] * 20, [], default=needs_evidence("still missing evidence"), limits=limits)
        self.assertEqual(tr["final"]["kind"], "step_limit")
        self.assertEqual(len(model.calls), limits.max_steps)
        self.assertEqual(len(policy.seen_snapshots), limits.max_steps)
        self.assertEqual({c["max_new_tokens"] for c in model.calls}, {limits.max_generation_tokens["heavy"]})
        self.assertLessEqual(tr["totals"]["generation_completion_tokens"], limits.max_steps * limits.max_generation_tokens["heavy"])


class NativeAgentHandoffContrastTests(unittest.TestCase):
    """Contrast only: after a handoff (arm D) the native heavy agent owns every step. Existing v0.6 code, no new runtime."""

    class FakeNativeLM:
        version, arch = "fake-native-heavy-34", "qwen3_5"

        def __init__(self, replies):
            self.replies = list(replies)

        def extend(self, text, state=None, past_len=0):
            return None, None, past_len + 10

        def assistant_header(self):
            return "<|im_start|>assistant\n"

        def generate_continue(self, text, state, past, max_new_tokens=220):
            return Generation(self.replies.pop(0), 10, 5, 0.0, 0.0, "eos"), None, past + 15

    @staticmethod
    def call(name, **args):
        params = "".join(f"<parameter={k}>\n{v}\n</parameter>\n" for k, v in args.items())
        return f"<tool_call>\n<function={name}>\n{params}</function>\n</tool_call>"

    def test_native_agent_controls_steps_but_unrequested_write_is_rejected_by_shared_host(self):
        lm = self.FakeNativeLM([self.call("get_error_metrics", service="checkout"),
                                self.call("get_deployment_history", service="checkout"),
                                self.call("rollback_deployment", service="checkout"),
                                "d-142 caused it; I requested a rollback."])
        host = Host(IncidentWorld())
        tr = run_heavy_agent(MSG, host=host, lm=lm, turn_id="D").as_json()
        self.assertEqual(native_rows(tr), [
            (0, "native_heavy_agent", "call_tool:get_error_metrics", "accepted", "host", "ok"),
            (1, "native_heavy_agent", "call_tool:get_deployment_history", "accepted", "host", "ok"),
            (2, "native_heavy_agent", "call_tool:rollback_deployment", "rejected", "host", "rejected"),
            (3, "native_heavy_agent", "answer", "none", "heavy_model", "final:answer"),
        ])
        self.assertEqual(tr["totals"]["decision_calls"], 0)  # no policy is consulted after the transfer
        self.assertNotIn("approval_requested", tr["final"])
        self.assertEqual(tr["final"]["denied_write_proposals"][0]["code"], "not_requested")
        self.assertEqual(host.world.write_ledger, [])

    def test_same_model_behaviour_under_turnwise_core_stays_policy_controlled(self):
        tr, host, policy, _ = run_core(
            [tool("get_error_metrics", service="checkout"), heavy(), adopt_latest_proposal, heavy(), heavy()],
            [proposal("get_deployment_history", service="checkout"), proposal("rollback_deployment", service="checkout"),
             answer("d-142 is the likely cause; no action was requested.")])
        self.assertEqual({r[1] for r in control_rows(tr)}, {"decision_policy"})
        self.assertEqual(len(policy.seen_snapshots), 5)
        self.assertNotIn("approval_required", [o["status"] for o in tr["observations"]])
        self.assertEqual([p["disposition"] for p in tr["final"]["model_proposals"]], ["executed", "not_adopted"])
        self.assertEqual(host.world.write_ledger, [])



class P0HostIntegrationTests(unittest.TestCase):
    """Additional #37-specific tests: typed proposals never supersede host intent or action receipts."""

    def test_user_requested_model_write_needs_policy_adoption_and_human_approval(self):
        tr, host, policy, _ = run_core(
            [heavy(), adopt_latest_proposal],
            [proposal("rollback_deployment", service="checkout")],
            message="Roll back checkout.")
        self.assertEqual(len(policy.seen_snapshots), 2)
        self.assertEqual(tr["final"]["kind"], "approval_required")
        self.assertEqual(tr["final"]["action_status"][0]["status"], "held_for_approval")
        self.assertEqual(tr["final"]["model_proposals"][0]["disposition"], "held_for_approval")
        self.assertEqual(tr["final"]["writes_executed"], 0)
        self.assertEqual(host.world.write_ledger, [])

    def test_typed_answer_claiming_unexecuted_write_is_withheld(self):
        tr, host, _, _ = run_core(
            [heavy()], [answer("I rolled checkout back. The deploy has been reverted.")])
        self.assertEqual(tr["final"]["kind"], "abstain")
        self.assertEqual(tr["final"]["reason"], "unsupported_action_claim")
        self.assertTrue(tr["final"]["unsupported_action_claims"])
        self.assertEqual(tr["final"]["writes_executed"], 0)
        self.assertEqual(host.world.write_ledger, [])

    def test_model_needs_evidence_cannot_bypass_host_finish_sufficiency(self):
        tr, _, policy, _ = run_core(
            [heavy(), Decision("finish"), Decision("abstain")],
            [needs_evidence("Please inspect deployment history.")])
        self.assertEqual([s["validation"]["status"] for s in tr["steps"]],
                         ["accepted", "rejected", "accepted"])
        self.assertIn("insufficient evidence", tr["steps"][1]["validation"]["reason"])
        self.assertEqual(len(policy.seen_snapshots), 3)
        self.assertEqual(tr["final"]["kind"], "abstain")

    def test_unresolved_user_action_remains_visible_when_typed_model_never_finishes(self):
        tr, host, _, _ = run_core(
            [heavy(), heavy()],
            [needs_evidence("missing"), needs_evidence("still missing")],
            message="Roll back checkout.", limits=Limits(max_steps=2))
        self.assertEqual(tr["final"]["kind"], "step_limit")
        self.assertEqual(tr["final"]["action_status"][0]["status"], "not_attempted")
        self.assertEqual(tr["final"]["writes_executed"], 0)
        self.assertEqual(host.world.write_ledger, [])



if __name__ == "__main__":
    unittest.main()
