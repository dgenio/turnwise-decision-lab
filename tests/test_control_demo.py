"""Turnwise per-step control on the shared world (#49). No optional dependencies, no network.

The central property: a model call is an operation the policy chose, and its output
comes back as an observation. Nothing the model asks for runs until the policy
decides again and the host validates it.
"""
from __future__ import annotations

import contextlib
import io
import json
import unittest

from turnwise_lab.control_demo.__main__ import REQUEST, main
from turnwise_lab.control_demo.model import INVESTIGATION, Answer, IncidentModel, ToolRequest
from turnwise_lab.control_demo.trace import POLICY, render
from turnwise_lab.control_demo.turnwise import RulePolicy, run_turnwise
from turnwise_lab.control_demo.world import CATALOG, SERVICES, Host


def receipt_steps(run):
    """Step index of every host receipt (Turnwise call ids are tw-<step>)."""
    return {int(r["call_id"].split("-")[1]): r for r in run.host_receipts}


class PolicyRegainsControlTests(unittest.TestCase):
    def setUp(self):
        self.run = run_turnwise(REQUEST)

    def test_every_model_observation_returns_control_to_the_policy(self):
        model_steps = [s for s in self.run.steps if s.operation == "call_model"]
        self.assertEqual(len(model_steps), 2)
        for s in model_steps:
            with self.subTest(step=s.index):
                self.assertEqual((s.owner, s.next_controller), (POLICY, POLICY))
                following = self.run.steps[s.index]  # steps are 1-indexed; this is the next one
                self.assertEqual(following.owner, POLICY)
                self.assertIn(following.operation, ("adopt_model_request", "decline_model_request", "finish"))

    def test_a_model_tool_request_is_an_observation_not_an_execution(self):
        receipts = receipt_steps(self.run)
        for s in self.run.steps:
            if s.operation == "call_model":
                self.assertNotIn(s.index, receipts)  # the model step itself executes nothing
                self.assertEqual(s.host_validation, "-")
        request_step = next(s for s in self.run.steps if "tool request get_config_diff" in s.observation)
        adopt_step = self.run.steps[request_step.index]
        self.assertEqual((adopt_step.operation, adopt_step.proposal["tool"]), ("adopt_model_request", "get_config_diff"))
        config = receipts[adopt_step.index]
        self.assertEqual((config["tool"], config["proposer"], config["validation"]),
                         ("get_config_diff", "policy, adopting a model request", "accepted"))

    def test_the_controller_never_passes_to_the_model(self):
        self.assertTrue(all(s.owner == POLICY for s in self.run.steps))
        self.assertTrue(all(s.next_controller in (POLICY, None) for s in self.run.steps))
        self.assertEqual(self.run.steps[-1].operation, "finish")

    def test_policy_gathers_required_evidence_before_spending_a_model_call(self):
        ops = [(s.operation, (s.proposal or {}).get("tool")) for s in self.run.steps]
        self.assertEqual(ops, [("call_tool", "get_error_metrics"), ("call_tool", "get_deployment_history"),
                               ("call_model", None), ("adopt_model_request", "get_config_diff"),
                               ("call_model", None), ("finish", None)])
        self.assertEqual(self.run.model_calls, 2)

    def test_final_answer_is_grounded_in_host_returned_evidence(self):
        self.assertEqual(self.run.final["kind"], "answer")
        self.assertEqual(set(self.run.final["cites"]), {"errors:checkout", "deploys:checkout", "config:checkout"})
        self.assertIn("d-142", self.run.final["text"])
        self.assertEqual(self.run.steps[-1].host_validation, "grounded")


class PolicyDecidesTests(unittest.TestCase):
    def test_unrequested_write_proposal_is_declined_and_never_reaches_the_host(self):
        run = run_turnwise(REQUEST, model=IncidentModel(propose_remediation=True))
        decline = next(s for s in run.steps if s.operation == "decline_model_request")
        self.assertEqual((decline.proposal["tool"], decline.host_validation), ("rollback_deployment", "not_submitted"))
        self.assertNotIn("rollback_deployment", [r["tool"] for r in run.host_receipts])
        self.assertEqual(run.steps[decline.index].operation, "call_model")  # policy decides again: ask for the answer
        self.assertEqual(run.final["kind"], "answer")

    def test_a_policy_that_declines_every_model_request_controls_what_runs(self):
        class DeclineAll(RulePolicy):
            @staticmethod
            def _decide_on_model_request(s, req):
                from turnwise_lab.control_demo.turnwise import Operation
                return Operation("decline_model_request", req.name, req.arguments, "policy under test declines")
        run = run_turnwise(REQUEST, policy=DeclineAll())
        self.assertEqual([r["tool"] for r in run.host_receipts], ["get_error_metrics", "get_deployment_history"])
        # Without config evidence the model cannot cite it, and the host will not accept an uncited answer.
        self.assertEqual((run.final["kind"], run.final["decided_by"]), ("abstain", "host"))

    def test_host_refuses_an_answer_citing_evidence_it_never_returned(self):
        class Overclaims(IncidentModel):
            def respond(self, request, seen):
                return Answer("It was the config change.", ("config:checkout",))
        run = run_turnwise(REQUEST, model=Overclaims())
        self.assertEqual((run.final["kind"], run.steps[-1].host_validation), ("abstain", "ungrounded"))

    def test_model_request_for_another_service_is_declined(self):
        class Wanders(IncidentModel):
            def respond(self, request, seen):
                if "get_config_diff" not in seen:
                    return ToolRequest("get_config_diff", {"service": "payments"})
                return super().respond(request, seen)
        run = run_turnwise(REQUEST, model=Wanders())
        decline = next(s for s in run.steps if s.operation == "decline_model_request")
        self.assertIn("different service", decline.observation)
        self.assertNotIn("payments", json.dumps(run.host_receipts))

    def test_model_call_budget_is_bounded(self):
        class Loops(IncidentModel):
            def respond(self, request, seen):
                return ToolRequest("get_error_metrics", {"service": "checkout"})  # already observed: declined each time
        run = run_turnwise(REQUEST, model=Loops(), max_steps=50)  # only the model-call budget can stop it
        self.assertEqual((run.final["kind"], run.model_calls), ("abstain", 3))
        self.assertIn("model-call budget", run.final["text"])

    def test_unnamed_service_is_clarified_without_any_call(self):
        run = run_turnwise("Why did errors go up?")
        self.assertEqual((run.final["kind"], run.host_receipts, run.model_calls), ("clarify", [], 0))


class SharedWorldTests(unittest.TestCase):
    def test_host_never_executes_a_write_and_validates_arguments(self):
        host = Host()
        self.assertEqual(host.submit("rollback_deployment", {"service": "checkout"}, proposer="t", call_id="1")["status"],
                         "approval_required")
        self.assertEqual(host.submit("get_config_diff", {"service": "nowhere"}, proposer="t", call_id="2")["status"], "rejected")
        self.assertEqual(host.submit("delete_everything", {"service": "checkout"}, proposer="t", call_id="3")["status"],
                         "rejected")
        self.assertEqual(host.submit("get_config_diff", {"service": "checkout", "approved": True}, proposer="t",
                                     call_id="4")["status"], "rejected")
        self.assertEqual((host.writes_executed, host.observed_fact_keys()), (0, set()))

    def test_principal_without_read_permission_cannot_read(self):
        host = Host(permissions=frozenset())
        self.assertEqual(host.submit("get_error_metrics", {"service": "checkout"}, proposer="t", call_id="1")["status"],
                         "rejected")

    def test_one_catalog_one_schema(self):
        self.assertEqual(len({t.name for t in CATALOG}), len(CATALOG))
        for t in CATALOG:
            self.assertEqual(t.json_schema()["properties"]["service"]["enum"], list(SERVICES))
        self.assertEqual([t.name for t in CATALOG if t.side_effect], ["rollback_deployment"])
        self.assertTrue(set(INVESTIGATION) <= {t.name for t in CATALOG})

    def test_runs_are_deterministic(self):
        self.assertEqual(run_turnwise(REQUEST).as_json(), run_turnwise(REQUEST).as_json())

    def test_cli_runs_without_optional_frameworks_and_renders_the_trace(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main([]), 0)
        self.assertIn("== Turnwise per-step policy", out.getvalue())
        self.assertIn("adopt_model_request", out.getvalue())
        self.assertIn("turnwise policy", render(run_turnwise(REQUEST)))



class DocumentationTests(unittest.TestCase):
    def test_documented_turnwise_trace_is_the_real_output(self):
        from pathlib import Path
        doc = (Path(__file__).resolve().parents[1] / "docs" / "same-task-native-vs-turnwise.md").read_text(encoding="utf-8")
        self.assertIn(render(run_turnwise(REQUEST)), doc)

if __name__ == "__main__":
    unittest.main()
