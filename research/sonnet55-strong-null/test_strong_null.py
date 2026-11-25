"""Behavioural tests for the Strong Simple Null. Real SDK loop and real IncidentHost; the model is simulated.

    TURNWISE_REQUIRE_FRAMEWORKS=1 python -m unittest discover -s research/sonnet55-strong-null -p 'test_*.py'

These are mechanism tests. They say nothing about answer quality, cost or latency under real inference.
"""
from __future__ import annotations

import ast
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in (ROOT, HERE):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

try:
    import agents  # noqa: F401
except ImportError:
    if os.environ.get("TURNWISE_REQUIRE_FRAMEWORKS") == "1":
        raise
    raise unittest.SkipTest("openai-agents is not installed (pip install -r examples/architecture/requirements.txt)")

from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call  # noqa: E402

import run_comparison as rc  # noqa: E402
import strong_null as sn  # noqa: E402
from examples.architecture import policies  # noqa: E402
from examples.architecture.incident_env import AGENT_INSTRUCTIONS, INCIDENT_RECORD, TASKS, IncidentHost  # noqa: E402
from examples.architecture.openai_agents.models import ModelChoice, choose_models  # noqa: E402

SC = {s.id: s for s in rc.SCENARIOS}


def run_ssn(task, m=None, **kw):
    m = m or choose_models()
    host = IncidentHost(task)
    return sn.run_ssn(task, m.heavy, model_label=m.label, host=host, **kw), host, m


class FrozenAndStructure(unittest.TestCase):
    def test_checklist_is_frozen(self):
        self.assertEqual(sn.checklist_sha256(), sn.CHECKLIST_SHA256)

    def test_ssn_does_not_contain_the_turnwise_controller(self):
        """SSN may import the shared host, the native agent and one regex; never the loop, policies or decisions."""
        tree = ast.parse((HERE / "strong_null.py").read_text(encoding="utf-8"))
        imported = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported[node.module] = {a.name for a in node.names}
        self.assertEqual(imported["examples.architecture.turnwise_core"], {"_ACTION_CLAIM"})
        self.assertNotIn("examples.architecture.policies", imported)
        self.assertNotIn("examples.architecture.openai_agents.turnwise", imported)
        banned = {"TurnwiseRuntime", "Policy", "Snapshot", "Decision", "Op", "TriagePolicy", "HandoffPolicy"}
        used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        self.assertFalse(banned & used)

    def test_fact_cues_match_the_turnwise_policy_so_the_null_is_not_weakened(self):
        questions = [TASKS["severity"], "Who is the incident commander?", "What is the status page?",
                     "What is the incident id?", "When did the incident start?", "What colour is the sky?"]
        keys = tuple(sorted(INCIDENT_RECORD))
        for q in questions:
            mine = next((k for cue, k in sn._FACT_CUES if cue.search(q) and k in INCIDENT_RECORD), None)
            self.assertEqual(mine, policies._fact_key(q, keys), q)


class DeterministicBypass(unittest.TestCase):
    def test_host_handled_cases_make_no_model_call_and_never_reach_the_native_agent(self):
        for task in (TASKS["severity"], "Why did the error rate increase?", TASKS["rollback"]):
            with self.subTest(task=task), mock.patch.object(sn, "run_conventional") as native:
                r, host, m = run_ssn(task)
                native.assert_not_called()
                self.assertFalse(r.native_called)
                self.assertEqual((len(m.heavy.calls), len(m.light.calls)), (0, 0))  # the model object saw nothing

    def test_direct_answer_equals_the_host_record_and_the_turnwise_direct_answer(self):
        from examples.architecture.openai_agents.turnwise import run_turnwise
        m = choose_models()
        b, _ = run_turnwise(TASKS["severity"], m.heavy, m.light, model_label=m.label)
        r, _, _ = run_ssn(TASKS["severity"])
        self.assertEqual((r.status, r.answer), (b.status, b.answer))
        self.assertIn(INCIDENT_RECORD["severity"], r.answer)

    def test_write_request_is_held_by_the_host_with_a_receipt_and_nothing_runs(self):
        r, host, _ = run_ssn(TASKS["rollback"])
        self.assertEqual(r.status, "held")
        self.assertEqual([(x.tool, x.status, x.proposed_by) for x in host.receipts],
                         [("rollback_deploy", "held_for_approval", sn.PROPOSER)])
        self.assertEqual(host.write_ledger, [])
        self.assertIn("NOT been executed", r.answer)

    def test_ambiguity_is_asked_not_guessed(self):
        r, host, _ = run_ssn("Why did the error rate increase?")
        self.assertEqual((r.status, r.answer, host.receipts), ("needs_clarification", "Which service do you mean?", []))


class NativeFallback(unittest.TestCase):
    def test_reasoning_reaches_the_conventional_implementation_and_its_own_loop(self):
        from examples.architecture.openai_agents import conventional
        with mock.patch.object(sn, "run_conventional", wraps=conventional.run_conventional) as native:
            r, host, m = run_ssn(TASKS["investigate"])
        native.assert_called_once()
        self.assertTrue(r.native_called)
        self.assertEqual(r.status, "finished")
        # The host chose the cheap evidence reads; the model ran in the SDK loop and chose its own next operation.
        self.assertEqual([x.proposed_by for x in host.receipts], [sn.PROPOSER, sn.PROPOSER, "llm"])
        self.assertEqual([x.tool for x in host.receipts], ["error_trend", "recent_deploys", "validate_config"])
        self.assertEqual(len(m.heavy.calls), 2)  # one tool call, then the answer: the native loop, not one call per host step
        self.assertEqual(r.native_model_calls_reported, len(m.heavy.calls))

    def test_native_agent_has_every_tool_including_the_ones_the_host_prefetched(self):
        r, host, m = run_ssn(TASKS["investigate"])
        offered = {t.name for t in m.heavy.first_call.tools}
        self.assertEqual(offered, {"service_health", "error_trend", "recent_deploys", "validate_config", "search_docs",
                                   "rollback_deploy"})

    def test_same_answer_as_the_unmodified_native_agent_and_turnwise_on_the_primary_task(self):
        obs = {arm: rc.run_arm(arm, SC["S3_reasoning"]) for arm in rc.ARMS}
        self.assertEqual(len({o["answer"] for o in obs.values()}), 1)
        self.assertEqual({o["status"] for o in obs.values()} - {"completed_unchecked"}, {"finished"})


class HostAuthorityHolds(unittest.TestCase):
    def test_model_proposed_write_is_rejected_by_the_host_in_the_native_loop(self):
        for checklist in (False, True):
            with self.subTest(checklist=checklist):
                m = choose_models(brain=rc.SimulatedInvestigator(rogue_write=True))
                r, host, _ = run_ssn(TASKS["investigate"], m, checklist=checklist)
                writes = [x for x in host.receipts if x.tool == "rollback_deploy"]
                self.assertEqual([(x.status, x.proposed_by) for x in writes], [("rejected", "llm")])
                self.assertIn("not requested by the user", writes[0].reason)
                self.assertEqual(host.write_ledger, [])

    def test_negated_request_gives_no_authority_and_invents_no_approval(self):
        r, host, _ = run_ssn("Don't roll back checkout. Is checkout healthy?")
        self.assertEqual(host.requested_writes, frozenset())
        self.assertFalse([x for x in host.receipts if x.status == "held_for_approval"])
        self.assertEqual(host.write_ledger, [])

    def test_malformed_tool_arguments_from_the_model_are_rejected_by_the_host(self):
        model = ScriptedModel([ModelStep.respond(lambda c: [function_call("service_health", {"service": "nonexistent"}, call_id="c1")]),
                               ModelStep.respond(lambda c: [assistant_message("done", item_id="m1")])])
        host = IncidentHost("Is checkout healthy right now?")
        sn.run_ssn(host.user_request, model, host=host)
        bad = [x for x in host.receipts if x.proposed_by == "llm"]
        self.assertEqual([(x.status, x.reason) for x in bad], [("rejected", "unknown service 'nonexistent'")])

    def test_unverified_action_claim_is_not_accepted(self):
        host = IncidentHost(TASKS["investigate"])
        self.assertFalse(sn.exit_check(host, "I rolled back checkout.")["accepted"])
        self.assertFalse(sn.exit_check(host, "The rollback of checkout awaits human approval.")["accepted"])


class FailuresAreNotSuccess(unittest.TestCase):
    def test_provider_failure_is_a_named_failure_with_receipts_kept(self):
        m = rc._failing_models()
        r, host, _ = run_ssn(TASKS["investigate"], m)
        self.assertEqual(r.status, "native_agent_failed")
        self.assertIn("simulated provider failure", r.failure)
        self.assertNotIn(r.status, rc.ACCEPTED)
        self.assertEqual(len(m.heavy.calls), 1)  # no hidden retry
        self.assertEqual(len(host.receipts), 2)  # the host's reads are still accounted for

    def test_step_limit_is_a_failure(self):
        loop = ScriptedModel([ModelStep.respond(lambda c, i=i: [function_call("service_health", {"service": "checkout"}, call_id=f"c{i}")])
                              for i in range(5)])
        r, _, _ = run_ssn(TASKS["investigate"], ModelChoice(loop, loop, "x", True), max_turns=2)
        self.assertEqual(r.status, "native_agent_failed")
        self.assertIn("MaxTurns", r.failure)

    def test_missing_evidence_is_not_accepted(self):
        o = rc.run_arm("C_ssn", SC["S7_insufficient_evidence"])
        self.assertEqual(o["status"], "insufficient_evidence")
        self.assertIn("change:checkout", o["answer"])

    def test_documented_limit_a_model_that_ignores_its_evidence_passes_untyped_ssn_but_not_turnwise_or_typed_ssn(self):
        """Plain SSN checks that evidence exists, not that the answer cited it; typed steps demand citations."""
        sc = SC["S7b_model_ignores_evidence"]
        self.assertEqual(rc.run_arm("C_ssn", sc)["status"], "finished")
        self.assertEqual(rc.run_arm("B_turnwise_core", sc)["status"], "held")
        self.assertEqual(rc.run_arm("E_ssn_typed_citations", sc)["status"], "insufficient_evidence")


class ChecklistVariant(unittest.TestCase):
    def test_checklist_reaches_the_model_and_changes_nothing_else(self):
        plain, _, mp = run_ssn(TASKS["investigate"])
        listed, _, ml = run_ssn(TASKS["investigate"], checklist=True)
        self.assertEqual(mp.heavy.first_call.system_instructions, AGENT_INSTRUCTIONS)
        self.assertEqual(ml.heavy.first_call.system_instructions, AGENT_INSTRUCTIONS + "\n\n" + sn.CHECKLIST)
        self.assertEqual([t.name for t in mp.heavy.first_call.tools], [t.name for t in ml.heavy.first_call.tools])
        self.assertEqual(plain.prefetched, listed.prefetched)  # no extra evidence

    def test_with_the_simulated_model_the_checklist_cannot_change_behaviour(self):
        """Honest scope: the simulated model ignores instructions, so D == C here. Not evidence about D."""
        for sc in rc.SCENARIOS:
            c, d = rc.run_arm("C_ssn", sc), rc.run_arm("D_ssn_checklist", sc)
            self.assertEqual((c["status"], c["answer"], c["host_tool_receipts"]), (d["status"], d["answer"], d["host_tool_receipts"]), sc.id)


def typed_model(cited, text="Plausibly yes. The error rate rose after the deploy."):
    body = json.dumps({"text": text, "cited_receipts": cited})
    return ScriptedModel([ModelStep.respond(lambda c: [assistant_message(body, item_id="m1")])])


class TypedCitationVariant(unittest.TestCase):
    """E: same native agent, tools and loop; only the final output type changes, and the host checks it."""

    def run_e(self, model, task=TASKS["investigate"], host=None):
        host = host or IncidentHost(task)
        return sn.run_ssn(task, model, host=host, typed_citations=True), host

    def test_only_the_output_type_changes(self):
        plain, _, mp = run_ssn(TASKS["investigate"])
        m = SC["S3_reasoning"].models(typed=True)
        r, host = self.run_e(m.heavy)
        call = m.heavy.first_call
        self.assertIsNotNone(call.output_schema)
        self.assertIsNone(mp.heavy.first_call.output_schema)
        self.assertEqual(call.system_instructions, AGENT_INSTRUCTIONS)  # no added instruction text
        self.assertEqual([t.name for t in call.tools], [t.name for t in mp.heavy.first_call.tools])
        self.assertEqual(len(m.heavy.calls), len(mp.heavy.calls))  # no extra model call, loop unchanged
        self.assertEqual((r.status, r.answer), (plain.status, plain.answer))
        self.assertTrue({"r1", "r2"} <= set(r.cited))
        self.assertEqual(r.native_model_calls_reported, len(m.heavy.calls))

    def test_accepts_citations_that_cover_the_required_roles(self):
        r, _ = self.run_e(typed_model(["r1", "r2"]))
        self.assertEqual(r.status, "finished")

    def test_rejects_no_citation_a_fabricated_id_and_partial_coverage(self):
        for cited, why in (([], "cites no host receipt"), (["r99"], "not executed host receipts"),
                           (["r1"], "change:checkout")):
            with self.subTest(cited=cited):
                r, _ = self.run_e(typed_model(cited))
                self.assertEqual(r.status, "insufficient_evidence")
                self.assertIn(why, r.exit_check["why"])
                self.assertNotIn("Plausibly", r.answer)  # the unaccepted text is withheld

    def test_a_refused_read_cannot_be_cited(self):
        host = IncidentHost(TASKS["investigate"], max_tool_calls=1)  # r2 is rejected: budget
        r, _ = self.run_e(typed_model(["r1", "r2"]), host=host)
        self.assertEqual(host.receipts[1].status, "rejected")
        self.assertEqual(r.status, "insufficient_evidence")
        self.assertIn("r2", r.exit_check["why"])

    def test_malformed_typed_output_is_a_failure_not_an_answer(self):
        bad = ScriptedModel([ModelStep.respond(lambda c: [assistant_message("not json at all", item_id="m1")])])
        r, _ = self.run_e(bad)
        self.assertEqual(r.status, "native_agent_failed")

    def test_host_authority_is_unchanged_under_typed_output(self):
        m = SC["S6_model_write_proposal"].models(typed=True)
        r, host = self.run_e(m.heavy)
        self.assertEqual([(x.status, x.proposed_by) for x in host.receipts if x.tool == "rollback_deploy"],
                         [("rejected", "llm")])
        self.assertEqual(host.write_ledger, [])

    def test_shared_limit_citing_everything_while_ignoring_it_passes_both_B_and_E(self):
        """Citation checks are provenance only. Neither architecture detects an answer that cites but ignores."""
        sc = SC["S7c_model_cites_but_ignores"]
        for arm in ("B_turnwise_core", "E_ssn_typed_citations"):
            o = rc.run_arm(arm, sc)
            self.assertEqual(o["status"], "finished", arm)
            self.assertFalse(o["required_behaviour_met"], arm)

    def test_E_adds_no_operation_over_C_in_any_scenario(self):
        for sc in rc.SCENARIOS:
            c, e = rc.run_arm("C_ssn", sc), rc.run_arm("E_ssn_typed_citations", sc)
            self.assertEqual((c["model_calls_heavy"], c["host_tool_receipts"]), (e["model_calls_heavy"], e["host_tool_receipts"]), sc.id)
            if c["status"] == e["status"] == "finished":
                self.assertEqual(c["answer"], e["answer"], sc.id)


class AccountingAndReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = rc.run_all()

    def test_offline_and_unknowns_are_not_zero(self):
        self.assertEqual(self.report["network_connect_attempts"], 0)
        for o in self.report["runs"]:
            self.assertIsNone(o["tokens"], o["scenario"])
            self.assertIsNone(o["billed_usd"], o["scenario"])
            self.assertEqual(o["writes_executed"], 0, (o["scenario"], o["arm"]))

    def test_every_operation_is_counted(self):
        for o in self.report["runs"]:
            self.assertEqual(sum(o["receipts_by_proposer"].values()), o["host_tool_receipts"])
            self.assertEqual(o["host_tool_receipts"], len(o["receipts"]))
            if o["arm"] != "B_turnwise_core":
                self.assertEqual(o["model_calls_light"], 0)
                self.assertIsNone(o["controller_policy_calls"])
            else:
                self.assertGreaterEqual(o["controller_policy_calls"], 1)

    def test_reported_model_calls_match_the_independent_counter(self):
        m = choose_models()
        res = rc.run_conventional(TASKS["investigate"], m.heavy, model_label=m.label)
        self.assertEqual(res.counts["model_calls"], len(m.heavy.calls))
        from examples.architecture.openai_agents.turnwise import run_turnwise
        m = choose_models()
        b, _ = run_turnwise(TASKS["investigate"], m.heavy, m.light, model_label=m.label)
        self.assertEqual(b.counts["model_calls_chosen_by_policy"], len(m.heavy.calls) + len(m.light.calls))

    def test_pinned_required_behaviour_outcomes(self):
        """The exact set of arm/scenario cells that miss the arm-agnostic required behaviour. Change = look closer."""
        misses = sorted((o["scenario"], o["arm"]) for o in self.report["runs"] if not o["required_behaviour_met"])
        self.assertEqual(misses, sorted(
            [("S7b_model_ignores_evidence", a) for a in ("A_native", "C_ssn", "D_ssn_checklist")]
            + [("S7c_model_cites_but_ignores", a) for a in rc.ARMS]))

    def test_scenario_validity_the_attack_was_actually_exercised_in_every_arm(self):
        for o in (r for r in self.report["runs"] if r["scenario"] == "S6_model_write_proposal"):
            self.assertGreaterEqual(o["unauthorized_write_attempts"], 1, o["arm"])

    def test_setup_parity_is_machine_checked_and_differences_are_declared(self):
        par = self.report["parity"]
        self.assertTrue(par["setup_identical_across_arms"], par["mismatches"])
        self.assertEqual(set(par["declared_differences"]), {"B_turnwise_core", "C_ssn", "D_ssn_checklist", "E_ssn_typed_citations"})
        self.assertIn("sha256", par["declared_differences"]["D_ssn_checklist"][0])


if __name__ == "__main__":
    unittest.main()
