"""B', the native-intercept model port (issue #87). Mechanism tests; the model is SIMULATED.

The property these tests pin is the narrow one the hypothesis needs: **nothing a model emits is executed
without a policy decision and host validation**, also when the model is asked through a real tools field and
returns several tool calls at once. The first class is stdlib-only (a fake port) and runs in the main CI job.
The rest run the real OpenAI Agents SDK and the offline provider double and need the pinned frameworks.

They say nothing about quality, cost or latency, and nothing about how a real model behaves when a call is
declined. B' is an ablation of the model interface, not the canonical Turnwise Core arm.
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import socket
import unittest
from unittest import mock

from examples.architecture.incident_env import AGENT_INSTRUCTIONS, TASKS, IncidentHost
from examples.architecture.native_intercept import (ARCHITECTURE, HOST_RESULTS, INTERCEPT_CONTRACT, NOT_CONSIDERED,
                                                    NativeCall, NativeInterceptRuntime, NativeTurn)
from examples.architecture.policies import TriagePolicy, op_for
from examples.architecture.simulated_model import SimulatedInvestigator
from examples.architecture.turnwise_core import Budget, Decision, ModelCallFailed, ModelOutcome, TurnwiseRuntime

try:
    import agents  # noqa: F401
    import llama_index.core  # noqa: F401  (the report imports the smoke harness, which knows both pairs)
    FRAMEWORKS_PRESENT = True
except ImportError:
    if os.environ.get("TURNWISE_REQUIRE_FRAMEWORKS") == "1":
        raise
    FRAMEWORKS_PRESENT = False

INVESTIGATE = TASKS["investigate"]
SVC = {"service": "checkout"}


def call(tool: str, arguments=None, call_id: str | None = None, raw: str | None = None) -> NativeCall:
    return NativeCall(call_id or f"c_{tool}", tool, raw if raw is not None else json.dumps(arguments or SVC))


def final(cited=("r1", "r2", "r3"), text="Plausibly yes.", kind="answer_candidate") -> NativeTurn:
    return NativeTurn(final={"kind": kind, "text": text, "cited_receipts": list(cited)})


def playbook(*roles: str) -> TriagePolicy:
    """``TriagePolicy`` whose playbook reads only these roles first; the model chooses the rest."""
    return type("Playbook", (TriagePolicy,), {"PLAYBOOK": {**TriagePolicy.PLAYBOOK, "diagnostic": roles}})()


class FakePort:
    """A scripted port: records exactly what the runtime hands it and returns the next scripted turn."""

    label = "SIMULATED fake port"
    describe = "a fake native-intercept port"

    def __init__(self, *turns):
        self.turns = list(turns)
        self.seen: list[dict] = []

    def native_step(self, tier, *, first_message, offered, answers, host_results):
        self.seen.append({"tier": tier, "first_message": first_message, "offered": [t.id for t in offered],
                          "answers": dict(answers), "host_results": list(host_results)})
        turn = self.turns.pop(0)
        if isinstance(turn, BaseException):
            raise turn
        return turn

    def handoff(self, task_text, max_turns):
        raise AssertionError("no handoff in these tests")


def run(*turns, policy=None, task=INVESTIGATE, budget=Budget(), host=None, **kwargs):
    host = host or IncidentHost(task)
    port = FakePort(*turns)
    runtime = NativeInterceptRuntime(host, policy or TriagePolicy(), port, budget=budget, **kwargs)
    return runtime.run(), runtime, host, port


# ================================================================ stdlib only: the runtime with a fake port
class NothingExecutesWithoutThePolicyTests(unittest.TestCase):
    def test_only_the_model_port_differs_from_turnwise_core(self):
        for name in ("run", "host_validates", "_check_finish", "_execute_tool", "_terminal", "_reject", "snapshot"):
            self.assertIs(getattr(NativeInterceptRuntime, name), getattr(TurnwiseRuntime, name), name)
        self.assertIsNot(NativeInterceptRuntime._call_model, TurnwiseRuntime._call_model)

    def test_it_labels_itself_as_an_ablation_and_turnwise_core_keeps_its_label(self):
        result, _, _, _ = run(NativeTurn(calls=(call("validate_config"),)), final())
        self.assertEqual(TurnwiseRuntime.ARCHITECTURE, "Turnwise Core")
        self.assertIn("B' ablation", ARCHITECTURE)
        self.assertTrue(result.title.startswith(ARCHITECTURE))
        self.assertTrue(result.notes[0].startswith("ABLATION (B')"))

    def test_a_tool_call_in_a_model_response_is_a_proposal_and_runs_only_after_the_policy_adopts_it(self):
        result, runtime, host, port = run(NativeTurn(calls=(call("validate_config"),)), final())
        self.assertEqual(result.status, "finished")
        self.assertEqual([(r.tool, r.proposed_by) for r in host.receipts],
                         [("error_trend", "turnwise_policy"), ("recent_deploys", "turnwise_policy"),
                          ("validate_config", "turnwise_policy")])
        proposal = runtime.outcomes[0]
        self.assertEqual((proposal.kind, proposal.proposal.call()), ("tool_proposal", "validate_config(service=checkout)"))
        self.assertIn(proposal.id, [s.latest.id for s in runtime.snapshots if s.latest is not None])  # the policy saw it
        self.assertEqual(runtime._adopted, {proposal.id: "r3"})
        # The model was called twice and was given the host's receipt as the answer to its call.
        self.assertEqual(len(port.seen), 2)
        answer = port.seen[1]["answers"]["c_validate_config"]
        self.assertEqual((answer.adopted, json.loads(answer.text)["receipt"]), (True, "r3"))

    def test_a_policy_that_adopts_nothing_means_nothing_runs(self):
        class Refuses(TriagePolicy):
            def decide(self, s):
                d = super().decide(s)
                return Decision(d.op.__class__.HOLD, "this policy adopts no model proposal", message="Stopped.") \
                    if d.adopted_from else d

        result, runtime, host, port = run(NativeTurn(calls=(call("validate_config"), call("service_health"))),
                                          policy=Refuses())
        self.assertEqual(result.status, "held")
        self.assertEqual([r.tool for r in host.receipts], ["error_trend", "recent_deploys"])  # the policy's own reads
        self.assertEqual((runtime.proposals_seen, runtime.proposals_declined, runtime._adopted), (2, 2, {}))

    def test_parallel_proposals_are_each_considered_validated_and_answered(self):
        calls = (call("error_trend"), call("recent_deploys"), call("validate_config"))
        result, runtime, host, port = run(NativeTurn(calls=calls), final(), policy=playbook())
        self.assertEqual(result.status, "finished")
        self.assertEqual([(r.tool, r.status, r.proposed_by) for r in host.receipts],
                         [(c.tool, "executed", "turnwise_policy") for c in calls])
        # One policy decision per proposal, in order, each with that proposal as the latest observation.
        considered = [s.latest.id for s in runtime.snapshots if isinstance(s.latest, ModelOutcome)
                      and s.latest.kind == "tool_proposal"]
        self.assertEqual(considered, ["m1", "m2", "m3"])
        self.assertEqual(result.counts["policy_decisions"], 6)  # model call, 3 proposals, model call, FINISH
        self.assertEqual(result.counts["model_calls_chosen_by_policy"], 2)
        answers = port.seen[1]["answers"]
        self.assertEqual({k: (a.adopted, json.loads(a.text)["tool"]) for k, a in answers.items()},
                         {c.call_id: (True, c.tool) for c in calls})
        self.assertEqual([row.step for row in result.rows if "." in row.step], ["1.1", "1.2", "1.3"])

    def test_a_declined_call_is_answered_with_the_reason_and_never_reaches_the_host(self):
        turn = NativeTurn(calls=(call("validate_config"), call("rollback_deploy")))
        result, runtime, host, port = run(turn, final())
        self.assertEqual(result.status, "finished")
        self.assertNotIn("rollback_deploy", [r.tool for r in host.receipts])
        self.assertEqual((host.write_ledger, result.writes_executed), ([], 0))
        declined = port.seen[1]["answers"]["c_rollback_deploy"]
        self.assertFalse(declined.adopted)
        self.assertTrue(declined.text.startswith("declined by policy: "))
        self.assertIn("a write the user did not request", declined.text)
        self.assertEqual((runtime.proposals_seen, runtime.proposals_declined), (2, 1))
        self.assertIn("NOT adopted by the policy", " ".join(result.notes))

    def test_a_policy_that_adopts_a_write_is_still_stopped_by_the_host(self):
        class AdoptsEverything(TriagePolicy):
            def decide(self, s):
                last = s.latest
                if isinstance(last, ModelOutcome) and last.proposal and (spec := s.tool(last.proposal.tool)):
                    if not s.attempted(last.proposal.tool, last.proposal.arguments):
                        return Decision(op_for(spec), "adopt whatever the model asks for", target=spec.id,
                                        arguments=dict(last.proposal.arguments), adopted_from=last.id)
                return super().decide(s)

        turn = NativeTurn(calls=(call("rollback_deploy"),))
        result, runtime, host, port = run(turn, final(), policy=AdoptsEverything())
        write = [r for r in host.receipts if r.tool == "rollback_deploy"]
        self.assertEqual([(r.status, r.proposed_by) for r in write], [("rejected", "turnwise_policy")])
        self.assertIn("not requested by the user", write[0].reason)
        self.assertEqual(host.write_ledger, [])
        if len(port.seen) > 1:  # if the policy called the model again, it was told what the host did
            self.assertEqual(json.loads(port.seen[1]["answers"]["c_rollback_deploy"].text)["status"], "rejected")

    def test_an_adoption_that_does_not_match_the_proposal_is_rejected_by_the_host_and_nothing_runs(self):
        class AltersTheArguments(TriagePolicy):
            def decide(self, s):
                d = super().decide(s)
                if d.adopted_from:  # claims to adopt the model's call, but for another service
                    return Decision(d.op, d.reason, target=d.target, arguments={"service": "auth"},
                                    adopted_from=d.adopted_from)
                return d

        result, runtime, host, port = run(NativeTurn(calls=(call("validate_config"),)), policy=AltersTheArguments())
        self.assertEqual([r.tool for r in host.receipts], ["error_trend", "recent_deploys"])
        self.assertEqual((result.counts["rejected"], runtime._adopted), (1, {}))
        self.assertIn("claims to adopt", " ".join(row.host for row in result.rows))

    def test_arguments_that_are_not_a_json_object_are_declined_without_asking_the_policy(self):
        turn = NativeTurn(calls=(call("validate_config", call_id="c_bad", raw='{"service": checkout'),
                                 call("validate_config", call_id="c_good")))
        result, runtime, host, port = run(turn, final())
        self.assertEqual(result.status, "finished")
        self.assertEqual((runtime.outcomes[0].kind, runtime.proposals_considered), ("invalid", 1))
        self.assertEqual([r.tool for r in host.receipts].count("validate_config"), 1)
        answers = port.seen[1]["answers"]
        self.assertEqual((answers["c_bad"].adopted, answers["c_good"].adopted), (False, True))
        self.assertIn("not a JSON object", answers["c_bad"].text)

    def test_the_proposal_budget_counts_every_tool_call(self):
        calls = tuple(call("search_docs", {"query": f"runbook {i}"}, call_id=f"c{i}") for i in range(4))
        result, runtime, host, port = run(NativeTurn(calls=calls), final(), max_proposals=2)
        self.assertEqual((runtime.proposals_seen, runtime.proposals_considered, runtime.proposals_declined), (4, 2, 2))
        self.assertEqual([r.tool for r in host.receipts].count("search_docs"), 2)
        self.assertEqual(result.counts["model_tool_calls_returned_as_proposals"], 4)
        over = [a.text for a in port.seen[1]["answers"].values() if not a.adopted]
        self.assertTrue(over and all("proposal budget exhausted" in text for text in over))

    def test_the_tool_budget_still_applies_to_adoptions(self):
        turn = NativeTurn(calls=(call("validate_config"), call("service_health")))
        result, runtime, host, port = run(turn, final(), budget=Budget(max_tool_calls=3))
        self.assertEqual(result.status, "finished")
        self.assertEqual([r.tool for r in host.receipts], ["error_trend", "recent_deploys", "validate_config"])
        self.assertIn("tool budget exhausted", port.seen[1]["answers"]["c_service_health"].text)

    def test_a_terminal_decision_ends_the_consideration_phase(self):
        calls = (call("validate_config", call_id="c1"), call("validate_config", call_id="c2"),
                 call("service_health", call_id="c3"))
        result, runtime, host, port = run(NativeTurn(calls=calls))
        # The second call repeats the first: TriagePolicy stops the run. The third is never considered or run.
        self.assertEqual(result.status, "held")
        self.assertEqual([r.tool for r in host.receipts], ["error_trend", "recent_deploys", "validate_config"])
        self.assertEqual(runtime.proposals_considered, 2)
        self.assertEqual(len(port.seen), 1)

    def test_a_failed_model_call_is_an_observation_and_is_not_retried_after_a_provider_failure(self):
        result, runtime, host, port = run(ModelCallFailed("provider error HTTP 429", "rate limit reached"))
        self.assertEqual((result.status, len(port.seen)), ("held", 1))
        self.assertTrue(runtime.outcomes[0].provider_rate_limited)
        self.assertIn("Provider unavailable", result.answer)

    def test_a_retry_after_a_model_error_resends_the_same_answers(self):
        turns = (NativeTurn(calls=(call("validate_config"),)), ModelCallFailed("invalid structured output", "x"), final())
        result, runtime, host, port = run(*turns)
        self.assertEqual((result.status, len(port.seen)), ("finished", 3))
        self.assertEqual(port.seen[1]["answers"], port.seen[2]["answers"])  # nothing was lost or answered twice
        self.assertEqual([r.tool for r in host.receipts].count("validate_config"), 1)

    def test_the_first_message_carries_the_context_and_later_calls_carry_only_what_is_new(self):
        result, runtime, host, port = run(NativeTurn(calls=(call("validate_config"),)), final())
        first, second = port.seen
        lines = first["first_message"].split("\n")
        self.assertEqual((lines[0], [json.loads(x)["receipt"] for x in lines[1:]]), (INVESTIGATE, ["r1", "r2"]))
        self.assertEqual((first["answers"], first["host_results"]), ({}, []))
        # r3 answers the model's own call, so it is not also sent as a host result.
        self.assertEqual((second["first_message"], second["host_results"]), ("", []))
        self.assertEqual(runtime.outcomes[-1].shown, ("r1", "r2", "r3"))  # what the final answer may cite

    def test_the_tools_field_of_a_conversation_is_fixed(self):
        result, runtime, host, port = run(NativeTurn(calls=(call("validate_config"),)), final())
        self.assertEqual(port.seen[0]["offered"], ["service_health", "validate_config", "search_docs"])
        self.assertEqual(port.seen[1]["offered"], port.seen[0]["offered"])  # the policy narrowed may_propose; the field stays

    def test_a_wider_offer_than_the_conversation_started_with_is_refused_visibly_and_nothing_is_sent(self):
        class Widens(TriagePolicy):
            def decide(self, s):
                d = super().decide(s)
                if d.op.value == "CALL_HEAVY" and s.outcomes:
                    return Decision(d.op, d.reason, context=d.context, may_propose=("rollback_deploy",))
                return d

        result, runtime, host, port = run(final(kind="needs_evidence", cited=()), final(), policy=Widens())
        self.assertEqual(len(port.seen), 1)  # the second model call was never sent
        self.assertNotEqual(result.status, "finished")

    def test_an_unanswered_call_has_a_default_answer(self):
        self.assertTrue(NOT_CONSIDERED.startswith("declined by policy"))


# ================================================================ real SDK, simulated model
@unittest.skipUnless(FRAMEWORKS_PRESENT, "needs the pinned frameworks (pip install -r examples/architecture/requirements.txt)")
class SdkPortTests(unittest.TestCase):
    def run_b2(self, task=INVESTIGATE, models=None, **kwargs):
        from examples.architecture.openai_agents.models import choose_models
        from examples.architecture.openai_agents.native_intercept import run_native_intercept

        m = models or choose_models()
        host = kwargs.pop("host", None) or IncidentHost(task)
        result, runtime = run_native_intercept(task, m.heavy, m.light, model_label=m.label, host=host, **kwargs)
        return result, runtime, host, m

    @staticmethod
    def scripted(*responses):
        from agents.testing import ModelStep, ScriptedModel
        from examples.architecture.openai_agents.models import ModelChoice

        model = ScriptedModel([ModelStep.respond(r if callable(r) else (lambda c, r=r: r)) for r in responses])
        return ModelChoice(model, ScriptedModel([]), "SIMULATED scripted fixture", True)

    @staticmethod
    def answer(cited=("r1", "r2", "r3")):
        from agents.testing import assistant_message
        return [assistant_message(json.dumps({"kind": "answer_candidate", "text": "Plausibly yes.",
                                              "cited_receipts": list(cited)}), item_id="msg_fixture")]

    def test_same_outcome_as_turnwise_core_on_every_demo_task_with_one_model_call_per_decision(self):
        from examples.architecture.openai_agents.models import choose_models
        from examples.architecture.openai_agents.turnwise import run_turnwise

        for name, task in TASKS.items():
            m = choose_models()
            core, _ = run_turnwise(task, m.heavy, m.light, model_label=m.label)
            result, runtime, host, m2 = self.run_b2(task)
            self.assertEqual((result.status, result.answer), (core.status, core.answer), name)
            self.assertEqual(len(m2.heavy.calls) + len(m2.light.calls),
                             result.counts["model_calls_chosen_by_policy"], name)
            self.assertEqual(result.counts["model_calls_chosen_by_policy"],
                             core.counts["model_calls_chosen_by_policy"], name)
            self.assertEqual(runtime.model.unexpected_invocations, [], name)
            self.assertTrue(all(r.proposed_by == "turnwise_policy" for r in host.receipts), name)

    def test_the_model_gets_a_real_tools_field_an_appended_conversation_and_no_contradiction(self):
        result, runtime, host, m = self.run_b2(policy=playbook())
        calls = m.heavy.calls
        self.assertEqual(len(calls), 4)  # three proposals, one at a time, then the answer
        for c in calls:
            self.assertEqual([t.name for t in c.tools], ["service_health", "error_trend", "recent_deploys",
                                                         "validate_config", "search_docs"])  # fixed, no write
            self.assertEqual(c.output_schema.name(), "StepAnswer")
            self.assertEqual(c.system_instructions, AGENT_INSTRUCTIONS + "\n\n" + INTERCEPT_CONTRACT)
            self.assertNotIn("no tool is callable", c.system_instructions)
        for earlier, later in zip(calls, calls[1:]):  # append-only: each conversation extends the previous one
            before = earlier.input if isinstance(earlier.input, list) else [{"role": "user", "content": earlier.input}]
            self.assertEqual(later.input[:len(before)], before)
        outputs = [i["output"] for i in calls[-1].input if isinstance(i, dict) and i.get("type") == "function_call_output"]
        self.assertEqual([json.loads(o)["receipt"] for o in outputs], ["r1", "r2", "r3"])

    def test_a_declined_call_is_answered_on_the_wire_and_its_tool_never_runs(self):
        from agents.testing import function_call

        seen = []

        def second(c):
            seen.extend(i["output"] for i in c.input if isinstance(i, dict) and i.get("type") == "function_call_output")
            return self.answer()

        models = self.scripted([function_call("validate_config", SVC, call_id="c1"),
                                function_call("service_health", SVC, call_id="c2")], second)
        result, runtime, host, _ = self.run_b2(models=models, budget=Budget(max_tool_calls=3))
        self.assertEqual(result.status, "finished")
        self.assertEqual(json.loads(seen[0])["receipt"], "r3")
        self.assertTrue(seen[1].startswith("declined by policy: "))
        self.assertNotIn("service_health", [r.tool for r in host.receipts])
        self.assertEqual(runtime.model.unexpected_invocations, [])

    def test_several_calls_in_one_response_pause_the_sdk_before_any_tool_runs(self):
        from examples.architecture.openai_agents.models import choose_models

        models = choose_models(brain=SimulatedInvestigator(batch_reads=True))
        result, runtime, host, m = self.run_b2(models=models, policy=playbook())
        self.assertEqual((result.status, len(m.heavy.calls)), ("finished", 2))  # one batch of three, then the answer
        self.assertEqual(runtime.proposals_seen, 3)
        self.assertEqual([r.proposed_by for r in host.receipts], ["turnwise_policy"] * 3)
        self.assertEqual(runtime.model.unexpected_invocations, [])

    def test_host_results_obtained_between_model_calls_are_appended_as_labelled_messages(self):
        class ReadsHealthAfterTheFirstReply(TriagePolicy):
            def decide(self, s):
                if s.outcomes and not s.attempted("service_health", SVC) and not isinstance(s.latest, ModelOutcome):
                    return Decision(op_for(s.tool("service_health")), "the policy wants one more read",
                                    target="service_health", arguments=SVC)
                return super().decide(s)

        result, runtime, host, m = self.run_b2(policy=ReadsHealthAfterTheFirstReply())
        last = m.heavy.calls[-1].input
        notes = [i["content"] for i in last if isinstance(i, dict) and i.get("role") == "user"
                 and str(i.get("content", "")).startswith(HOST_RESULTS)]
        self.assertEqual(len(notes), 1)
        self.assertEqual(json.loads(notes[0].split("\n")[1])["tool"], "service_health")

    def test_a_call_to_a_tool_that_was_not_offered_never_reaches_the_host(self):
        from examples.architecture.openai_agents.models import choose_models

        result, runtime, host, m = self.run_b2(models=choose_models(brain=SimulatedInvestigator(rogue_write=True)))
        self.assertEqual(result.status, "held")
        self.assertNotIn("rollback_deploy", [r.tool for r in host.receipts])
        self.assertEqual((host.write_ledger, result.writes_executed), ([], 0))
        # The SDK refuses a call to a tool the agent does not have: a failed model call, visible to the policy.
        self.assertTrue(any(o.kind == "invalid" and "rollback_deploy not found" in o.note for o in runtime.outcomes))
        self.assertLessEqual(len(m.heavy.calls), Budget().max_model_calls)

    def test_an_inert_tool_invoked_with_no_host_result_executes_nothing_and_trips_the_wire(self):
        from examples.architecture.openai_agents.conventional import build_agent
        from examples.architecture.openai_agents.models import choose_models
        from examples.architecture.openai_agents.native_intercept import NO_HOST_RESULT, OpenAIAgentsInterceptPort

        m, host = choose_models(), IncidentHost(INVESTIGATE)
        port = OpenAIAgentsInterceptPort(build_agent(m.heavy), host, light_model=m.light, label=m.label)
        tool = port._inert_tool(host.tools[0])
        self.assertTrue(tool.needs_approval)

        class Ctx:
            tool_call_id = "call_never_decided"

        self.assertEqual(asyncio.run(tool.on_invoke_tool(Ctx(), json.dumps(SVC))), NO_HOST_RESULT)
        self.assertEqual((host.receipts, host.write_ledger), ([], []))
        self.assertEqual(port.unexpected_invocations, [f"{host.tools[0].id}:call_never_decided"])

    def test_the_demo_flag_is_opt_in_and_leaves_the_default_output_unchanged(self):
        from examples.architecture import run_demo

        def output(*argv):
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                run_demo.main(["--brief", *argv])
            return buffer.getvalue()

        default, extra = output(), output("--native-intercept")
        self.assertNotIn("native-intercept", default)
        self.assertTrue(extra.startswith(default.rstrip("\n")))
        self.assertIn("B' native-intercept port (SIMULATED, ablation, no efficacy claim): finished", extra)
        with self.assertRaises(SystemExit) as refused:
            run_demo.main(["--brief", "--native-intercept", "--framework", "llamaindex"])
        self.assertIn("OpenAI Agents SDK pair only", str(refused.exception))


@unittest.skipUnless(FRAMEWORKS_PRESENT, "needs the pinned frameworks (pip install -r examples/architecture/requirements.txt)")
class WireAndReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from examples.architecture import intercept_structure

        def deny(*args, **kwargs):
            raise AssertionError("the report attempted a network connection")

        cls.module = intercept_structure
        with mock.patch.object(socket.socket, "connect", deny), mock.patch.object(socket.socket, "connect_ex", deny):
            cls.report = intercept_structure.build_report()

    def arms(self, k):
        return {a["arm"]: a for a in self.report["turnwise_by_k"][str(k)]}

    def test_every_arm_ran_offline_through_the_real_provider_classes_and_passed(self):
        self.assertFalse(self.report["real_inference"])
        self.assertIn("SIMULATED", self.report["label"])
        self.assertEqual([a["arm"] for a in self.report["native"]], ["A", "A'", "S"])  # S next to A and Core (#88)
        self.assertEqual({a["verdict"] for a in self.report["native"]}, {"PASS"})
        for k in self.module.KS:
            arms = self.arms(k)
            self.assertEqual(list(arms), ["B", "B' seq", "B' batch"])
            self.assertEqual({a["verdict"] for a in arms.values()}, {"PASS"}, k)
            for arm in arms.values():  # the same three reads reached the host under every port
                self.assertEqual(sorted(arm["host_tool_calls"]), ["error_trend", "recent_deploys", "validate_config"])
                self.assertEqual((arm["model_proposals"], arm["proposals_adopted"]), (k, k), (k, arm["arm"]))

    def test_request_counts_follow_from_how_the_model_asks_not_from_who_controls(self):
        for k in self.module.KS:
            arms = self.arms(k)
            self.assertEqual(arms["B"]["requests"], k + 1)  # one proposal per typed step
            self.assertEqual(arms["B' seq"]["requests"], k + 1)  # a model that asks for one tool at a time
            self.assertEqual(arms["B' batch"]["requests"], 2)  # all proposals in one response, then the answer
            self.assertEqual(arms["B"]["max_tool_calls_per_response"], 0)
            self.assertEqual(arms["B' batch"]["max_tool_calls_per_response"], k)

    def test_the_appended_conversation_reuses_more_prefix_than_the_rebuilt_packet(self):
        for k in self.module.KS:
            arms = self.arms(k)
            for variant in ("B' seq", "B' batch"):
                self.assertGreater(arms[variant]["min_later_prefix_share"], arms["B"]["min_later_prefix_share"], (k, variant))
            self.assertGreaterEqual(arms["B' seq"]["min_later_prefix_share"], 0.7, k)

    def test_the_predeclared_offline_conditions_are_evaluated_as_written(self):
        check = self.report["predeclared_offline_check"]
        self.assertEqual((check["B' seq"]["adopt_condition_met"], check["B' batch"]["adopt_condition_met"]), (False, True))
        self.assertEqual((check["B' seq"]["keep_b_condition_met"], check["B' batch"]["keep_b_condition_met"]), (False, False))
        self.assertIn("INCONCLUSIVE offline", check["reading"])

    def test_costs_are_never_a_guess_reported_as_zero_and_the_report_says_what_it_is_not(self):
        for arm in [*self.report["native"], *(a for k in self.module.KS for a in self.arms(k).values())]:
            self.assertTrue(all(v is not None and v > 0 for v in arm["usd"].values()), arm["arm"])
        text = self.module.render(self.report)
        for needle in ("SIMULATED, structural", "NOT a cost measurement", "INCONCLUSIVE offline",
                       "No model call executed anything.", "Nothing here measures answer quality"):
            self.assertIn(needle, text)

    def run_with_faults(self, *faults):
        from examples.architecture.openai_agents.models import choose_models
        from examples.architecture.openai_agents.native_intercept import run_native_intercept
        from examples.architecture.provider import DOUBLE_SOURCE, ProviderLedger, ProviderSettings, ProviderSetup
        from examples.architecture.provider_double import ProviderDouble

        settings = ProviderSettings(model="gpt-6.1-sol")
        ledger = ProviderLedger(source=DOUBLE_SOURCE, max_requests=6, max_output_tokens=settings.max_output_tokens)
        double = ProviderDouble(SimulatedInvestigator(), faults=list(faults))
        m = choose_models(provider=ProviderSetup(settings, ledger, double.transport()))
        host = IncidentHost(INVESTIGATE)
        result, runtime = run_native_intercept(INVESTIGATE, m.heavy, m.light, model_label=m.label,
                                               model_settings=m.settings, host=host, ledger=ledger)
        return result, runtime, host, double

    def test_provider_faults_stay_visible_and_execute_nothing(self):
        result, runtime, host, double = self.run_with_faults("http_429")
        self.assertEqual((result.status, len(double.requests)), ("held", 1))  # no retry after a provider failure
        for fault in ("not_json", "schema_violation", "refusal", "unknown_tool", "write_call"):
            result, runtime, host, double = self.run_with_faults(fault)
            self.assertEqual(runtime.outcomes[0].kind, "invalid", fault)
            self.assertNotIn("rollback_deploy", [r.tool for r in host.receipts], fault)
            self.assertEqual((host.write_ledger, runtime.model.unexpected_invocations), ([], []), fault)

    def test_a_call_with_broken_arguments_is_declined_and_the_run_goes_on(self):
        result, runtime, host, double = self.run_with_faults("bad_arguments")
        self.assertEqual(runtime.outcomes[0].kind, "invalid")
        self.assertEqual(result.status, "finished")
        answered = [i.get("output") for i in double.requests[1]["input"] if isinstance(i, dict)
                    and i.get("type") == "function_call_output"]
        self.assertTrue(answered and "not a JSON object" in answered[0])


if __name__ == "__main__":
    unittest.main()
