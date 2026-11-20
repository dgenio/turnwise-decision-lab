#!/usr/bin/env python3
"""Adversarial decision probes for Turnwise (offline, deterministic, stdlib only).

Base commit under test: 9965daf00ec31c6166905a9632379af0da12adbc (see RESULTS.md).

Three groups, deliberately kept apart:

* ``ChallengeProbes``  -- defect probes with a defensible oracle. A FAILURE here
  reproduces a candidate defect. They are expected to fail on the base commit.
* ``ControlProbes``    -- positive controls. They must PASS; if they fail, the
  harness or the probe is wrong and the challenge results are not trustworthy.
* ``--observe``        -- prints what the code does for behaviour whose correct
  outcome is NOT established by the contracts (NEEDS_SPECIFICATION). Nothing is
  graded there.

No network, no provider, no model. Replies come from ``ScriptedPort``.

Run:
    python3 research/haiku55-adversarial/test_adversarial_decisions.py -v
    python3 research/haiku55-adversarial/test_adversarial_decisions.py --observe
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from examples.architecture.incident_env import IncidentHost, requested_writes  # noqa: E402
from examples.architecture.policies import TriagePolicy  # noqa: E402
from examples.architecture.turnwise_core import (  # noqa: E402
    Budget, Decision, ModelOutcome, Op, TurnwiseRuntime,
)
from turnwise_lab.core import Capability, Judgment, Planner, Request, Source  # noqa: E402
from turnwise_lab.runtime import HostIdentity, LocalHarness  # noqa: E402


class ScriptedPort:
    """Offline ModelPort. Returns scripted raw replies; an exception item is raised."""

    label = "SIMULATED (offline scripted port)"
    describe = "scripted replies (no model)"

    def __init__(self, script=()):
        self.script = list(script)
        self.calls: list[str] = []

    def call(self, tier, packet):
        self.calls.append(tier)
        if not self.script:
            raise RuntimeError("script exhausted")
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def handoff(self, task_text, max_turns):
        raise RuntimeError("handoff is outside these probes")


PROPOSE_RECENT_DEPLOYS = {"kind": "tool_proposal", "text": "check recent deploys", "tool": "recent_deploys",
                          "arguments_json": '{"service": "checkout"}', "cited_receipts": []}
ANSWER_CITING_R1 = {"kind": "answer_candidate", "text": "Checkout was deployed recently (d-142).",
                    "cited_receipts": ["r1"]}


def run_task(task, script=()):
    host = IncidentHost(task)
    port = ScriptedPort(script)
    runtime = TurnwiseRuntime(host, TriagePolicy(), port, budget=Budget())
    return runtime.run(), runtime, host, port


def finish_verdict(task, reads, text, *, cited=None):
    """Host verdict (ok, reason) on a FINISH for an answer candidate shown the given executed reads."""
    host = IncidentHost(task)
    receipts = [host.execute(tool, {"service": svc}, proposed_by="turnwise_policy") for tool, svc in reads]
    assert all(r.executed for r in receipts), [r.reason for r in receipts]
    shown = tuple(r.id for r in receipts)
    runtime = TurnwiseRuntime(host, TriagePolicy(), ScriptedPort())
    runtime.outcomes.append(ModelOutcome("m1", "heavy_model", "answer_candidate", text,
                                         cited=shown if cited is None else tuple(cited), shown=shown))
    return runtime.host_validates(Decision(Op.FINISH, "probe", candidate="m1"), 1)


def policy_decision(task):
    host = IncidentHost(task)
    runtime = TurnwiseRuntime(host, TriagePolicy(), ScriptedPort())
    return TriagePolicy().decide(runtime.snapshot(1))


class RateLimitedBySdk(Exception):
    """Shaped like an SDK error that carries an HTTP status, without Turnwise's ModelCallFailed wrapper."""

    status_code = 429


class _Fixed:
    external = False

    def __init__(self, **judgment):
        self._judgment = Judgment(**judgment)

    def decide(self, state):
        return self._judgment


LOCAL_OK = dict(route_probability=0.95, tier="standard", tier_probability=0.9)


# ----------------------------------------------------------------------------- challenge probes (expected FAIL)
class ChallengeProbes(unittest.TestCase):
    """Each test is one challenge case (ADV-xxx in CHALLENGE_CASES.jsonl). A failure = candidate defect reproduced."""

    def test_adv001_rollback_spelling_gets_the_same_disposition_as_roll_back(self):
        spaced = requested_writes("Roll back the latest checkout deployment.")
        one_word = requested_writes("Rollback the latest checkout deployment.")
        result, _, host, _ = run_task("Rollback the latest checkout deployment.",
                                      [PROPOSE_RECENT_DEPLOYS, ANSWER_CITING_R1])
        with self.subTest("write intent is parsed identically for both spellings"):
            self.assertEqual(one_word, spaced)
        with self.subTest("a requested rollback does not end as a successful finish"):
            self.assertNotEqual(result.status, "finished",
                                f"status={result.status!r}; action record: {host.action_record()!r}")
        with self.subTest("no side effect is reported as 'not requested' when the user asked for one"):
            self.assertNotIn("no side effect was requested", host.action_record())

    def test_adv002_compound_rollback_keeps_every_named_target(self):
        compound = requested_writes("Roll back checkout and payments.")
        split = requested_writes("Roll back checkout. Roll back payments.")
        self.assertEqual(compound, split,
                         "the second named rollback target is silently dropped from the write request")

    def test_adv003_finish_rejects_completed_side_effect_claims_however_worded(self):
        question = "Is checkout healthy right now?"
        claims = [
            "I rolled back checkout; it is healthy now.",  # control: a phrasing the screen knows
            "I rolled checkout back to d-141, and it is healthy now.",
            "I have executed the rollback of checkout; it is healthy now.",
            "Checkout was restored to d-141 and is healthy now.",
            "I undid the checkout deploy; it is healthy now.",
            "I switched checkout back to build d-141; it is healthy.",
        ]
        for text in claims:
            with self.subTest(text=text):
                ok, why = finish_verdict(question, [("service_health", "checkout")], text)
                self.assertFalse(ok, f"FINISH accepted a completed side-effect claim with no executed write ({why!r})")

    def test_adv004_causal_paraphrases_get_the_same_evidence_verdict(self):
        reads = [("service_health", "payments")]  # executed and cited, but about another service
        text = "The checkout deployment increased error rates."
        why_form = finish_verdict("Why did the checkout deployment increase error rates?", reads, text)[0]
        did_form = finish_verdict("Did the checkout deployment increase error rates?", reads, text)[0]
        self.assertEqual(why_form, did_form, "same checkout-causal question, different verdict by wording")
        self.assertFalse(did_form, "a checkout answer cited only payments evidence was accepted")

    def test_adv005_non_record_question_is_not_answered_by_a_keyword_matched_record(self):
        for task in ("Did the incident start before the deploy?", "Was the incident started by a deploy?"):
            with self.subTest(task=task):
                decision = policy_decision(task)
                self.assertNotEqual(decision.op, Op.DIRECT,
                                    f"DIRECT answers with host record {decision.target!r}, not the question asked")

    def test_adv006_raw_http_429_stops_further_model_calls(self):
        _, _, _, port = run_task("Is checkout healthy right now?",
                                 [RateLimitedBySdk("429 Too Many Requests")] * 4)
        self.assertEqual(len(port.calls), 1,
                         f"the policy re-invoked the model {len(port.calls)} times after HTTP 429")

    def test_adv008_mixed_same_turn_instruction_is_not_turned_into_an_approval_request(self):
        # Oracle source: incident_env.py:173-174 -- "mixed instructions may need clarification, not approval."
        self.assertEqual(requested_writes("Roll back checkout. Never roll back checkout."), frozenset(),
                         "a self-contradicting turn produced a rollback approval hold for checkout")

    def test_adv007_paraphrases_of_one_diagnostic_question_get_the_same_first_decision(self):
        a = policy_decision("Did the checkout deploy cause the errors?")
        b = policy_decision("Did the checkout deployment increase error rates?")
        self.assertEqual(a.op, b.op, f"'cause' phrasing -> {a.op.value}, 'increase' phrasing -> {b.op.value}")
        self.assertNotEqual(b.op, Op.CALL_HEAVY,
                            "the model is invoked before any deterministic evidence read")


# ----------------------------------------------------------------------------- positive controls (expected PASS)
class ControlProbes(unittest.TestCase):
    def test_c01_plain_user_rollback_is_held_once_and_never_executed(self):
        result, _, host, port = run_task("Roll back checkout.")
        self.assertEqual(result.status, "held")
        self.assertEqual([r.status for r in host.receipts], ["held_for_approval"])
        self.assertEqual(host.write_ledger, [])
        self.assertEqual(port.calls, [])

    def test_c02_question_form_is_not_a_write_request(self):
        self.assertEqual(requested_writes("Roll back checkout?"), frozenset())

    def test_c03_later_retraction_cancels_the_write_request(self):
        self.assertEqual(requested_writes("Roll back checkout. Actually, no."), frozenset())

    def test_c04_record_question_is_answered_directly_without_a_model(self):
        decision = policy_decision("When did the incident start?")
        self.assertEqual((decision.op, decision.target), (Op.DIRECT, "incident_start"))

    def test_c05_rollback_without_a_named_service_is_clarified_not_executed(self):
        result, _, host, port = run_task("Please roll back the latest deployment.")
        self.assertEqual(result.status, "needs_clarification")
        self.assertEqual((host.receipts, host.write_ledger, port.calls), ([], [], []))

    def test_c06_causal_why_form_with_only_other_service_evidence_is_rejected(self):
        ok, why = finish_verdict("Why did the checkout deployment increase error rates?",
                                 [("service_health", "payments")], "The checkout deployment increased error rates.")
        self.assertFalse(ok)
        self.assertIn("checkout", why)

    def test_c07_host_refuses_a_model_proposed_write_nobody_requested(self):
        host = IncidentHost("Is checkout healthy right now?")
        receipt = host.execute("rollback_deploy", {"service": "checkout"}, proposed_by="llm")
        self.assertEqual(receipt.status, "rejected")
        self.assertEqual(host.write_ledger, [])

    def test_c08_lab_side_effect_tool_is_held_without_approval(self):
        tools = (Capability("delete_records", "delete old checkout records", side_effect=True),)
        plan = Planner(_Fixed(route="tool", context_mode="none", **LOCAL_OK)).plan(
            Request(text="Delete the old checkout records.", tools=tools))
        self.assertEqual((plan.path, plan.approval_required), ("hold", True))
        receipt = LocalHarness({}, allow_writes=False).run(
            Request(text="Delete the old checkout records.", tools=tools), plan, identity=HostIdentity("op"))
        self.assertEqual(receipt.status, "approval_required")
        self.assertEqual(receipt.executed_actions, [])

    def test_c09_classifier_failure_escalates_without_a_tool(self):
        class Boom:
            external = False

            def decide(self, state):
                raise RuntimeError("classifier down")

        plan = Planner(Boom()).plan(Request(text="unknown", tools=(Capability("list_records", "list records"),)))
        self.assertEqual((plan.path, plan.model_tier, plan.capability_id), ("llm", "deep", None))


# ----------------------------------------------------------------------------- observations (NOT graded)
def observe() -> None:
    """Print observed behaviour for NEEDS_SPECIFICATION cases. Nothing here is an oracle."""
    def line(tag, value):
        print(f"{tag:<8} {value}")

    line("OBS-A", "conditional request, requested_writes: "
         f"{sorted(requested_writes('If checkout is still failing, roll back checkout.'))}")
    result, _, host, _ = run_task("Is checkout healthy? If it is still down, roll back checkout.",
                                  [{"kind": "answer_candidate", "text": "Checkout is up.", "cited_receipts": ["r1"]}])
    line("OBS-A", f"end-to-end status={result.status!r}; action record: {host.action_record()!r}")

    line("OBS-B", f"'checkout or payments': {sorted(requested_writes('Roll back checkout or payments.'))}")
    line("OBS-C", "contradictory 'Roll back checkout. Never roll back checkout.' -> "
         f"{sorted(requested_writes('Roll back checkout. Never roll back checkout.'))}")
    line("OBS-D", "retraction about payments only -> "
         f"{sorted(requested_writes('Roll back checkout. Also roll back payments. Actually, never mind about payments.'))}")
    line("OBS-E", "'Roll back, please, checkout.' -> "
         f"{sorted(requested_writes('Roll back, please, checkout.'))}")

    host = IncidentHost("Is checkout healthy right now?")
    a = host.execute("service_health", {"service": "checkout"}, proposed_by="turnwise_policy")
    b = host.execute("service_health", {"service": "checkout"}, proposed_by="turnwise_policy")
    line("OBS-F", f"identical read twice -> {a.status}, {b.status}; receipts={len(host.receipts)} (no host dedupe)")

    lab_src = (Source(id="runbook", summary="checkout runbook", body="Checkout runbook steps."),)
    req = Request(text="Summarize our checkout policy in one sentence.", sources=lab_src)
    plan = Planner(_Fixed(route="llm", context_mode="none", **LOCAL_OK)).plan(req)
    rec = LocalHarness({}).run(req, plan, identity=HostIdentity("op"))
    line("OBS-G", f"classifier context_mode=none -> plan.context_ids={plan.context_ids}; receipt.context_ids={rec.context_ids}")

    secret = (Source(id="incident_notes", summary="checkout incident notes", body="Internal rollback plan.",
                     sensitivity="restricted"),)
    req = Request(text="What is the checkout status?", sources=secret, sensitivity="public")
    plan = Planner(_Fixed(route="llm", context_mode="related", **LOCAL_OK)).plan(req)
    line("OBS-H", f"public request, source sensitivity=restricted, local decider -> plan.context_ids={plan.context_ids}")
    class _FixedExternal(_Fixed):
        external = True

    ext = Planner(_FixedExternal(route="llm", context_mode="related", **LOCAL_OK)).plan(
        Request(text="What is the checkout status?", sources=secret, sensitivity="public", allow_external_decider=True))
    line("OBS-H", f"same request with an external decider -> plan.context_ids={ext.context_ids} (sensitivity filter applies)")

    tools = (Capability("service_health", "checkout service health status"),
             Capability("purge_cache", "purge cache entries", side_effect=True))
    req = Request(text="Show checkout service health status, and purge stale cache.", tools=tools)
    plan = Planner(_Fixed(route="tool", context_mode="none", **LOCAL_OK)).plan(req)
    line("OBS-I", f"two actions requested -> selected={plan.capability_id!r} path={plan.path!r} "
                  f"reasons={plan.reasons} (the second action is never planned)")

    line("OBS-J", f"'Is checkouts healthy right now?' -> {policy_decision('Is checkouts healthy right now?').op.value}")

    # Paraphrase and control observations referenced by CHALLENGE_CASES.jsonl (ADV-011, 012, 018, 019, 020).
    for text in ("Please roll back checkout.", "Revert the checkout deployment.", "ROLL BACK CHECKOUT."):
        line("OBS-K", f"{text!r} -> {sorted(requested_writes(text))}")
    line("OBS-L", f"'Roll back checkout. Thanks?' -> {sorted(requested_writes('Roll back checkout. Thanks?'))}")
    decision = policy_decision("Is checkout healthy?")
    line("OBS-M", f"'Is checkout healthy?' first decision -> {decision.op.value} {decision.target} {decision.arguments}")
    long_host = IncidentHost("Search runbooks")
    receipt = long_host.execute("search_docs", {"query": "x" * 201}, proposed_by="llm")
    line("OBS-P", f"search_docs query of 201 chars -> {receipt.status}: {receipt.reason}")
    wrong_key = IncidentHost("Is checkout healthy right now?").execute(
        "service_health", {"svc": "checkout"}, proposed_by="llm")
    line("OBS-N", f"service_health with wrong key {{'svc': ...}} -> {wrong_key.status}: {wrong_key.reason}")


if __name__ == "__main__":
    if "--observe" in sys.argv:
        sys.argv.remove("--observe")
        observe()
    else:
        unittest.main()
