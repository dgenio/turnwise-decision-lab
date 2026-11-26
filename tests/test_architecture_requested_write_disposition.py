"""#13: every write the user requested ends with a host-stated disposition, at every way a run can end.

``DIRECT`` and ``FINISH`` already refuse to end a run while a user-requested write has no host
disposition (#72). ``HOLD``, ``CLARIFY`` and the host's own stops (rejection limit, step budget)
did not: a run could end with the request neither submitted nor named, and the host action
record said "no side effect was requested or executed" although the user had requested one.
These tests pin the repair. Developer regressions on the canonical ``examples/architecture`` host,
not benchmark evidence; stdlib only, so they run in the main CI job.
"""
from __future__ import annotations

import unittest

from examples.architecture.incident_env import TASKS, IncidentHost
from examples.architecture.policies import TriagePolicy
from examples.architecture.simulated_model import SimulatedInvestigator
from examples.architecture.turnwise_core import Budget, Decision, Op, TurnwiseRuntime

ROLLBACK = TASKS["rollback"]  # "Please roll back the latest checkout deployment."
CALL = "rollback_deploy(service=checkout)"
NOTHING_REQUESTED = "no side effect was requested or executed"


class ScriptedPort:
    label, describe = "SIMULATED (test)", "test double"

    def __init__(self, *outputs):
        self.outputs, self.calls = list(outputs), 0

    def call(self, tier, packet):
        self.calls += 1
        return self.outputs.pop(0) if self.outputs else {"kind": "needs_evidence", "text": "nothing more"}

    def handoff(self, task_text, max_turns):
        raise NotImplementedError


class SimulatedPort(ScriptedPort):
    def __init__(self):
        super().__init__()
        self.brain = SimulatedInvestigator()

    def call(self, tier, packet):
        self.calls += 1
        return self.brain.typed_step(packet)


class Script:
    name = "scripted policy (test)"

    def __init__(self, decide):
        self.decide = decide


def run(task, decide, port=None, budget=Budget()):
    host = IncidentHost(task)
    return TurnwiseRuntime(host, Script(decide), port or ScriptedPort(), budget=budget).run(), host


def record(result) -> str:
    return next(n for n in result.notes if n.startswith("host action record"))


class UnsubmittedRequestedWrite(unittest.TestCase):
    def assert_named_as_unsubmitted(self, result, host):
        self.assertEqual(host.requested_writes, {("rollback_deploy", "checkout")})
        self.assertFalse(any(r.tool == "rollback_deploy" for r in host.receipts))
        self.assertIn(CALL, result.answer)
        self.assertIn("not submitted", result.answer)
        self.assertNotIn(NOTHING_REQUESTED, record(result))
        self.assertIn(f"{CALL} REQUESTED BY THE USER, NOT SUBMITTED", record(result))
        self.assertEqual(result.writes_executed, 0)

    def test_hold_after_a_text_only_escalation_names_the_request(self):
        def decide(s):
            if not s.outcomes:
                return Decision(Op.CALL_HEAVY, "uncertain; escalate", context=(), may_propose=())
            return Decision(Op.HOLD, "stop", message="Stopping here.")
        result, host = run(ROLLBACK, decide, ScriptedPort({"kind": "needs_evidence", "text": "cannot propose tools"}))
        self.assertEqual(result.status, "held")
        self.assertTrue(result.answer.startswith("Stopping here."))  # the policy's message is kept, not rewritten
        self.assert_named_as_unsubmitted(result, host)

    def test_clarify_names_the_request(self):
        result, host = run(ROLLBACK, lambda s: Decision(Op.CLARIFY, "ask", message="Which deployment do you mean?"))
        self.assertEqual(result.status, "needs_clarification")
        self.assert_named_as_unsubmitted(result, host)

    def test_stop_after_repeated_rejections_names_the_request(self):
        task = "Please roll back the latest checkout deployment. Is checkout healthy right now?"

        def decide(s):
            if not s.receipts:
                return Decision(Op.CALL_TOOL, "read", "service_health", {"service": "checkout"})
            if not s.outcomes:
                return Decision(Op.CALL_HEAVY, "reason", context=(s.receipts[0].id,))
            return Decision(Op.FINISH, "finish", candidate=s.outcomes[-1].id)  # refused: a write is outstanding
        result, host = run(task, decide, ScriptedPort(
            {"kind": "answer_candidate", "text": "Checkout is degraded.", "cited_receipts": ["r1"]}))
        self.assertEqual(result.status, "stopped")
        self.assert_named_as_unsubmitted(result, host)

    def test_step_budget_stop_names_the_request(self):
        result, host = run(ROLLBACK, lambda s: Decision(Op.CALL_TOOL, "read", "service_health", {"service": "checkout"}),
                           budget=Budget(max_steps=2, max_tool_calls=6))
        self.assertEqual(result.status, "stopped")
        self.assert_named_as_unsubmitted(result, host)

    def test_a_write_submitted_for_another_service_does_not_dispose_of_the_request(self):
        def decide(s):
            if not s.receipts:
                return Decision(Op.CALL_WORKFLOW, "wrong target", "rollback_deploy", {"service": "payments"})
            return Decision(Op.HOLD, "stop", message="Stopping here.")
        result, host = run(ROLLBACK, decide)
        self.assertEqual([(r.tool, r.arguments, r.status) for r in host.receipts],
                         [("rollback_deploy", {"service": "payments"}, "rejected")])
        self.assertIn(CALL, result.answer)
        self.assertIn(f"{CALL} REQUESTED BY THE USER, NOT SUBMITTED", record(result))
        self.assertIn("rollback_deploy(service=payments) REJECTED", record(result))


class DisposedOrAbsentRequests(unittest.TestCase):
    def test_a_held_request_is_reported_as_held_only(self):
        host = IncidentHost(ROLLBACK)
        result = TurnwiseRuntime(host, TriagePolicy(), SimulatedPort()).run()
        self.assertEqual(result.status, "held")
        self.assertIn(f"{CALL} HELD_FOR_APPROVAL", record(result))
        self.assertNotIn("NOT SUBMITTED", record(result))
        self.assertNotIn("not submitted", result.answer)

    def test_runs_without_a_requested_write_are_unchanged(self):
        for name in ("investigate", "status", "severity"):
            with self.subTest(task=name):
                host = IncidentHost(TASKS[name])
                result = TurnwiseRuntime(host, TriagePolicy(), SimulatedPort()).run()
                self.assertEqual(record(result), f"host action record: {NOTHING_REQUESTED}")
                self.assertNotIn("not submitted", result.answer)

    def test_a_retracted_request_is_still_reported_as_not_requested(self):
        host = IncidentHost("Roll back checkout. Actually, don't.")
        result = TurnwiseRuntime(host, TriagePolicy(), SimulatedPort()).run()
        self.assertEqual(host.requested_writes, frozenset())
        self.assertIn("NOT REQUESTED", record(result))
        self.assertNotIn("NOT SUBMITTED", record(result))


if __name__ == "__main__":
    unittest.main()
