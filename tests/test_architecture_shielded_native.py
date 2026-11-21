"""Arm S, the shielded native agent (issue #88). Mechanism tests; the model is SIMULATED.

Ported from the unmerged branch ``experiment/sonnet55-strong-simple-null`` (``research/sonnet55-strong-null``)
and re-derived against ``main``. The first three classes are stdlib-only and run in the main CI job. The rest
run the real OpenAI Agents SDK loop with its own scripted model and need the pinned frameworks.

They show control-flow properties: where the host acts, that the agent keeps its own loop, that nothing
executes without the host, and what the exit gate can and cannot catch. They say nothing about answer quality,
cost or latency under real inference, and nothing about whether arm S is as good as Turnwise Core with a real
model.
"""
from __future__ import annotations

import ast
import contextlib
import io
import json
import os
import socket
import unittest
from pathlib import Path
from unittest import mock

from examples.architecture import policies, shielded_native as sn
from examples.architecture.incident_env import AGENT_INSTRUCTIONS, INCIDENT_RECORD, TASKS, IncidentHost
from examples.architecture.simulated_model import NativeAction, SimulatedInvestigator, _intent, _parse_result

try:
    import agents  # noqa: F401
    import llama_index.core  # noqa: F401  (the cost report and the demo import both pairs)
    FRAMEWORKS_PRESENT = True
except ImportError:
    if os.environ.get("TURNWISE_REQUIRE_FRAMEWORKS") == "1":
        raise
    FRAMEWORKS_PRESENT = False

ROOT = Path(__file__).resolve().parents[1]
INVESTIGATE = TASKS["investigate"]
LAZY_TEXT = "Yes, the deploy caused the errors."


# ---------------------------------------------------------------- simulated fixtures (not models)
class LazyInvestigator(SimulatedInvestigator):
    """Concludes on a causal question without using any evidence. ``citation`` is what it declares when asked
    for citations: "none" cites nothing; "all" cites every executed receipt it was shown and ignores them."""

    citation = "none"

    def native_step(self, *, instructions, task, tool_results, tools):
        if _intent(task) != "diagnostic":
            return super().native_step(instructions=instructions, task=task, tool_results=tool_results, tools=tools)
        seen = [r for r in (_parse_result(x) for x in tool_results) if r and r.get("status") == "executed"]
        return NativeAction("answer", text=LAZY_TEXT,
                            cited=() if self.citation == "none" else tuple(r["receipt"] for r in seen))

    def typed_step(self, packet):
        if _intent(str(packet.get("task", ""))) != "diagnostic":
            return super().typed_step(packet)
        cited = [] if self.citation == "none" else [r["receipt"] for r in packet.get("evidence", [])
                                                    if isinstance(r, dict) and r.get("status") == "executed"]
        return {"kind": "answer_candidate", "text": LAZY_TEXT, "tool": None, "arguments_json": None,
                "cited_receipts": cited}


class CitingLazyInvestigator(LazyInvestigator):
    citation = "all"


def imports_of(path: Path) -> tuple[dict[str, set[str]], set[str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = {node.module: {a.name for a in node.names} for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module}
    used = ({n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
            | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)})
    return imported, used


# ================================================================ stdlib only
class StructureTests(unittest.TestCase):
    BANNED = {"TurnwiseRuntime", "Policy", "Snapshot", "Decision", "Op", "TriagePolicy", "HandoffPolicy"}

    def test_arm_s_does_not_contain_the_turnwise_controller(self):
        """It may use the shared host, the native agent and one regex; never the loop, a policy or a decision."""
        imported, used = imports_of(ROOT / "examples/architecture/shielded_native.py")
        self.assertEqual(imported["turnwise_core"], {"_ACTION_CLAIM"})
        self.assertFalse({"policies", "openai_agents.turnwise"} & set(imported))
        self.assertFalse(self.BANNED & used)
        imported, used = imports_of(ROOT / "examples/architecture/openai_agents/shielded.py")
        self.assertFalse({"turnwise_core", "policies", "turnwise", "step_schema"} & set(imported))
        self.assertFalse(self.BANNED & used)

    def test_it_is_labelled_as_not_turnwise_core(self):
        self.assertIn("NOT Turnwise Core", sn.ARM)

    def test_fact_cues_match_the_turnwise_policy_so_the_null_is_not_weakened(self):
        keys = tuple(sorted(INCIDENT_RECORD))
        for question in (TASKS["severity"], "Who is the incident commander?", "What is the status page?",
                         "What is the incident id?", "When did the incident start?", "What colour is the sky?"):
            self.assertEqual(sn.fact_key(question), policies._fact_key(question, keys), question)


class HostRulesTests(unittest.TestCase):
    def test_a_requested_write_is_held_by_the_host_with_a_receipt_and_nothing_runs(self):
        host = IncidentHost(TASKS["rollback"])
        settled = sn.host_rules(host)
        self.assertEqual((settled.status, settled.rule), ("held", "write"))
        self.assertEqual([(r.tool, r.status, r.proposed_by) for r in host.receipts],
                         [("rollback_deploy", "held_for_approval", sn.PROPOSER)])
        self.assertEqual(host.write_ledger, [])
        self.assertIn("NOT been executed", settled.answer)

    def test_a_negated_request_gives_no_authority_and_invents_no_approval(self):
        host = IncidentHost("Don't roll back checkout. Is checkout healthy?")
        self.assertIsNone(sn.host_rules(host))  # not a write request: the agent is needed for the question
        self.assertEqual((host.requested_writes, host.receipts, host.write_ledger), (frozenset(), [], []))

    def test_a_pure_record_question_is_answered_from_the_verified_record(self):
        host = IncidentHost(TASKS["severity"])
        settled = sn.host_rules(host)
        self.assertEqual((settled.status, settled.rule, host.receipts), ("answered_directly", "record", []))
        self.assertIn(INCIDENT_RECORD["severity"], settled.answer)

    def test_ambiguity_is_asked_not_guessed(self):
        host = IncidentHost("Why did the error rate increase?")
        settled = sn.host_rules(host)
        self.assertEqual((settled.status, settled.answer, host.receipts),
                         ("needs_clarification", "Which service do you mean?", []))

    def test_prefetch_reads_exactly_the_roles_the_host_contract_requires_through_the_host(self):
        for task, tools in ((INVESTIGATE, ["error_trend", "recent_deploys"]), (TASKS["status"], ["service_health"])):
            host = IncidentHost(task)
            self.assertIsNone(sn.host_rules(host))
            read = sn.prefetch(host)
            self.assertEqual([r.tool for r in read], tools)
            self.assertEqual([(r.status, r.proposed_by) for r in host.receipts], [("executed", sn.PROPOSER)] * len(tools))
            self.assertEqual(sn.first_message(host, read).split("\n")[0], task)
            self.assertEqual([json.loads(line)["receipt"] for line in sn.first_message(host, read).split("\n")[1:]],
                             [r.id for r in read])

    def test_the_host_budget_still_applies_to_the_host_rules(self):
        host = IncidentHost(INVESTIGATE, max_tool_calls=1)
        self.assertEqual([r.status for r in sn.prefetch(host)], ["executed", "rejected"])


class ExitGateTests(unittest.TestCase):
    def host(self, **kwargs) -> IncidentHost:
        host = IncidentHost(INVESTIGATE, **kwargs)
        sn.prefetch(host)
        return host

    def test_an_unverified_action_claim_is_not_accepted(self):
        host = self.host()
        for text in ("I rolled back checkout.", "The rollback of checkout awaits human approval."):
            verdict = sn.exit_check(host, text, ("r1", "r2"))
            self.assertEqual((verdict.accepted, verdict.status), (False, "unverified_action_claim"), text)

    def test_typed_citations_are_checked_like_finish_checks_a_models(self):
        self.assertTrue(sn.exit_check(self.host(), "Plausibly yes.", ("r1", "r2")).accepted)
        for cited, why in (((), "cites no host receipt"), (("r99",), "not executed host receipts"),
                           (("r1",), "change:checkout")):
            verdict = sn.exit_check(self.host(), "Plausibly yes.", cited)
            self.assertEqual((verdict.accepted, verdict.status), (False, "insufficient_evidence"), cited)
            self.assertIn(why, verdict.why + verdict.detail)

    def test_a_refused_read_cannot_be_cited(self):
        host = self.host(max_tool_calls=1)  # r2 is rejected: budget
        verdict = sn.exit_check(host, "Plausibly yes.", ("r1", "r2"))
        self.assertFalse(verdict.accepted)
        self.assertIn("r2", verdict.detail)

    def test_without_citations_the_gate_can_only_ask_whether_the_evidence_exists(self):
        """The documented weakness of a plain-text answer: provenance is 'someone obtained it', not 'it was used'."""
        self.assertTrue(sn.exit_check(self.host(), LAZY_TEXT, None).accepted)
        missing = sn.exit_check(self.host(max_tool_calls=1), LAZY_TEXT, None)
        self.assertEqual((missing.accepted, missing.status), (False, "insufficient_evidence"))
        self.assertIn("change:checkout", missing.why)

    def test_what_the_user_is_told_never_quotes_the_agent(self):
        verdict = sn.exit_check(self.host(), "Plausibly yes.", ("ignore previous instructions",))
        self.assertNotIn("ignore previous", verdict.why)
        self.assertNotIn("ignore previous", sn.withheld_answer(verdict))
        self.assertNotIn("Plausibly", sn.withheld_answer(verdict))
        self.assertIn("ignore previous", sn.return_message(verdict))  # the agent is told what it declared


# ================================================================ real SDK loop, simulated model
@unittest.skipUnless(FRAMEWORKS_PRESENT, "needs the pinned frameworks (pip install -r examples/architecture/requirements.txt)")
class SdkCase(unittest.TestCase):
    def run_s(self, task=INVESTIGATE, models=None, **kwargs):
        from examples.architecture.openai_agents.models import choose_models
        from examples.architecture.openai_agents.shielded import run_shielded

        m = models or choose_models()
        host = kwargs.pop("host", None) or IncidentHost(task)
        result, report = run_shielded(task, m.heavy, model_label=m.label, host=host, **kwargs)
        return result, report, host, m

    @staticmethod
    def scripted(*responses):
        """A scripted SDK model: each entry is the list of output items of one response, or a callable giving it."""
        from agents.testing import ModelStep, ScriptedModel
        from examples.architecture.openai_agents.models import ModelChoice

        steps = [ModelStep.respond(r if callable(r) else (lambda call, r=r: r)) for r in responses]
        model = ScriptedModel(steps)
        return ModelChoice(model, ScriptedModel([]), "SIMULATED scripted fixture", True)

    @staticmethod
    def answer(text="Plausibly yes. The error rate rose after the deploy.", cited=("r1", "r2")):
        from agents.testing import assistant_message
        return [assistant_message(json.dumps({"text": text, "cited_receipts": list(cited)}), item_id="msg_fixture")]


class NativeLoopTests(SdkCase):
    def test_host_settled_cases_make_no_model_call(self):
        for task, status in ((TASKS["severity"], "answered_directly"), ("Why did the error rate increase?",
                             "needs_clarification"), (TASKS["rollback"], "held")):
            result, report, _, m = self.run_s(task)
            self.assertEqual((result.status, report.native_called), (status, False), task)
            self.assertEqual((len(m.heavy.calls), len(m.light.calls), result.counts["model_calls"]), (0, 0, 0))
            self.assertEqual([row.controller for row in result.rows], [sn.HOST_RULE])

    def test_the_direct_answer_equals_turnwise_cores(self):
        from examples.architecture.openai_agents.models import choose_models
        from examples.architecture.openai_agents.turnwise import run_turnwise

        m = choose_models()
        core, _ = run_turnwise(TASKS["severity"], m.heavy, m.light, model_label=m.label)
        result, _, _, _ = self.run_s(TASKS["severity"])
        self.assertEqual((result.status, result.answer), (core.status, core.answer))

    def test_the_agent_keeps_its_own_loop_and_the_host_only_adds_the_boundaries(self):
        result, report, host, m = self.run_s()
        self.assertEqual(result.status, "finished")
        # The host chose the evidence its contract requires; the model, in the SDK loop, chose the rest.
        self.assertEqual([(r.tool, r.proposed_by) for r in host.receipts],
                         [("error_trend", sn.PROPOSER), ("recent_deploys", sn.PROPOSER), ("validate_config", "llm")])
        self.assertEqual(len(m.heavy.calls), 2)  # one tool call, then the answer: one run of the native loop
        self.assertEqual((report.model_calls, result.counts["model_calls"]), (2, 2))  # counted, not asserted
        self.assertEqual([row.controller for row in result.rows],
                         [sn.HOST_RULE, sn.HOST_RULE, "LLM (inside the SDK Runner loop)",
                          "LLM (inside the SDK Runner loop)", sn.EXIT_GATE])
        self.assertIn("NOT Turnwise Core", result.title)

    def test_only_the_final_output_type_differs_from_the_unmodified_agent(self):
        _, typed, _, mt = self.run_s()
        _, plain, _, mp = self.run_s(typed_citations=False)
        first_typed, first_plain = mt.heavy.first_call, mp.heavy.first_call
        self.assertIsNotNone(first_typed.output_schema)
        self.assertIsNone(first_plain.output_schema)
        for call in (first_typed, first_plain):
            self.assertEqual(call.system_instructions, AGENT_INSTRUCTIONS)  # no added instruction text
            self.assertEqual({t.name for t in call.tools}, {"service_health", "error_trend", "recent_deploys",
                                                            "validate_config", "search_docs", "rollback_deploy"})
        self.assertEqual((len(mt.heavy.calls), typed.native_answer), (len(mp.heavy.calls), plain.native_answer))
        self.assertEqual((typed.cited, plain.cited), (("r1", "r2", "r3"), None))

    def test_same_answer_and_same_operations_as_turnwise_core_on_the_showcase(self):
        """On this task the arm-A-to-B difference is reproduced by the host reading what it already requires."""
        from examples.architecture.openai_agents.conventional import run_conventional
        from examples.architecture.openai_agents.models import choose_models
        from examples.architecture.openai_agents.turnwise import run_turnwise

        m = choose_models()
        native = run_conventional(INVESTIGATE, m.heavy, model_label=m.label)
        m = choose_models()
        core, _ = run_turnwise(INVESTIGATE, m.heavy, m.light, model_label=m.label)
        shielded, _, host, _ = self.run_s()
        self.assertEqual(len({native.answer, core.answer, shielded.answer}), 1)
        self.assertEqual((shielded.counts["model_calls"], shielded.counts["host_tool_requests"]),
                         (core.counts["model_calls_chosen_by_policy"], core.counts["host_tool_requests"]))
        self.assertLess(shielded.counts["model_calls"], native.counts["model_calls"])

    def test_the_checklist_variant_changes_only_the_instructions(self):
        from examples.architecture.checklist_null import native_instructions

        _, plain, _, mp = self.run_s()
        _, listed, _, ml = self.run_s(checklist=True)
        self.assertEqual(ml.heavy.first_call.system_instructions, native_instructions(checklist=True))
        self.assertEqual([t.name for t in ml.heavy.first_call.tools], [t.name for t in mp.heavy.first_call.tools])
        self.assertEqual((listed.prefetched, listed.status), (plain.prefetched, plain.status))


class HostAuthorityTests(SdkCase):
    def test_a_model_proposed_write_is_rejected_by_the_host_inside_the_native_loop(self):
        from examples.architecture.openai_agents.models import choose_models

        for typed in (True, False):
            result, _, host, _ = self.run_s(models=choose_models(brain=SimulatedInvestigator(rogue_write=True)),
                                            typed_citations=typed)
            writes = [r for r in host.receipts if r.tool == "rollback_deploy"]
            self.assertEqual([(r.status, r.proposed_by) for r in writes], [("rejected", "llm")], typed)
            self.assertIn("not requested by the user", writes[0].reason)
            self.assertEqual((host.write_ledger, result.writes_executed), ([], 0))

    def test_malformed_tool_arguments_from_the_model_are_rejected_by_the_host(self):
        from agents.testing import function_call

        models = self.scripted([function_call("service_health", {"service": "nonexistent"}, call_id="c1")],
                               self.answer(cited=("r1",)))
        _, _, host, _ = self.run_s(TASKS["status"], models)
        bad = [r for r in host.receipts if r.proposed_by == "llm"]
        self.assertEqual([(r.status, r.reason) for r in bad], [("rejected", "unknown service 'nonexistent'")])


class ExitGateInTheLoopTests(SdkCase):
    def lazy(self, brain, **kwargs):
        from examples.architecture.openai_agents.models import choose_models
        return self.run_s(models=choose_models(brain=brain), **kwargs)

    def core(self, brain):
        from examples.architecture.openai_agents.models import choose_models
        from examples.architecture.openai_agents.turnwise import run_turnwise

        m = choose_models(brain=brain)
        return run_turnwise(INVESTIGATE, m.heavy, m.light, model_label=m.label)[0]

    def test_an_uncited_conclusion_is_withheld_with_a_typed_answer_and_passes_without_one(self):
        """The typed final answer closes this gap with no per-step controller; the plain one does not."""
        typed, report, _, _ = self.lazy(LazyInvestigator(), max_exit_returns=0)
        self.assertEqual(typed.status, "insufficient_evidence")
        self.assertNotIn(LAZY_TEXT, typed.answer)  # the unaccepted text is withheld
        self.assertEqual(report.native_answer, LAZY_TEXT)  # and kept for inspection
        plain, _, _, _ = self.lazy(LazyInvestigator(), typed_citations=False)
        self.assertEqual((plain.status, plain.answer), ("finished", LAZY_TEXT))
        self.assertEqual(self.core(LazyInvestigator()).status, "held")

    def test_shared_limit_citing_everything_while_ignoring_it_passes_both_arms(self):
        """Citation checks are provenance only, in either architecture."""
        shielded, _, _, _ = self.lazy(CitingLazyInvestigator())
        self.assertEqual((shielded.status, shielded.answer), ("finished", LAZY_TEXT))
        core = self.core(CitingLazyInvestigator())
        self.assertEqual((core.status, core.answer), ("finished", LAZY_TEXT))

    def test_a_rejected_answer_goes_back_to_the_agent_once_with_the_reason(self):
        seen = []

        def second(call):
            seen.append(call.input[-1])
            return self.answer(cited=("r1", "r2"))

        result, report, _, m = self.run_s(models=self.scripted(self.answer(cited=("r1",)), second))
        self.assertEqual((result.status, report.exit_returns, report.model_calls), ("finished", 1, 2))
        self.assertEqual([v.accepted for v in report.verdicts], [False, True])
        self.assertEqual(seen[0]["role"], "user")
        self.assertIn("The host did not accept your answer", seen[0]["content"])
        self.assertIn("change:checkout", seen[0]["content"])
        self.assertEqual((result.counts["exit_gate_checks"], result.counts["exit_gate_returns"]), (2, 1))
        self.assertIn("exit gate -> rejected, back to the agent", [row.short for row in result.rows])

    def test_the_return_is_bounded_and_every_attempt_is_counted(self):
        bad = self.answer(cited=("r1",))
        result, report, _, m = self.run_s(models=self.scripted(bad, bad, bad))
        self.assertEqual((result.status, report.exit_returns, len(m.heavy.calls)), ("insufficient_evidence", 1, 2))
        self.assertNotIn("Plausibly", result.answer)
        none, report, _, m = self.run_s(models=self.scripted(bad, bad), max_exit_returns=0)
        self.assertEqual((none.status, report.exit_returns, len(m.heavy.calls)), ("insufficient_evidence", 0, 1))

    def test_a_returned_agent_may_fetch_what_was_missing_and_the_host_still_checks_every_call(self):
        from agents.testing import function_call

        host = IncidentHost(INVESTIGATE, max_tool_calls=3)
        models = self.scripted(self.answer(cited=("r1", "r2", "r9")),
                               [function_call("validate_config", {"service": "checkout"}, call_id="c1")],
                               self.answer(cited=("r1", "r2", "r3")))
        result, report, host, _ = self.run_s(models=models, host=host)
        self.assertEqual((result.status, report.cited), ("finished", ("r1", "r2", "r3")))
        self.assertEqual([(r.tool, r.status, r.proposed_by) for r in host.receipts][-1],
                         ("validate_config", "executed", "llm"))


class FailuresAreNotSuccessTests(SdkCase):
    def test_a_provider_failure_is_a_named_failure_with_receipts_kept_and_no_hidden_retry(self):
        from agents.testing import ScriptedModel
        from examples.architecture.openai_agents.models import ModelChoice

        failing = ScriptedModel([RuntimeError("simulated provider failure (HTTP 503)")] * 12)
        result, report, host, m = self.run_s(models=ModelChoice(failing, ScriptedModel([]), "SIMULATED failure", True))
        self.assertEqual((result.status, report.status), ("native_agent_failed", "native_agent_failed"))
        self.assertIn("simulated provider failure", report.failure)
        self.assertNotIn(result.status, sn.ACCEPTED)
        self.assertEqual(len(m.heavy.calls), 1)
        self.assertEqual(len(host.receipts), 2)  # the host's reads are still accounted for
        self.assertEqual(report.verdicts, [])  # there was no answer to check

    def test_the_step_limit_is_a_failure(self):
        from agents.testing import function_call

        loop = [(lambda call, i=i: [function_call("service_health", {"service": "checkout"}, call_id=f"c{i}")])
                for i in range(5)]
        result, report, _, _ = self.run_s(models=self.scripted(*loop), max_turns=2)
        self.assertEqual(result.status, "native_agent_failed")
        self.assertIn("MaxTurns", report.failure)

    def test_malformed_typed_output_is_a_failure_not_an_answer(self):
        from agents.testing import assistant_message

        result, _, _, _ = self.run_s(models=self.scripted([assistant_message("not json at all", item_id="m1")]))
        self.assertEqual(result.status, "native_agent_failed")
        self.assertNotIn("not json", result.answer)


class DemoAndReportTests(SdkCase):
    def test_the_demo_flag_is_opt_in_and_leaves_the_default_output_unchanged(self):
        from examples.architecture import run_demo

        def output(*argv):
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                run_demo.main(["--brief", *argv])
            return buffer.getvalue()

        default, shielded = output(), output("--shielded")
        self.assertNotIn("shielded", default.lower())
        self.assertTrue(shielded.startswith(default.rstrip("\n")))
        self.assertIn("S shielded native agent (SIMULATED, NOT Turnwise Core, no efficacy claim): finished", shielded)
        with self.assertRaises(SystemExit) as refused:
            run_demo.main(["--brief", "--shielded", "--framework", "llamaindex"])
        self.assertIn("OpenAI Agents SDK pair only", str(refused.exception))

    def test_arm_s_is_in_the_offline_cost_table_next_to_a_and_core(self):
        from examples.architecture import cost_structure

        def deny(*args, **kwargs):
            raise AssertionError("the cost-structure report attempted a network connection")

        with mock.patch.object(socket.socket, "connect", deny), mock.patch.object(socket.socket, "connect_ex", deny):
            report = cost_structure.build_report()
        arms = {a["arm"]: a for a in report["frameworks"]["openai-agents"]["arms"]}
        self.assertEqual(list(arms), ["A", "A'", "B", "S"])
        self.assertEqual((arms["S"]["verdict"], arms["S"]["termination"]), ("PASS", "finished"))
        self.assertIn("NOT Turnwise Core", arms["S"]["name"])
        # The agent's conversation is appended, so its later request repeats most of the first.
        self.assertGreaterEqual(min(arms["S"]["shared_prefix_share"][1:]), 0.7)
        self.assertEqual([a["arm"] for a in report["frameworks"]["llamaindex"]["arms"]], ["A", "A'", "B"])
        for row in report["frameworks"]["openai-agents"]["costs"]:
            self.assertTrue(row["usd"]["S"] is not None and row["usd"]["S"] > 0, row)
        text = cost_structure.render(report)
        self.assertIn("not run", text)  # LlamaIndex has no arm S, and says so instead of printing a number


if __name__ == "__main__":
    unittest.main()
