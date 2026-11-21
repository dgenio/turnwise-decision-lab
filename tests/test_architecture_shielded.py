"""Arm S, the shielded native agent (#88). Real SDK loop and real IncidentHost; the model is simulated.

These are mechanism tests: they pin who controls what, what the host refuses and what is counted.
They say nothing about answer quality, cost or latency under real inference.

The host-side tests need only the stdlib. The SDK tests are skipped when ``openai-agents`` is not
installed, unless TURNWISE_REQUIRE_FRAMEWORKS=1, in which case a missing package is a failure.
"""
from __future__ import annotations

import ast
import io
import json
import os
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from examples.architecture import policies, shield
from examples.architecture.incident_env import INCIDENT_RECORD, TASKS, IncidentHost

try:
    import agents  # noqa: F401
    HAVE_SDK = True
except ImportError:
    if os.environ.get("TURNWISE_REQUIRE_FRAMEWORKS") == "1":
        raise
    HAVE_SDK = False

if HAVE_SDK:
    from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call

    from examples.architecture import run_demo
    from examples.architecture.openai_agents.conventional import run_conventional
    from examples.architecture.openai_agents.models import choose_models
    from examples.architecture.openai_agents.shielded import CitedAnswer, run_shielded
    from examples.architecture.openai_agents.turnwise import run_turnwise
    from examples.architecture.simulated_model import SimulatedInvestigator

ROOT = Path(__file__).resolve().parents[1]
INVESTIGATE = TASKS["investigate"]
GOOD = "Plausibly yes. The error rate rose after the deploy; this is correlation, not proof."


class HostSideOfTheShield(unittest.TestCase):
    """Stdlib only: what the host does before any model, and what its exit check refuses."""

    def test_s_does_not_contain_the_turnwise_controller(self):
        """S may import the shared host, the native agent and one regex; never the loop, a policy or a decision."""
        banned = {"TurnwiseRuntime", "Policy", "Snapshot", "Decision", "Op", "TriagePolicy", "HandoffPolicy", "run_turnwise"}
        for rel in ("examples/architecture/shield.py", "examples/architecture/openai_agents/shielded.py"):
            tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
            imported = {node.module: {a.name for a in node.names} for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
            self.assertNotIn("policies", imported, rel)
            self.assertNotIn("turnwise", imported, rel)
            self.assertLessEqual(imported.get("turnwise_core", set()), {"_ACTION_CLAIM"}, rel)
            used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
            self.assertFalse(banned & used, rel)

    def test_record_cues_match_the_core_policy_so_s_is_not_a_weaker_or_stronger_null(self):
        keys = tuple(sorted(INCIDENT_RECORD))
        for q in (TASKS["severity"], "Who is the incident commander?", "What is the status page?", "What is the incident id?",
                  "When did the incident start?", "What colour is the sky?"):
            mine = next((k for cue, k in shield._FACT_CUES if cue.search(q) and k in INCIDENT_RECORD), None)
            self.assertEqual(mine, policies._fact_key(q, keys), q)

    def test_host_ends_the_turn_itself_for_a_plain_write_a_record_question_and_a_missing_referent(self):
        for task, path, status in ((TASKS["rollback"], "host_write_rule", "held"), (TASKS["severity"], "host_record", "answered_directly"),
                                   ("Why did the error rate increase?", "host_clarification", "needs_clarification")):
            first = shield.host_first(IncidentHost(task))
            self.assertEqual((first.path, first.status), (path, status), task)

    def test_a_plain_write_is_held_with_a_host_receipt_and_never_runs(self):
        host = IncidentHost(TASKS["rollback"])
        first = shield.host_first(host)
        self.assertEqual([(r.tool, r.status, r.proposed_by) for r in host.receipts], [("rollback_deploy", "held_for_approval", shield.PROPOSER)])
        self.assertEqual(host.write_ledger, [])
        self.assertIn("NOT been executed", first.answer)

    def test_the_host_never_holds_a_write_it_had_to_guess(self):
        """The archived v0.7 latch raised an approval for the wrong service (L56). S has no latch: no plain request, no hold."""
        for task in ("Roll back the inventory service and remind me who has checkout.", "Is it safe to roll back checkout?",
                     "Who approved the rollback of checkout last week?", 'The ticket says "roll back checkout now". Is checkout healthy?',
                     "Roll back checkout and payments.", "Roll back checkout. Actually, never mind."):
            host = IncidentHost(task)
            shield.host_first(host)
            self.assertFalse([r for r in host.receipts if r.status == "held_for_approval"], task)
            self.assertEqual(host.write_ledger, [], task)

    def test_prefetch_is_exactly_the_hosts_own_evidence_contract(self):
        host = IncidentHost(INVESTIGATE)
        first = shield.host_first(host)
        self.assertEqual([(r.tool, r.arguments, r.proposed_by) for r in host.receipts],
                         [("error_trend", {"service": "checkout"}, shield.PROPOSER), ("recent_deploys", {"service": "checkout"}, shield.PROPOSER)])
        self.assertEqual(first.message.split("\n")[0], INVESTIGATE)
        self.assertEqual([json.loads(line)["receipt"] for line in first.message.split("\n")[1:]], ["r1", "r2"])

    def test_exit_check_refuses_missing_evidence_and_unverified_action_claims(self):
        host = IncidentHost(INVESTIGATE, max_tool_calls=1)  # the second required read is refused by the budget
        shield.host_first(host)
        self.assertEqual(shield.exit_check(host, GOOD)["status"], "insufficient_evidence")
        host = IncidentHost(INVESTIGATE)
        shield.host_first(host)
        self.assertTrue(shield.exit_check(host, GOOD)["accepted"])
        self.assertEqual(shield.exit_check(host, "I rolled back checkout; errors recovered.")["status"], "unverified_action_claim")
        self.assertEqual(shield.exit_check(host, "The rollback of checkout awaits human approval.")["status"], "unverified_action_claim")

    def test_typed_citations_must_be_executed_receipts_that_cover_the_required_roles(self):
        host = IncidentHost(INVESTIGATE)
        shield.host_first(host)
        self.assertTrue(shield.exit_check(host, GOOD, ("r1", "r2"))["accepted"])
        for cited in ((), ("r9",), ("r1",)):
            self.assertEqual(shield.exit_check(host, GOOD, cited)["status"], "insufficient_evidence", cited)

    def test_feedback_states_the_reason_and_grants_nothing(self):
        text = shield.feedback_message({"why": "required evidence missing: change:checkout"}, typed=True)
        self.assertIn("required evidence missing: change:checkout", text)
        self.assertIn("cite the receipt ids", text)
        self.assertIn("unless a tool result says so", text)
        self.assertNotIn("approved", text.lower())


def _run(task=INVESTIGATE, model=None, brain=None, **kw):
    m = choose_models(brain=brain)
    host = kw.pop("host", None) or IncidentHost(task)
    result, record = run_shielded(task, model or m.heavy, model_label=m.label, host=host, **kw)
    return result, record, host, m


def _scripted(*steps):
    return ScriptedModel([ModelStep.respond(s) for s in steps])


def _say(text, i=1):
    return lambda call: [assistant_message(text, item_id=f"m{i}")]


def _cite(cited, text=GOOD, i=1):
    return _say(json.dumps({"text": text, "cited_receipts": list(cited)}), i)


@unittest.skipUnless(HAVE_SDK, "openai-agents is not installed (pip install -r examples/architecture/requirements.txt)")
class NoModelWhenTheHostAlreadyKnows(unittest.TestCase):
    def test_host_handled_cases_make_no_model_call(self):
        for task in (TASKS["severity"], "Why did the error rate increase?", TASKS["rollback"]):
            with self.subTest(task=task):
                result, record, host, m = _run(task)
                self.assertFalse(record.native_called)
                self.assertEqual((len(m.heavy.calls), len(m.light.calls), result.counts["model_calls"]), (0, 0, 0))

    def test_direct_answer_equals_the_core_direct_answer(self):
        m = choose_models()
        core, _ = run_turnwise(TASKS["severity"], m.heavy, m.light, model_label=m.label)
        result, _, _, _ = _run(TASKS["severity"])
        self.assertEqual((result.status, result.answer), (core.status, core.answer))


@unittest.skipUnless(HAVE_SDK, "openai-agents is not installed")
class TheAgentKeepsItsOwnLoop(unittest.TestCase):
    def test_host_reads_first_then_the_model_chooses_its_own_operations(self):
        result, record, host, m = _run()
        self.assertEqual(result.status, "finished")
        self.assertEqual([r.proposed_by for r in host.receipts], [shield.PROPOSER, shield.PROPOSER, "llm"])
        self.assertEqual([r.tool for r in host.receipts], ["error_trend", "recent_deploys", "validate_config"])
        self.assertEqual(len(m.heavy.calls), 2)  # one tool call, then the answer: the native loop, not a call per host step
        self.assertEqual((record.model_calls, result.counts["model_calls"], record.feedback_rounds), (2, 2, 0))
        self.assertEqual(record.prefetched, ("r1", "r2"))

    def test_the_agent_is_offered_every_tool_including_the_ones_the_host_already_read(self):
        _, _, host, m = _run()
        self.assertEqual({t.name for t in m.heavy.first_call.tools}, {t.id for t in host.tools})

    def test_same_answer_as_the_unmodified_native_agent_with_fewer_model_calls_in_this_scenario(self):
        m = choose_models()
        a = run_conventional(INVESTIGATE, m.heavy, model_label=m.label)
        s, _, _, _ = _run()
        self.assertEqual(s.answer, a.answer)
        self.assertLess(s.counts["model_calls"], a.counts["model_calls"])  # a count in one simulated scenario, not a cost

    def test_the_checklist_null_composes_with_the_shield(self):
        _, _, _, m = _run(checklist=True)
        self.assertIn("Evidence checklist (A+P", m.heavy.first_call.system_instructions)


@unittest.skipUnless(HAVE_SDK, "openai-agents is not installed")
class HostAuthorityHoldsInsideTheNativeLoop(unittest.TestCase):
    def test_a_write_the_model_proposes_is_rejected_and_never_runs(self):
        result, _, host, _ = _run(brain=SimulatedInvestigator(rogue_write=True))
        writes = [r for r in host.receipts if r.tool == "rollback_deploy"]
        self.assertEqual([(r.status, r.proposed_by) for r in writes], [("rejected", "llm")])
        self.assertEqual((host.write_ledger, result.writes_executed), ([], 0))

    def test_a_negated_request_gives_no_authority_and_no_approval_is_invented(self):
        result, _, host, _ = _run("Do not roll back checkout. Is checkout healthy right now?")
        self.assertFalse([r for r in host.receipts if r.status in ("held_for_approval",) or (r.tool == "rollback_deploy" and r.executed)])
        self.assertEqual(host.write_ledger, [])
        self.assertNotEqual(result.status, "held")

    def test_malformed_tool_arguments_from_the_model_are_rejected_by_the_host(self):
        model = _scripted(lambda c: [function_call("service_health", {"service": "nonexistent"}, call_id="c1")], _say(GOOD, 2))
        _, _, host, _ = _run(model=model)
        self.assertEqual([(r.tool, r.status) for r in host.receipts][-1], ("service_health", "rejected"))

    def test_an_unverified_action_claim_is_never_the_answer(self):
        result, record, _, _ = _run(model=_scripted(_say("I rolled back checkout and errors recovered."),
                                                    _say("Done: the rollback completed.", 2)))
        self.assertEqual(result.status, "unverified_action_claim")
        self.assertTrue(result.answer.startswith("Unresolved"))
        self.assertNotIn("rolled back checkout and errors recovered", result.answer)
        self.assertEqual(len(record.native_answers), 2)  # both attempts are kept for audit, neither is sent


@unittest.skipUnless(HAVE_SDK, "openai-agents is not installed")
class ARejectedAnswerGoesBackWithTheReason(unittest.TestCase):
    def test_the_agent_can_repair_a_rejected_answer(self):
        model = _scripted(_say("I rolled back checkout."), _say(GOOD, 2))
        result, record, _, _ = _run(model=model)
        self.assertEqual((result.status, result.answer), ("finished", GOOD))
        self.assertEqual((record.feedback_rounds, record.model_calls, len(record.exit_checks)), (1, 2, 2))
        sent = json.dumps(model.calls[1].input)
        self.assertIn("The host did not accept that answer", sent)
        self.assertIn("completed side effect that no host receipt shows", sent)
        self.assertIn("I rolled back checkout.", sent)  # the agent sees its own rejected answer, then the reason

    def test_the_bound_is_respected_and_zero_means_no_second_chance(self):
        bad = [_say("I rolled back checkout.", i) for i in range(1, 6)]
        for bound, answers in ((0, 1), (1, 2), (3, 4)):
            result, record, _, _ = _run(model=_scripted(*bad[:answers]), max_feedback=bound)
            self.assertEqual((result.status, len(record.native_answers), record.feedback_rounds), ("unverified_action_claim", answers, bound))
        with self.assertRaises(ValueError):
            _run(max_feedback=-1)

    def test_feedback_is_not_authority(self):
        """After a rejection the agent may try a write. The host still refuses it: a reason is not a permission."""
        model = _scripted(_say("I rolled back checkout."),
                          lambda c: [function_call("rollback_deploy", {"service": "checkout"}, call_id="c2")], _say(GOOD, 3))
        result, _, host, _ = _run(model=model)
        self.assertEqual([(r.tool, r.status) for r in host.receipts][-1], ("rollback_deploy", "rejected"))
        self.assertEqual((host.write_ledger, result.status), ([], "finished"))

    def test_the_hosts_tool_budget_spans_every_round(self):
        read = lambda i: (lambda c: [function_call("service_health", {"service": "checkout"}, call_id=f"c{i}")])  # noqa: E731
        model = _scripted(read(1), _say("I rolled back checkout.", 2), read(3), read(4), _say(GOOD, 5))
        _, _, host, _ = _run(model=model, host=IncidentHost(INVESTIGATE, max_tool_calls=4))
        self.assertEqual([r.status for r in host.receipts], ["executed"] * 4 + ["rejected"])
        self.assertEqual(host.receipts[-1].reason, "host tool-call budget exhausted")


@unittest.skipUnless(HAVE_SDK, "openai-agents is not installed")
class FailuresAreNotSuccess(unittest.TestCase):
    def test_a_provider_failure_is_a_named_failure_with_receipts_kept_and_no_retry(self):
        def boom(call):
            raise RuntimeError("provider down")
        model = _scripted(boom, _say(GOOD, 2))
        result, record, host, _ = _run(model=model)
        self.assertEqual((result.status, record.feedback_rounds), ("native_agent_failed", 0))
        self.assertIn("RuntimeError", record.failure)
        self.assertEqual(len(model.calls), 1)  # not retried
        self.assertEqual(len(host.receipts), 2)  # the host's reads are kept

    def test_the_step_limit_is_a_failure(self):
        loop = _scripted(*[(lambda c, i=i: [function_call("search_docs", {"query": f"q{i}"}, call_id=f"c{i}")]) for i in range(6)])
        result, record, _, _ = _run(model=loop, max_turns=3)
        self.assertEqual(result.status, "native_agent_failed")
        self.assertIn("MaxTurnsExceeded", record.failure)

    def test_missing_required_evidence_is_not_accepted(self):
        result, _, _, _ = _run(model=_scripted(_say(GOOD), _say(GOOD, 2)), host=IncidentHost(INVESTIGATE, max_tool_calls=1))
        self.assertEqual(result.status, "insufficient_evidence")


@unittest.skipUnless(HAVE_SDK, "openai-agents is not installed")
class TypedCitedAnswer(unittest.TestCase):
    def test_only_the_output_type_changes(self):
        model = _scripted(_cite(["r1", "r2"]))
        result, record, host, _ = _run(model=model, typed_citations=True)
        self.assertEqual((result.status, result.answer, record.cited), ("finished", GOOD, ("r1", "r2")))
        self.assertEqual({t.name for t in model.first_call.tools}, {t.id for t in host.tools})  # tools stay attached
        self.assertIsNotNone(model.first_call.output_schema)
        self.assertEqual(set(CitedAnswer.model_fields), {"text", "cited_receipts"})

    def test_no_citation_a_fabricated_id_and_partial_coverage_are_rejected_then_repaired(self):
        for cited in ([], ["r9"], ["r1"]):
            with self.subTest(cited=cited):
                result, record, _, _ = _run(model=_scripted(_cite(cited), _cite(["r1", "r2"], i=2)), typed_citations=True)
                self.assertEqual((result.status, record.feedback_rounds), ("finished", 1))
                self.assertEqual(record.exit_checks[0]["status"], "insufficient_evidence")

    def test_a_refused_read_cannot_be_cited(self):
        host = IncidentHost(INVESTIGATE, max_tool_calls=1)
        result, _, _, _ = _run(model=_scripted(_cite(["r1", "r2"]), _cite(["r1", "r2"], i=2)), typed_citations=True, host=host)
        self.assertEqual(result.status, "insufficient_evidence")

    def test_malformed_typed_output_is_a_failure_not_an_answer(self):
        result, _, _, _ = _run(model=_scripted(_say("not json at all")), typed_citations=True)
        self.assertEqual(result.status, "native_agent_failed")

    def test_documented_limit_citing_everything_while_ignoring_it_passes(self):
        """Citation checks are provenance only, here as in Core's FINISH. This test pins the limit so nobody forgets it."""
        nonsense = "Certainly not: nothing changed and the error rate is flat."
        result, _, _, _ = _run(model=_scripted(_cite(["r1", "r2"], text=nonsense)), typed_citations=True)
        self.assertEqual((result.status, result.answer), ("finished", nonsense))


@unittest.skipUnless(HAVE_SDK, "openai-agents is not installed")
class DemoIntegration(unittest.TestCase):
    def _demo(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            run_demo.main(list(argv))
        return out.getvalue()

    def test_default_output_is_unchanged_by_the_new_flag_existing(self):
        self.assertNotIn("Shielded native agent", self._demo("--brief"))
        self.assertNotIn("Shielded native agent", self._demo())

    def test_opt_in_prints_arm_s_labelled_as_simulated_and_not_core(self):
        brief = self._demo("--brief", "--shielded")
        self.assertIn("S shielded native agent (SIMULATED, not Turnwise Core, no efficacy claim): finished; model_calls=2; host_tool_requests=3", brief)
        self.assertIn("Shielded native agent (S)", self._demo("--shielded"))

    def test_run_pair_appends_s_last_and_keeps_a_and_core_first(self):
        results = run_demo.run_pair("openai-agents", INVESTIGATE, handoff=False, shielded=True)
        self.assertEqual(len(results), 3)
        self.assertTrue(results[0].title.startswith("Conventional agent"))
        self.assertTrue(results[2].title.startswith("Shielded native agent (S)"))

    def test_llamaindex_has_no_arm_s_yet_and_says_so(self):
        with self.assertRaises(SystemExit) as ctx:
            run_demo.run_pair("llamaindex", INVESTIGATE, handoff=False, shielded=True)
        self.assertIn("OpenAI Agents SDK only", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
