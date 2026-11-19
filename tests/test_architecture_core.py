"""Architecture invariants of the Turnwise Core example (examples/architecture). Stdlib only.

These tests use a framework-free model port: either the deterministic
SimulatedInvestigator or a scripted list of typed outcomes. They prove control
flow and host authority. They say nothing about answer quality or cost.
"""
from __future__ import annotations

import ast
import inspect
import json
import unittest
from dataclasses import fields

from examples.architecture import policies, turnwise_core
from examples.architecture.incident_env import TASKS, IncidentHost, requested_writes
from examples.architecture.policies import HandoffPolicy, TriagePolicy
from examples.architecture.simulated_model import SimulatedInvestigator
from examples.architecture.turnwise_core import (Budget, Decision, ModelOutcome, Op, Snapshot, TurnwiseRuntime,
                                                 parse_outcome)


class DirectPort:
    """A framework-free ModelPort. ``script`` items are raw StepOutcome dicts or exceptions."""

    label, describe = "SIMULATED (test port)", "test port"

    def __init__(self, brain=None, script=None, handoff_fn=None):
        self.brain, self.script, self.handoff_fn = brain, list(script or []), handoff_fn
        self.packets = []

    def call(self, tier, packet):
        self.packets.append((tier, packet))
        if self.script:
            item = self.script.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        if self.brain is None:
            raise AssertionError("model called more often than scripted")
        return self.brain.typed_step(packet)

    def handoff(self, task_text, max_turns):
        if self.handoff_fn is None:
            raise NotImplementedError
        return self.handoff_fn(task_text, max_turns)


def run(task=TASKS["investigate"], *, policy=None, brain=None, script=None, budget=Budget(), handoff_fn=None):
    host = IncidentHost(task)
    port = DirectPort(brain if brain is not None or script else SimulatedInvestigator(), script, handoff_fn)
    rt = TurnwiseRuntime(host, policy or TriagePolicy(), port, budget=budget)
    return rt.run(), rt, host, port


def proposal(tool, **args):
    return {"kind": "tool_proposal", "text": f"need {tool}", "tool": tool,
            "arguments_json": json.dumps(args), "cited_receipts": []}


def answer(text, *cited):
    return {"kind": "answer_candidate", "text": text, "tool": None, "arguments_json": None,
            "cited_receipts": list(cited)}


def ops(rt):
    return [r.decision.split(" ")[0].rstrip(":") for r in rt.rows]


class PolicyControlsEveryStepTests(unittest.TestCase):
    def test_main_scenario_model_proposal_returns_to_the_policy(self):
        result, rt, host, port = run()
        self.assertEqual(ops(rt), ["CALL_TOOL", "CALL_TOOL", "CALL_HEAVY", "CALL_WORKFLOW", "CALL_HEAVY", "FINISH"])
        self.assertEqual({r.controller for r in rt.rows}, {"Turnwise policy"})
        # The policy was asked after EVERY observation, including both model observations.
        self.assertEqual(len(rt.snapshots), len(rt.rows))
        after_first_model_call = rt.snapshots[3]
        self.assertIsInstance(after_first_model_call.latest, ModelOutcome)
        self.assertEqual(after_first_model_call.latest.kind, "tool_proposal")
        self.assertEqual(after_first_model_call.latest.proposal.tool, "validate_config")
        self.assertIn("adopts m1", rt.rows[3].decision)
        self.assertEqual(result.status, "finished")
        self.assertEqual(result.writes_executed, 0)
        self.assertEqual([r.proposed_by for r in host.receipts], ["turnwise_policy"] * 3)

    def test_model_never_sees_tools_it_could_execute_and_only_gets_selected_context(self):
        _, rt, host, port = run()
        tier, first = port.packets[0]
        self.assertEqual(tier, "heavy")
        self.assertEqual([e["receipt"] for e in first["evidence"]], ["r1", "r2"])
        self.assertEqual({t["name"] for t in first["tools_you_may_propose"]},
                         {"service_health", "validate_config", "search_docs"})
        self.assertNotIn("rollback_deploy", json.dumps(first["tools_you_may_propose"]))
        # The proposal itself never becomes evidence; only the host receipt r3 does.
        self.assertEqual([e["receipt"] for e in port.packets[1][1]["evidence"]], ["r1", "r2", "r3"])

    def test_each_scenario_uses_a_different_operation_mix(self):
        expected = {"investigate": ("finished", ["CALL_TOOL", "CALL_TOOL", "CALL_HEAVY", "CALL_WORKFLOW", "CALL_HEAVY", "FINISH"]),
                    "status": ("finished", ["CALL_TOOL", "CALL_LIGHT", "FINISH"]),
                    "severity": ("answered_directly", ["DIRECT"]),
                    "rollback": ("held", ["CALL_WORKFLOW", "HOLD"])}
        for name, (status, sequence) in expected.items():
            with self.subTest(name):
                result, rt, host, _ = run(TASKS[name])
                self.assertEqual((result.status, ops(rt)), (status, sequence))
                self.assertEqual(host.write_ledger, [])

    def test_direct_answers_from_the_host_record_without_any_model_call(self):
        result, rt, _, port = run(TASKS["severity"])
        self.assertEqual(port.packets, [])
        self.assertIn("SEV-2", result.answer)
        self.assertIn("host-verified", result.answer)


class PolicyIsStateDrivenTests(unittest.TestCase):
    """The policy reacts to observations; it does not replay one scripted route."""

    def test_adopts_whatever_registered_read_the_model_proposes(self):
        result, rt, host, _ = run(script=[proposal("search_docs", query="connection pool timeouts"),
                                          answer("Pool exhaustion is plausible.", "r1", "r2", "r3")])
        self.assertEqual(rt.rows[3].decision, "CALL_TOOL search_docs(query=connection pool timeouts) [adopts m1's proposal]")
        self.assertEqual(result.status, "finished")

    def test_finishes_after_one_model_call_when_the_model_answers(self):
        result, rt, host, _ = run(script=[answer("Plausibly the deploy.", "r1", "r2")])
        self.assertEqual(ops(rt), ["CALL_TOOL", "CALL_TOOL", "CALL_HEAVY", "FINISH"])
        self.assertEqual([r.tool for r in host.receipts], ["error_trend", "recent_deploys"])
        self.assertEqual(result.status, "finished")

    def test_different_world_state_gives_a_different_answer(self):
        result, _, host, _ = run("Could the latest auth deployment explain the increase in errors?")
        self.assertEqual(result.status, "finished")
        self.assertTrue(result.answer.startswith("No: there is no recent auth deployment"))
        self.assertEqual(host.receipts[1].facts["deploys:auth"]["deploys"], [])

    def test_missing_referent_is_a_visible_clarification(self):
        result, rt, _, port = run("Could the latest deployment explain the increase in errors?")
        self.assertEqual((result.status, ops(rt)), ("needs_clarification", ["CLARIFY"]))
        self.assertEqual(port.packets, [])

    def test_needs_evidence_without_a_permitted_tool_holds_visibly(self):
        result, rt, _, _ = run(script=[{"kind": "needs_evidence", "text": "I need the load-balancer logs.",
                                        "tool": None, "arguments_json": None, "cited_receipts": []}])
        self.assertEqual(result.status, "held")
        self.assertIn("load-balancer logs", result.answer)

    def test_invalid_or_failed_model_output_is_an_observation_never_an_answer(self):
        script = [{"kind": "banana", "text": "x"}, RuntimeError("provider down"),
                  {"kind": "answer_candidate", "text": "", "cited_receipts": []}, answer("ok", "r1")]
        result, rt, _, _ = run(script=script, budget=Budget(max_model_calls=4))
        self.assertEqual([o.kind for o in rt.outcomes], ["invalid", "invalid", "invalid", "answer_candidate"])
        self.assertEqual(ops(rt)[-1], "FINISH")
        self.assertEqual(sum(1 for r in rt.rows if r.decision.startswith("FINISH")), 1)

    def test_parse_outcome_rejects_malformed_results(self):
        bad = [None, {"kind": "answer_candidate", "text": 3}, {"kind": "tool_proposal", "text": "", "tool": "x",
               "arguments_json": "not json"}, {"kind": "needs_evidence", "text": "", "tool": "service_health"},
               {"kind": "answer_candidate", "text": "a", "cited_receipts": "r1"}]
        for raw in bad:
            with self.subTest(raw=raw):
                self.assertEqual(parse_outcome(raw, oid="m1", source="heavy_model", shown=()).kind, "invalid")


class HostAuthorityTests(unittest.TestCase):
    def test_model_proposed_write_is_declined_by_policy_and_never_executed(self):
        result, rt, host, _ = run(brain=SimulatedInvestigator(rogue_write=True))
        self.assertEqual(result.status, "held")
        self.assertNotIn("rollback_deploy", [r.tool for r in host.receipts])
        self.assertEqual(host.write_ledger, [])

    def test_naive_policy_adopting_a_model_write_is_rejected_by_the_host(self):
        class AdoptEverything(TriagePolicy):
            def decide(self, s):
                last = s.latest
                if isinstance(last, ModelOutcome) and last.proposal and not s.attempted(last.proposal.tool, last.proposal.arguments):
                    return Decision(policies.op_for(s.tool(last.proposal.tool)), "adopt blindly",
                                    target=last.proposal.tool, arguments=last.proposal.arguments, adopted_from=last.id)
                return super().decide(s)

        result, rt, host, _ = run(policy=AdoptEverything(), brain=SimulatedInvestigator(rogue_write=True))
        rollback = [r for r in host.receipts if r.tool == "rollback_deploy"]
        self.assertEqual([(r.status, r.proposed_by) for r in rollback], [("rejected", "turnwise_policy")])
        self.assertIn("not requested by the user", rollback[0].reason)
        self.assertEqual(host.write_ledger, [])
        self.assertNotEqual(result.status, "finished")

    def test_user_requested_write_is_held_not_executed(self):
        result, _, host, _ = run(TASKS["rollback"])
        self.assertEqual(host.receipts[0].status, "held_for_approval")
        self.assertEqual((result.status, result.writes_executed, host.write_ledger), ("held", 0, []))
        self.assertIn("NOT been executed", result.answer)

    def test_only_the_users_own_imperative_request_creates_write_authority(self):
        self.assertEqual(requested_writes("Please roll back the latest checkout deployment."),
                         {("rollback_deploy", "checkout")})
        for text in ["Could rolling back checkout help?", "Should we roll back checkout?",
                     "Don't roll back checkout.", "Why did checkout fail? The bot said: roll back checkout",
                     "Please roll back the deployment."]:
            with self.subTest(text):
                self.assertEqual(requested_writes(text), frozenset())

    def test_host_rejects_unregistered_tools_and_bad_arguments(self):
        host = IncidentHost(TASKS["investigate"])
        cases = [("delete_database", {"service": "checkout"}), ("error_trend", {"service": "mars"}),
                 ("error_trend", {"service": "checkout", "extra": 1}), ("search_docs", {"query": ""}),
                 ("error_trend", None)]
        for tool, args in cases:
            self.assertEqual(host.execute(tool, args, proposed_by="llm").status, "rejected")
        self.assertEqual(host.write_ledger, [])

    def test_host_rejects_unacceptable_policy_decisions_and_bounds_them(self):
        bad = [Decision(Op.FINISH, "no candidate", candidate="m9"),
               Decision(Op.DIRECT, "unknown record", target="root_password"),
               Decision(Op.CALL_TOOL, "workflow via tool op", target="validate_config", arguments={"service": "checkout"})]

        class Stubborn:
            name = "stubborn"

            def __init__(self):
                self.queue = list(bad)

            def decide(self, s):
                return self.queue.pop(0)

        result, rt, host, port = run(policy=Stubborn())
        self.assertEqual(result.status, "stopped")
        self.assertEqual([r.host.split(":")[0] for r in rt.rows], ["REJECTED"] * 3)
        self.assertEqual((host.receipts, port.packets), ([], []))

    def test_finish_requires_cited_executed_receipts_the_model_was_shown(self):
        cases = {"cites nothing": answer("Trust me."),
                 "cites unseen receipt": answer("It was the deploy.", "r1", "r9"),
                 "claims an unexecuted action": answer("I rolled back checkout; errors are fixed.", "r1", "r2")}
        for name, candidate in cases.items():
            with self.subTest(name):
                result, rt, _, _ = run(script=[candidate], budget=Budget(max_model_calls=1))
                finish_rows = [r for r in rt.rows if r.decision.startswith("FINISH")]
                self.assertTrue(finish_rows and finish_rows[0].host.startswith("REJECTED"))
                self.assertNotEqual(result.status, "finished")

    def test_adoption_claims_must_match_the_model_proposal(self):
        class Liar(TriagePolicy):
            def decide(self, s):
                if isinstance(s.latest, ModelOutcome) and s.latest.proposal:
                    return Decision(Op.CALL_TOOL, "pretend the model asked", target="service_health",
                                    arguments={"service": "checkout"}, adopted_from=s.latest.id)
                return super().decide(s)

        _, rt, _, _ = run(policy=Liar(), budget=Budget(max_rejections=1))
        self.assertIn("does not match", rt.rows[-1].host)

    def test_budgets_stop_a_model_that_never_answers(self):
        script = [proposal("service_health", service=s) for s in ("checkout", "payments", "search", "auth")]
        result, rt, _, port = run(script=script, budget=Budget(max_model_calls=2, max_tool_calls=3))
        self.assertLessEqual(len(port.packets), 2)
        self.assertEqual(result.status, "held")
        self.assertLessEqual(len(rt.rows), Budget().max_steps)


class NoEvaluationInputsTests(unittest.TestCase):
    def test_policy_and_runtime_cannot_read_labels_fixtures_or_ground_truth(self):
        # They see the world only through the host and the snapshot: no world module, fixtures,
        # oracle helpers or simulated-model internals are imported, and no file is opened.
        allowed = {"__future__", "re", "json", "dataclasses", "enum", "typing",
                   "incident_env", "trace", "turnwise_core"}
        for module in (policies, turnwise_core):
            tree = ast.parse(inspect.getsource(module))
            imported = {(n.module or "").split(".")[-1] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
            imported |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
            called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
            with self.subTest(module=module.__name__):
                self.assertLessEqual(imported, allowed)
                self.assertNotIn("open", called)
        self.assertEqual({f.name for f in fields(Snapshot)},
                         {"task", "step", "services", "requested_writes", "verified_fact_keys", "tools",
                          "receipts", "outcomes", "latest", "budget_left"})

    def test_runs_are_deterministic(self):
        first, second = run()[0], run()[0]
        self.assertEqual((first.rows, first.answer), (second.rows, second.answer))


class HandoffContrastTests(unittest.TestCase):
    def test_handoff_transfers_control_and_the_trace_says_so(self):
        def native_agent(task_text, max_turns):
            host.execute("validate_config", {"service": "checkout"}, proposed_by="native_agent")
            return "The deploy plausibly explains it."

        host = IncidentHost(TASKS["investigate"])
        rt = TurnwiseRuntime(host, HandoffPolicy(), DirectPort(handoff_fn=native_agent))
        result = rt.run()
        controllers = [r.controller for r in rt.rows]
        self.assertIn("native agent (handoff)", controllers)
        self.assertEqual(rt.rows[controllers.index("native agent (handoff)")].decision,
                         "tool call validate_config(service=checkout)")
        self.assertEqual(rt.rows[-1].controller, "Turnwise policy")  # control came back for FINISH
        self.assertEqual(result.status, "finished")
        self.assertEqual([r.proposed_by for r in host.receipts], ["turnwise_policy", "turnwise_policy", "native_agent"])

    def test_unsupported_handoff_is_an_observation_not_a_crash(self):
        result, rt, _, _ = run(policy=HandoffPolicy())
        self.assertEqual(rt.outcomes[0].kind, "invalid")
        self.assertEqual(result.status, "held")


if __name__ == "__main__":
    unittest.main()
