"""Real-provider readiness of the architecture example, tested against a deterministic provider double.

The offline demo swaps the *model object* for a framework test double. These
tests instead run the classes a live run uses -- the Agents SDK's
``OpenAIResponsesModel`` over ``openai.AsyncOpenAI``, and LlamaIndex's
``OpenAIResponses`` -- and replace only the HTTP endpoint (``ProviderDouble``,
an ``httpx2.MockTransport`` speaking the Responses API wire format). No network,
no credentials, no inference. Socket connects are blocked for the whole module.

Sections follow the readiness questions: native tool calling (1), what a
Turnwise model step receives (2), proposals return to the policy (3), the
policy decides and the host validates (4), failures are visible (5), model
output never authorises a side effect (6), limits stop runaway execution (7),
parity and disclosed differences (8), and the bounded smoke harness.

Skipped when the frameworks are not installed, unless TURNWISE_REQUIRE_FRAMEWORKS=1.
"""
from __future__ import annotations

import io
import json
import os
import socket
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

try:
    import agents  # noqa: F401
    import llama_index.core  # noqa: F401
    import llama_index.llms.openai  # noqa: F401
    HAVE_FRAMEWORKS = True
except ImportError:
    if os.environ.get("TURNWISE_REQUIRE_FRAMEWORKS") == "1":
        raise
    HAVE_FRAMEWORKS = False

if HAVE_FRAMEWORKS:
    from examples.architecture import live_smoke
    from examples.architecture.incident_env import AGENT_INSTRUCTIONS, TASKS, TOOLS, IncidentHost
    from examples.architecture.policies import TriagePolicy
    from examples.architecture.provider import (DOUBLE_SOURCE, REAL_SOURCE, Prices, ProviderLedger, ProviderSettings,
                                                ProviderSetup)
    from examples.architecture.provider_double import PACKET_MARKER, ProviderDouble
    from examples.architecture.simulated_model import SimulatedInvestigator
    from examples.architecture.step_schema import StepOutcome
    from examples.architecture.turnwise_core import STEP_CONTRACT, Budget, ModelOutcome

REGISTERED = sorted(t.id for t in TOOLS) if HAVE_FRAMEWORKS else []
FRAMEWORKS = ("openai-agents", "llamaindex")
MODEL = "gpt-6.1-sol"


def _no_network(*args, **kwargs):
    raise AssertionError("provider-readiness tests must not open a network connection")


def setUpModule():
    if HAVE_FRAMEWORKS:
        for name in ("connect", "connect_ex"):
            patcher = mock.patch.object(socket.socket, name, _no_network)
            patcher.start()
            unittest.addModuleCleanup(patcher.stop)


def make_setup(double, *, max_requests=10, model=MODEL, prices=None, usd_cap=None, **settings):
    settings = ProviderSettings(model, **settings)
    ledger = ProviderLedger(source=DOUBLE_SOURCE, max_requests=max_requests, prices=prices, usd_cap=usd_cap,
                            max_output_tokens=settings.max_output_tokens)
    return ProviderSetup(settings, ledger, double.transport())


def conventional(framework, double, task=None, **kw):
    """Run A over the provider double. Returns (result or the exception it raised, host, setup)."""
    task = task or TASKS["investigate"]
    setup, host = make_setup(double, **kw), IncidentHost(task)
    try:
        if framework == "openai-agents":
            from examples.architecture.openai_agents.conventional import run_conventional
            from examples.architecture.openai_agents.models import choose_models
            m = choose_models(provider=setup)
            return run_conventional(task, m.heavy, model_label=m.label, model_settings=m.settings, host=host), \
                host, setup
        from examples.architecture.llamaindex.conventional import run_conventional
        from examples.architecture.llamaindex.models import choose_llms
        m = choose_llms(provider=setup)
        return run_conventional(task, m.heavy, model_label=m.label, host=host), host, setup
    except Exception as exc:  # noqa: BLE001 - the tests assert on it
        return exc, host, setup


def turnwise(framework, double, task=None, *, policy=None, budget=None, **kw):
    """Run B over the provider double. Returns (result, runtime, setup)."""
    task = task or TASKS["investigate"]
    setup = make_setup(double, **kw)
    budget = budget or Budget()
    if framework == "openai-agents":
        from examples.architecture.openai_agents.models import choose_models
        from examples.architecture.openai_agents.turnwise import run_turnwise
        m = choose_models(provider=setup)
        result, rt = run_turnwise(task, m.heavy, m.light, model_label=m.label, policy=policy, budget=budget,
                                  model_settings=m.settings, ledger=setup.ledger)
    else:
        from examples.architecture.llamaindex.models import choose_llms
        from examples.architecture.llamaindex.turnwise import run_turnwise
        m = choose_llms(provider=setup)
        result, rt = run_turnwise(task, m.heavy, m.light, model_label=m.label, policy=policy, budget=budget,
                                  ledger=setup.ledger)
    return result, rt, setup


def step_text(body):
    """The text of a Turnwise step request's user message (the context packet)."""
    user = next(i for i in body["input"] if isinstance(i, dict) and i.get("role") == "user")
    content = user["content"]
    return content if isinstance(content, str) else "".join(p.get("text", "") for p in content)


def instructions_of(body):
    parts = [body.get("instructions") or ""] + [
        (i["content"] if isinstance(i["content"], str) else "".join(p.get("text", "") for p in i["content"]))
        for i in body["input"] if isinstance(i, dict) and i.get("role") in ("system", "developer")]
    return "\n".join(p for p in parts if p)


def invalid_notes(rt):
    return [o.note for o in rt.outcomes if o.kind == "invalid"]


@unittest.skipUnless(HAVE_FRAMEWORKS, "openai-agents, llama-index-core and llama-index-llms-openai are needed")
class NativeToolCallingTests(unittest.TestCase):
    """1. The conventional agent uses the framework's native tool calling, on the provider wire format."""

    def test_conventional_agents_send_native_function_tools_and_feed_results_back(self):
        for framework in FRAMEWORKS:
            with self.subTest(framework):
                double = ProviderDouble()
                result, host, setup = conventional(framework, double)
                self.assertEqual(len(double.requests), 4)
                for body in double.requests:
                    self.assertEqual(sorted(t["name"] for t in body["tools"]), REGISTERED)
                    self.assertTrue(all(t["type"] == "function" for t in body["tools"]))
                    self.assertFalse((body.get("text") or {}).get("format"))
                # The framework appended the model's call and the host's result, paired by call id.
                second = [i for i in double.requests[1]["input"] if isinstance(i, dict)]
                call = next(i for i in second if i.get("type") == "function_call")
                output = next(i for i in second if i.get("type") == "function_call_output")
                self.assertEqual((call["name"], call["call_id"]), ("error_trend", output["call_id"]))
                self.assertEqual(json.loads(output["output"])["receipt"], "r1")
                self.assertEqual([(r.tool, r.status, r.proposed_by) for r in host.receipts],
                                 [(t, "executed", "llm") for t in ("error_trend", "recent_deploys", "validate_config")])
                self.assertTrue(result.answer.startswith("Plausibly yes."))
                self.assertEqual(result.writes_executed, 0)


@unittest.skipUnless(HAVE_FRAMEWORKS, "frameworks not installed")
class TurnwiseStepRequestTests(unittest.TestCase):
    """2. A Turnwise model operation receives the instructions, the selected evidence and the StepOutcome schema."""

    def test_step_requests_carry_instructions_packet_and_strict_schema_and_no_tools(self):
        expected_fields = set(StepOutcome.model_fields)
        for framework in FRAMEWORKS:
            with self.subTest(framework):
                double = ProviderDouble()
                result, rt, _ = turnwise(framework, double)
                self.assertEqual(len(double.requests), 2)  # exactly one provider request per CALL_HEAVY
                for body in double.requests:
                    self.assertFalse(body.get("tools"))
                    fmt = body["text"]["format"]
                    self.assertEqual((fmt["type"], fmt["strict"]), ("json_schema", True))
                    self.assertEqual(set(fmt["schema"]["properties"]), expected_fields)
                    self.assertEqual(set(fmt["schema"]["required"]), expected_fields)
                    self.assertFalse(fmt["schema"]["additionalProperties"])
                    instructions = instructions_of(body)
                    self.assertTrue(instructions.startswith(AGENT_INSTRUCTIONS))
                    self.assertIn(STEP_CONTRACT, instructions)
                text = step_text(double.requests[0])
                packet = json.loads(text.split(PACKET_MARKER, 1)[1] if PACKET_MARKER in text else text)
                self.assertEqual(packet["task"], TASKS["investigate"])
                self.assertEqual([e["receipt"] for e in packet["evidence"]], ["r1", "r2"])
                self.assertEqual(packet["evidence"][0], json.loads(rt.host.receipt("r1").for_model()))
                self.assertEqual([t["name"] for t in packet["tools_you_may_propose"]],
                                 ["service_health", "validate_config", "search_docs"])  # never the write tool
                self.assertEqual(result.status, "finished")


@unittest.skipUnless(HAVE_FRAMEWORKS, "frameworks not installed")
class ProposalReturnsToPolicyTests(unittest.TestCase):
    """3. A provider-format tool proposal comes back to the policy as data; nothing executes on the model's say-so."""

    def test_tool_proposal_is_an_observation_and_execution_follows_a_policy_decision(self):
        for framework in FRAMEWORKS:
            with self.subTest(framework):
                result, rt, _ = turnwise(framework, ProviderDouble())
                m1 = rt.outcomes[0]
                self.assertEqual((m1.kind, m1.proposal.tool), ("tool_proposal", "validate_config"))
                after = next(i for i, s in enumerate(rt.snapshots) if s.latest is not None and s.latest.id == "m1")
                self.assertIsInstance(rt.snapshots[after].latest, ModelOutcome)
                self.assertEqual(len(rt.snapshots[after].receipts), len(rt.snapshots[after - 1].receipts))
                self.assertIn("[adopts m1's proposal]", rt.rows[after].decision)
                self.assertEqual((rt.host.receipts[-1].tool, rt.host.receipts[-1].proposed_by),
                                 ("validate_config", "turnwise_policy"))
                self.assertTrue(live_smoke._proposals_returned_to_policy(rt))

    def test_a_function_call_returned_to_a_tool_less_step_executes_nothing(self):
        for framework in FRAMEWORKS:
            with self.subTest(framework):
                result, rt, _ = turnwise(framework, ProviderDouble(faults=["step_function_call"]))
                self.assertEqual(rt.outcomes[0].kind, "invalid")
                self.assertEqual([r.proposed_by for r in rt.host.receipts], ["turnwise_policy"] * len(rt.host.receipts))
                self.assertEqual(result.status, "finished")


@unittest.skipUnless(HAVE_FRAMEWORKS, "frameworks not installed")
class PolicyDecidesHostValidatesTests(unittest.TestCase):
    """4. The policy makes the next decision; the host validates it independently."""

    def test_policy_declines_a_write_proposal_and_decides_again(self):
        for framework in FRAMEWORKS:
            with self.subTest(framework):
                result, rt, _ = turnwise(framework, ProviderDouble(faults=["write_proposal"]))
                self.assertEqual(rt.outcomes[0].proposal.tool, "rollback_deploy")
                self.assertIn("declined m1's proposal rollback_deploy", rt.rows[3].why)
                self.assertNotIn("rollback_deploy", [r.tool for r in rt.host.receipts])
                self.assertEqual((result.status, result.writes_executed), ("finished", 0))

    def test_host_rejects_a_write_that_a_naive_policy_adopts(self):
        class AdoptEverything(TriagePolicy):
            def decide(self, s):
                last = s.latest
                if isinstance(last, ModelOutcome) and last.proposal and not s.attempted(last.proposal.tool,
                                                                                        last.proposal.arguments):
                    from examples.architecture.policies import op_for
                    from examples.architecture.turnwise_core import Decision
                    return Decision(op_for(s.tool(last.proposal.tool)), "adopt anything", target=last.proposal.tool,
                                    arguments=dict(last.proposal.arguments), adopted_from=last.id)
                return super().decide(s)

        for framework in FRAMEWORKS:
            with self.subTest(framework):
                result, rt, _ = turnwise(framework, ProviderDouble(faults=["write_proposal"]), policy=AdoptEverything())
                rollback = next(r for r in rt.host.receipts if r.tool == "rollback_deploy")
                self.assertEqual(rollback.status, "rejected")
                self.assertIn("write was not requested by the user", rollback.reason)
                self.assertEqual(result.writes_executed, 0)


@unittest.skipUnless(HAVE_FRAMEWORKS, "frameworks not installed")
class FailuresAreVisibleTests(unittest.TestCase):
    """5. Invalid structured output, bad tool arguments, provider errors, refusals and timeouts fail visibly."""

    TURNWISE_FAULTS = {
        "refusal": "refusal: I can't help with that request.",
        "not_json": "invalid structured output",
        "schema_violation": "invalid structured output",
        "step_function_call": "",  # framework-specific wording; asserted invalid below
        "incomplete": "incomplete response",
        "http_500": "provider error HTTP 500",
        "http_429": "provider error HTTP 429",
        "http_401": "provider error HTTP 401",
        "timeout": "timeout",
    }

    def test_turnwise_records_each_failure_as_an_invalid_observation_never_an_answer(self):
        for framework in FRAMEWORKS:
            for fault, expected in self.TURNWISE_FAULTS.items():
                with self.subTest(framework=framework, fault=fault):
                    double = ProviderDouble(faults=[fault])
                    result, rt, setup = turnwise(framework, double)
                    self.assertEqual(rt.outcomes[0].kind, "invalid")
                    self.assertTrue(invalid_notes(rt)[0].startswith("model call failed: " + expected),
                                    invalid_notes(rt)[0])
                    self.assertIn("m1 invalid", rt.rows[2].observation)  # in the trace
                    self.assertNotEqual(rt.rows[3].decision.split(" ")[0], "FINISH")  # never accepted
                    self.assertEqual(len(double.requests), rt._model_calls)  # one request per call: no retries
                    self.assertEqual(result.writes_executed, 0)

    def test_conventional_provider_failures_raise_visibly_without_retries(self):
        expected = {"refusal": ("refusal", "refusal"), "http_500": ("provider error HTTP 500",) * 2,
                    "http_429": ("provider error HTTP 429",) * 2, "timeout": ("timeout",) * 2}
        for framework in FRAMEWORKS:
            for fault, categories in expected.items():
                with self.subTest(framework=framework, fault=fault):
                    double = ProviderDouble(faults=[fault])
                    outcome, host, setup = conventional(framework, double)
                    self.assertEqual(len(double.requests), 1)  # max_retries=0: no hidden second attempt
                    if framework == "llamaindex" and fault == "refusal":
                        # LlamaIndex's FunctionAgent ends a refused run as an ordinary, empty completion. Only the
                        # wire record shows the refusal; the smoke harness grades it from there.
                        self.assertEqual(outcome.answer, "")
                        self.assertIsNotNone(setup.ledger.exchanges[0].refusal())
                        continue
                    from examples.architecture.turnwise_core import describe_failure
                    self.assertIsInstance(outcome, Exception)
                    self.assertTrue(describe_failure(outcome).startswith(categories[0]), describe_failure(outcome))
                    self.assertEqual(host.receipts, [])

    def test_malformed_tool_arguments_reach_the_host_and_are_rejected(self):
        for framework in FRAMEWORKS:
            with self.subTest(framework):
                result, host, _ = conventional(framework, ProviderDouble(faults=["bad_arguments"]))
                first = host.receipts[0]
                self.assertEqual((first.tool, first.status), ("error_trend", "rejected"))
                self.assertIn("takes exactly one argument", first.reason)
                self.assertEqual(result.writes_executed, 0)

    def test_unknown_tool_names_never_reach_the_host(self):
        sdk, sdk_host, _ = conventional("openai-agents", ProviderDouble(faults=["unknown_tool"]))
        self.assertIsInstance(sdk, Exception)  # the SDK aborts the run (ModelBehaviorError)
        self.assertEqual(sdk_host.receipts, [])
        li, li_host, _ = conventional("llamaindex", ProviderDouble(faults=["unknown_tool"]))
        self.assertNotIn("delete_everything", [r.tool for r in li_host.receipts])  # error returned to the model
        self.assertEqual(li.writes_executed, 0)


@unittest.skipUnless(HAVE_FRAMEWORKS, "frameworks not installed")
class ModelOutputNeverAuthorisesTests(unittest.TestCase):
    """6. A model-proposed side effect never creates user authorisation."""

    def test_model_write_calls_and_proposals_are_rejected_or_declined(self):
        for framework in FRAMEWORKS:
            with self.subTest(framework):
                result, host, _ = conventional(framework, ProviderDouble(faults=["write_call"]))
                rollback = next(r for r in host.receipts if r.tool == "rollback_deploy")
                self.assertEqual(rollback.status, "rejected")
                self.assertIn("a proposal cannot authorise a side effect", rollback.reason)
                self.assertEqual(host.requested_writes, frozenset())
                self.assertEqual(result.writes_executed, 0)
                tw, rt, _ = turnwise(framework, ProviderDouble(faults=["write_proposal"]))
                self.assertEqual(rt.host.requested_writes, frozenset())
                self.assertEqual(tw.writes_executed, 0)

    def test_a_user_requested_write_is_held_never_executed_in_all_four_configurations(self):
        for framework in FRAMEWORKS:
            with self.subTest(framework):
                result, host, _ = conventional(framework, ProviderDouble(), task=TASKS["rollback"])
                self.assertEqual([r.status for r in host.receipts], ["held_for_approval"])
                self.assertEqual(result.writes_executed, 0)
                tw, rt, setup = turnwise(framework, ProviderDouble(), task=TASKS["rollback"])
                self.assertEqual((tw.status, tw.writes_executed, len(setup.ledger.exchanges)), ("held", 0, 0))


@unittest.skipUnless(HAVE_FRAMEWORKS, "frameworks not installed")
class LimitsTests(unittest.TestCase):
    """7. Step limits, model-call limits and the provider caps stop runaway execution."""

    def test_native_loops_stop_at_the_framework_step_limit(self):
        for framework in FRAMEWORKS:
            with self.subTest(framework):
                double = ProviderDouble(faults=["always_tool"] * 30)
                outcome, host, setup = conventional(framework, double, max_requests=30)
                self.assertIsInstance(outcome, Exception)
                from examples.architecture.turnwise_core import describe_failure
                self.assertTrue(describe_failure(outcome).startswith("framework step limit reached"),
                                describe_failure(outcome))
                self.assertEqual(len(double.requests), 10)  # max_turns / max_iterations = 10
                # The SDK runs the 10th turn's tool call before raising; LlamaIndex raises before running it.
                self.assertEqual(len(host.receipts), {"openai-agents": 10, "llamaindex": 9}[framework])
                self.assertTrue(all(r.status == "rejected" for r in host.receipts[8:]))  # the host's tool cap is 8
                self.assertEqual([r.status for r in host.receipts[:8]], ["executed"] * 8)

    def test_turnwise_model_calls_stop_at_the_budget(self):
        class EndlessProposals(SimulatedInvestigator):
            def __init__(self):
                super().__init__()
                self.n = 0

            def typed_step(self, packet):
                self.n += 1
                return {"kind": "tool_proposal", "text": "one more", "tool": "search_docs",
                        "arguments_json": json.dumps({"query": f"runbook {self.n}"}), "cited_receipts": []}

        for framework in FRAMEWORKS:
            for double in (ProviderDouble(brain=EndlessProposals()), ProviderDouble(faults=["not_json"] * 10)):
                with self.subTest(framework=framework):
                    result, rt, setup = turnwise(framework, double, budget=Budget(max_model_calls=3))
                    self.assertEqual(len(double.requests), 3)
                    self.assertEqual(result.status, "held")
                    self.assertLessEqual(len(rt.rows), Budget().max_steps)

    def test_request_cap_refuses_before_sending_and_halts_turnwise(self):
        for framework in FRAMEWORKS:
            with self.subTest(framework):
                double = ProviderDouble()
                result, rt, setup = turnwise(framework, double, max_requests=1)
                self.assertEqual(len(double.requests), 1)  # the second request was never sent
                self.assertEqual(result.status, "stopped")
                self.assertIn("provider request cap reached", result.answer)
                self.assertIn("[halted]", rt.rows[-1].short)
                self.assertEqual(len(setup.ledger.refused), 1)
                outcome, host, setup = conventional(framework, ProviderDouble(), max_requests=2)
                self.assertIsInstance(outcome, Exception)
                self.assertEqual(len(setup.ledger.exchanges), 2)
                self.assertIn("provider request cap reached", setup.ledger.refused[0])

    def test_spend_cap_refuses_a_request_that_could_exceed_the_authorisation(self):
        prices = Prices(input_per_mtok=2.0, output_per_mtok=10.0)
        for framework in FRAMEWORKS:
            with self.subTest(framework):
                _, _, probe = turnwise(framework, ProviderDouble(), prices=prices)
                first_bound = prices.cost(*probe.ledger.exchanges[0].bound_tokens)
                # The cap admits exactly the first request's bound. The second step's packet is larger (one more
                # receipt), so reserved cost + its bound exceeds the cap: refused before sending.
                double = ProviderDouble()
                result, rt, setup = turnwise(framework, double, prices=prices, usd_cap=first_bound)
                self.assertEqual(len(double.requests), 1)
                self.assertIn("authorised spend", result.answer)
                self.assertLessEqual(setup.ledger.spend_bound_usd(), first_bound)


    def test_http_errors_without_usage_keep_their_budget_reservation(self):
        # A 429/500 cannot prove zero billed usage. Reserve its pre-send bound
        # before allowing the next configuration or retry.
        import httpx2
        from examples.architecture.provider import ProviderCapReached
        prices = Prices(input_per_mtok=2.5, output_per_mtok=10.0)
        payload = json.dumps({"model": MODEL, "max_output_tokens": 2000}).encode()
        for status in (429, 500):
            with self.subTest(status=status):
                first = httpx2.Request("POST", "https://provider-double.invalid/v1/responses",
                                       content=payload)
                max_first = prices.cost(*live_smoke.request_bound(payload, 2000)) if hasattr(
                    live_smoke, "request_bound") else prices.cost(len(payload) + 512, 2000)
                ledger = ProviderLedger(source=DOUBLE_SOURCE, max_requests=2, prices=prices,
                                        usd_cap=max_first)
                ledger.admit(first)
                ledger.receive(httpx2.Response(status, json={"error": {"message": "provider error"}},
                                               request=first))
                self.assertEqual(ledger.reported_cost_usd(), 0.0)
                self.assertAlmostEqual(ledger.spend_bound_usd(), max_first)
                second = httpx2.Request("POST", "https://provider-double.invalid/v1/responses",
                                        content=payload)
                with self.assertRaises(ProviderCapReached):
                    ledger.admit(second)
                self.assertEqual(len(ledger.exchanges), 1)

    def test_provider_endpoint_is_checked_before_any_request_is_sent(self):
        import httpx2
        from examples.architecture.provider import ProviderCapReached
        ledger = ProviderLedger(source=REAL_SOURCE, max_requests=4)
        payload = json.dumps({"model": MODEL, "max_output_tokens": 2000}).encode()
        for target in ("http://api.openai.com/v1/responses",
                       "https://other.example/v1/responses",
                       "https://api.openai.com/v1/chat/completions"):
            with self.subTest(target=target):
                with self.assertRaises(ProviderCapReached) as ctx:
                    ledger.admit(httpx2.Request("POST", target, content=payload))
                self.assertIn("pinned Responses API", str(ctx.exception))
        self.assertEqual(ledger.exchanges, [])

    def test_spend_cap_prices_each_request_by_its_actual_size(self):
        # Review finding: a fixed 8,000-token assumption let a ~100k-token request through a $0.05 cap.
        import httpx2
        prices = Prices(input_per_mtok=2.5, output_per_mtok=10.0)
        ledger = ProviderLedger(source=DOUBLE_SOURCE, max_requests=10, prices=prices, usd_cap=0.05)
        huge = json.dumps({"model": MODEL, "max_output_tokens": 2000, "input": "x" * 400_000}).encode()
        with self.assertRaises(Exception) as ctx:
            ledger.admit(httpx2.Request("POST", "https://provider-double.invalid/v1/responses", content=huge))
        self.assertIn("authorised spend", str(ctx.exception))
        self.assertEqual(ledger.exchanges, [])

    def test_requests_without_the_configured_output_bound_are_refused_unsent(self):
        import httpx2
        ledger = ProviderLedger(source=DOUBLE_SOURCE, max_requests=10, max_output_tokens=2000)
        for body in ({"model": MODEL}, {"model": MODEL, "max_output_tokens": 50_000},
                     {"model": MODEL, "max_output_tokens": True}):
            with self.subTest(body=body), self.assertRaises(Exception) as ctx:
                ledger.admit(httpx2.Request("POST", "https://provider-double.invalid/v1/responses",
                                            content=json.dumps(body).encode()))
            self.assertIn("no output bound", str(ctx.exception))
        self.assertEqual(ledger.exchanges, [])

    def test_a_cap_refusal_is_reported_as_a_halt(self):
        from examples.architecture.turnwise_core import describe_failure
        outcome, _, _ = conventional("openai-agents", ProviderDouble(), max_requests=1)
        self.assertTrue(describe_failure(outcome).startswith("run halted"), describe_failure(outcome))


@unittest.skipUnless(HAVE_FRAMEWORKS, "frameworks not installed")
class ParityTests(unittest.TestCase):
    """8. Same model, settings and tool environment across all four configurations; differences are disclosed."""

    def test_all_configurations_send_the_same_model_and_model_settings(self):
        cases = [(dict(model="gpt-6.1-sol", reasoning_effort="low"), "reasoning", {"effort": "low"}),
                 (dict(model="gpt-4.1", temperature=0.0), "temperature", 0.0)]
        for settings, key, value in cases:
            with self.subTest(settings["model"]):
                bodies = []
                for framework in FRAMEWORKS:
                    for run in (conventional, turnwise):
                        double = ProviderDouble()
                        run(framework, double, max_output_tokens=1500, **settings)
                        bodies += double.requests
                self.assertEqual({b["model"] for b in bodies}, {settings["model"]})
                self.assertEqual({b.get("max_output_tokens") for b in bodies}, {1500})  # incl. LlamaIndex steps
                self.assertEqual({json.dumps(b.get(key)) for b in bodies}, {json.dumps(value)})

    def test_every_model_setting_matches_within_and_across_frameworks(self):
        # Review finding: only one key per case was compared. Compare them all, for the accepted settings.
        keys = ("model", "max_output_tokens", "temperature", "reasoning")
        for settings in (dict(model="gpt-6.1-sol"), dict(model="gpt-6.1-sol", reasoning_effort="low"),
                         dict(model="gpt-4.1", temperature=0.0), dict(model="gpt-4.1", temperature=0.7)):
            self.assertEqual(live_smoke.parity_problems(ProviderSettings(**settings)), [])
            sent = {}
            for framework in FRAMEWORKS:
                for run in (conventional, turnwise):
                    double = ProviderDouble()
                    run(framework, double, **settings)
                    sent[(framework, run.__name__)] = {json.dumps({k: b.get(k) for k in keys + ("top_p",)})
                                                       for b in double.requests}
            with self.subTest(**settings):
                self.assertEqual(sent[("llamaindex", "conventional")], sent[("llamaindex", "turnwise")])
                self.assertEqual(sent[("openai-agents", "conventional")], sent[("openai-agents", "turnwise")])
                strip = lambda rows: {json.dumps({k: json.loads(r)[k] for k in keys}) for r in rows}  # noqa: E731
                self.assertEqual(strip(sent[("openai-agents", "conventional")]),
                                 strip(sent[("llamaindex", "conventional")]))

    def test_harness_refuses_settings_the_frameworks_would_send_differently(self):
        for settings, fragment in ((dict(model="gpt-4.1"), "set --temperature explicitly"),
                                   (dict(model="gpt-6.1-sol", temperature=0.0), "drop --temperature"),
                                   (dict(model="gpt-4.1", temperature=0.0, reasoning_effort="low"),
                                    "drop --reasoning-effort")):
            with self.subTest(**settings):
                problems = live_smoke.parity_problems(ProviderSettings(**settings))
                self.assertTrue(any(fragment in p for p in problems), problems)

    def test_real_mode_pins_the_openai_endpoint_in_both_frameworks(self):
        # Review finding: OPENAI_BASE_URL / OPENAI_API_BASE could redirect a run labelled as real OpenAI inference.
        from examples.architecture.llamaindex.models import choose_llms
        from examples.architecture.openai_agents.models import choose_models
        env = {"OPENAI_API_KEY": "sk-not-used-ledger-cap-is-zero", "OPENAI_BASE_URL": "https://elsewhere.invalid/v1",
               "OPENAI_API_BASE": "https://another.invalid/v1"}
        with mock.patch.dict(os.environ, env):
            setup = ProviderSetup(ProviderSettings(MODEL), ProviderLedger(source=REAL_SOURCE, max_requests=0))
            sdk_model = choose_models(provider=setup).heavy
            li_llm = choose_llms(provider=setup).heavy
        self.assertEqual(str(sdk_model._client.base_url).rstrip("/"), "https://api.openai.com/v1")
        self.assertEqual(li_llm.api_base.rstrip("/"), "https://api.openai.com/v1")

    def test_native_agents_offer_equivalent_tool_schemas_on_the_wire(self):
        tools = {}
        for framework in FRAMEWORKS:
            double = ProviderDouble()
            conventional(framework, double)
            tools[framework] = {t["name"]: t["parameters"] for t in double.requests[0]["tools"]}
        for spec in TOOLS:
            sdk, li = tools["openai-agents"][spec.id], tools["llamaindex"][spec.id]
            self.assertEqual(sdk, spec.json_schema())  # the SDK sends the registry schema as is
            self.assertEqual(set(li["properties"]), set(sdk["properties"]))
            self.assertEqual(set(li["required"]), set(sdk["required"]))
            for name, definition in sdk["properties"].items():
                self.assertEqual(li["properties"][name].get("type"), definition.get("type"))
                self.assertEqual(li["properties"][name].get("enum"), definition.get("enum"))

    def test_disclosed_framework_differences_match_what_is_sent(self):
        """The guide's 'Provider path' table lists these; this test keeps it honest."""
        observed = {}
        for framework in FRAMEWORKS:
            conv, tw = ProviderDouble(), ProviderDouble()
            conventional(framework, conv)
            turnwise(framework, tw)
            c, t = conv.requests[0], tw.requests[0]
            observed[framework] = {
                "tool strict mode": sorted({str(x.get("strict")) for x in c["tools"]}),
                "store": c.get("store"),
                "instructions field": "instructions" if c.get("instructions") else "developer/system message",
                "step tool_choice": t.get("tool_choice"),
                "step schema name": t["text"]["format"]["name"],
            }
        self.assertEqual(observed["openai-agents"], {
            "tool strict mode": ["True"], "store": None, "instructions field": "instructions",
            "step tool_choice": None, "step schema name": "final_output"})
        self.assertEqual(observed["llamaindex"]["tool strict mode"], ["None"])  # not set: the API's non-strict default
        self.assertEqual(observed["llamaindex"]["store"], False)
        self.assertEqual(observed["llamaindex"]["step tool_choice"], "none")
        self.assertEqual(observed["llamaindex"]["step schema name"], "StepOutcome")

    def test_reasoning_items_round_trip_in_both_frameworks(self):
        # The double rejects a reasoning item echoed by id when store=false, like the real API. The SDK keeps the
        # API's default store and echoes the item; LlamaIndex sends store=false and drops reasoning items.
        for framework in FRAMEWORKS:
            with self.subTest(framework):
                result, host, _ = conventional(framework, ProviderDouble(reasoning_items=True))
                self.assertFalse(isinstance(result, Exception), result)
                self.assertEqual(len(host.receipts), 3)


@unittest.skipUnless(HAVE_FRAMEWORKS, "frameworks not installed")
class LiveSmokeHarnessTests(unittest.TestCase):
    """The bounded smoke harness: rehearsal against the double, refusal to spend without authorisation."""

    def test_rehearsal_runs_all_four_configurations_and_labels_them_simulated(self):
        report = live_smoke.run_matrix(ProviderSettings(MODEL), double=ProviderDouble())
        self.assertEqual(report["verdict"], "PASS", live_smoke.render(report))
        self.assertEqual((report["source"], report["real_inference"]), (DOUBLE_SOURCE, False))
        self.assertEqual([r["config"] for r in report["configs"]],
                         ["openai-agents / conventional", "openai-agents / turnwise",
                          "llamaindex / conventional", "llamaindex / turnwise"])
        for rec in report["configs"]:
            self.assertEqual(rec["source"], DOUBLE_SOURCE)
            self.assertEqual(rec["controller_changes"], 0)
        json.dumps(report)  # the JSON report is serialisable
        text = live_smoke.render(report)
        self.assertIn("PROVIDER DOUBLE (simulated responses; no inference performed)", text)
        self.assertIn("synthetic: provider double", text)

    def test_first_429_stops_all_further_transport_in_each_matrix_position(self):
        for pos, before in enumerate((0, 4, 6, 10)):
            with self.subTest(pos=pos):
                double = ProviderDouble(faults=[None] * before + ["http_429"])
                report = live_smoke.run_matrix(ProviderSettings(MODEL), double=double)
                self.assertEqual(len(double.requests), before + 1)
                self.assertEqual(len(report["configs"]), pos + 1)
                self.assertEqual(report["stop_reason"], "provider_http_429")
                self.assertEqual(report["verdict"], "INCONCLUSIVE")
                last = report["configs"][-1]
                self.assertEqual(last["provider_requests"][-1]["status"], 429)
                if last["architecture"] == "turnwise":
                    self.assertEqual(last["termination"]["status"], "held")
                    self.assertEqual(last["policy_observed_outcome_ids"][-1], last["typed_outcomes"][-1]["id"])

    def test_provider_failures_are_inconclusive_and_the_matrix_continues(self):
        report = live_smoke.run_matrix(ProviderSettings(MODEL), double=ProviderDouble(faults=["http_500"]))
        verdicts = [r["verdict"] for r in report["configs"]]
        self.assertEqual(verdicts[0], "INCONCLUSIVE")
        self.assertIn("provider error HTTP 500", report["configs"][0]["error"])
        self.assertEqual(report["verdict"], "INCONCLUSIVE")

    def test_a_refusal_hidden_by_the_framework_is_graded_from_the_wire(self):
        report = live_smoke.run_matrix(ProviderSettings(MODEL), double=ProviderDouble(faults=["refusal"]),
                                       configs=(("llamaindex", "conventional"),))
        rec = report["configs"][0]
        self.assertEqual(rec["termination"]["status"], "completed (FunctionAgent response)")
        self.assertEqual(rec["verdict"], "INCONCLUSIVE")
        self.assertIn("refusal", next(c["detail"] for c in rec["checks"] if c["check"].startswith("no refusal")))

    def test_mechanism_violations_are_failures(self):
        rec = {"architecture": "conventional", "writes_executed": 1, "provider_requests": [], "tool_calls": [
            {"proposed_by": "turnwise_policy", "status": "executed"}], "model_requested": MODEL, "request_cap": 10,
            "termination": {"status": "completed", "answer": "x"}}
        checks = live_smoke._checks(rec, None)
        failed = {c["check"] for c in checks if c["result"] == "fail"}
        self.assertIn("no write executed", failed)
        self.assertIn("every host receipt came from the model's own tool call", failed)
        self.assertEqual(live_smoke._verdict(checks, None), "FAIL")

    def _main(self, argv, env=None):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, env or {}, clear=False), redirect_stdout(out), redirect_stderr(err):
            try:
                code = live_smoke.main(argv)
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def test_paid_runs_refuse_without_model_prices_authorisation_or_key(self):
        paid = ["--provider", "openai", "--model", MODEL, "--input-usd-per-mtok", "2.5",
                "--output-usd-per-mtok", "10"]
        cases = [
            (["--provider", "openai"], {}, "explicit --model"),
            (["--provider", "openai", "--model", MODEL], {"OPENAI_API_KEY": "sk-present-but-not-authorisation"},
             "--authorize-usd"),
            (paid + ["--authorize-usd", "0.10"], {"OPENAI_API_KEY": "sk-present-but-not-authorisation"},
             "exceeds --authorize-usd"),
            (paid + ["--authorize-usd", "2"], {"OPENAI_API_KEY": ""}, "OPENAI_API_KEY is not set"),
        ]
        for argv, env, message in cases:
            with self.subTest(message):
                with mock.patch("examples.architecture.live_smoke.run_matrix") as run:
                    code, out, err = self._main(argv, env)
                    run.assert_not_called()
                self.assertEqual(code, 2)
                self.assertIn(message, err)

    def test_paid_gate_refuses_meaningless_numbers_and_divergent_settings(self):
        base = ["--provider", "openai", "--model", MODEL]
        env = {"OPENAI_API_KEY": "sk-present-but-not-authorisation"}
        cases = [
            (base + ["--input-usd-per-mtok", "0", "--output-usd-per-mtok", "0", "--authorize-usd", "0"], "positive"),
            (base + ["--input-usd-per-mtok", "-2", "--output-usd-per-mtok", "-10", "--authorize-usd", "1"],
             "positive"),
            (base + ["--max-output-tokens", "-100000"], "--max-output-tokens"),
            (base + ["--temperature", "0"], "drop --temperature"),
        ]
        for argv, message in cases:
            with self.subTest(message=message, argv=argv):
                with mock.patch("examples.architecture.live_smoke.run_matrix") as run:
                    code, out, err = self._main(argv, env)
                    run.assert_not_called()
                self.assertEqual(code, 2)
                self.assertIn(message, err)

    def test_exit_status_distinguishes_inconclusive_from_usage_errors(self):
        with mock.patch("examples.architecture.live_smoke.ProviderDouble",
                        side_effect=lambda *a, **k: ProviderDouble(faults=["http_500"])):
            code, out, err = self._main(["--configs", "openai-agents/conventional"])
        self.assertEqual(code, 3)
        self.assertIn("VERDICT: INCONCLUSIVE", out)

    def test_an_interrupted_run_keeps_the_partial_report(self):
        import tempfile
        real = live_smoke.run_config
        calls = {"n": 0}

        def interrupt_second(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                raise KeyboardInterrupt
            return real(*args, **kwargs)

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "report.json")
            with mock.patch("examples.architecture.live_smoke.run_config", side_effect=interrupt_second):
                code, out, err = self._main(["--out", path])
            with open(path, encoding="utf-8") as fh:
                saved = json.load(fh)
        self.assertEqual(code, 130)
        self.assertEqual((saved["verdict"], saved["complete"]), ("INTERRUPTED", False))
        self.assertEqual(saved["source"], DOUBLE_SOURCE)  # the header is there, not just a verdict
        self.assertEqual([r["config"] for r in saved["configs"]],
                         ["openai-agents / conventional", "openai-agents / turnwise"])
        self.assertEqual(saved["configs"][1]["verdict"], "INTERRUPTED")

    def test_an_interrupt_mid_configuration_keeps_the_requests_already_sent(self):
        # Review finding: Ctrl-C inside a configuration lost its requests, including one cut off in flight.
        class InterruptOnSecond(ProviderDouble):
            def handle(self, request):
                if len(self.requests) == 1:
                    self.requests.append({})
                    raise KeyboardInterrupt
                return super().handle(request)

        saved = {}
        with self.assertRaises(KeyboardInterrupt):
            live_smoke.run_matrix(ProviderSettings(MODEL), double=InterruptOnSecond(),
                                  on_record=lambda report: saved.update(json.loads(json.dumps(report))))
        rec = saved["configs"][0]
        self.assertEqual((saved["verdict"], rec["verdict"]), ("INTERRUPTED", "INTERRUPTED"))
        self.assertEqual(len(rec["provider_requests"]), 2)  # the completed one and the one cut off
        self.assertIsNone(rec["provider_requests"][1]["status"])

    def test_misconfigured_bounds_and_prices_fail_loudly(self):
        with self.assertRaises(ValueError):
            ProviderSetup(ProviderSettings(MODEL, max_output_tokens=4000),
                          ProviderLedger(source=DOUBLE_SOURCE, max_requests=1))  # ledger default 2000
        for bad in ((0, 10), (-2, -10)):
            with self.assertRaises(ValueError):
                Prices(*bad)
        with self.assertRaises(ValueError):
            live_smoke.run_matrix(ProviderSettings("gpt-4.1"), double=ProviderDouble())  # no explicit temperature

    def test_echoed_reasoning_items_widen_the_input_bound(self):
        # The SDK echoes reasoning items by id; their stored content may be billed as input but is not in the body.
        from examples.architecture.provider import request_bound
        plain = request_bound(b"x" * 1000, 2000)
        echoed = request_bound(b"x" * 1000, 2000, reasoning_refs=2)
        self.assertEqual(echoed[0] - plain[0], 4000)
        double = ProviderDouble(reasoning_items=True)
        _, _, setup = conventional("openai-agents", double)
        bounds = [e.bound_tokens[0] for e in setup.ledger.exchanges]
        self.assertGreater(bounds[1] - bounds[0], 2000)  # request 2 echoes rs_1

    def test_rehearsal_also_rejects_an_unsupported_model_before_any_request(self):
        with mock.patch("examples.architecture.live_smoke.run_matrix") as run:
            code, out, err = self._main(["--model", "gpt-6.2-sol"])
            run.assert_not_called()
        self.assertIn("does not support model 'gpt-6.2-sol'", str(code) + err)

    def test_plan_prints_the_worst_case_and_sends_nothing(self):
        with mock.patch("examples.architecture.live_smoke.run_matrix") as run:
            code, out, err = self._main(["--plan", "--provider", "openai", "--model", MODEL,
                                         "--input-usd-per-mtok", "2.5", "--output-usd-per-mtok", "10"])
            run.assert_not_called()
        self.assertEqual(code, 0)
        self.assertIn("max 28 provider requests in total", err)
        self.assertIn("= $1.1200", err)  # planning estimate: 28 x (8000 x $2.50 + 2000 x $10) / 1e6
        self.assertIn("hard bound", err)

    def test_preflight_rejects_a_model_id_a_framework_does_not_support_before_any_request(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-not-used-ledger-cap-is-zero"}), \
                self.assertRaises(SystemExit) as ctx:
            live_smoke._preflight(ProviderSettings("gpt-6.2-sol"))  # newer than llama-index-llms-openai 0.9.0
        self.assertIn("does not support model 'gpt-6.2-sol'", str(ctx.exception))

    def test_real_provider_setup_needs_a_key_and_never_falls_back_to_the_double(self):
        setup = ProviderSetup(ProviderSettings(MODEL), ProviderLedger(source=REAL_SOURCE, max_requests=0))
        self.assertFalse(setup.simulated)
        self.assertEqual(setup.base_url, "https://api.openai.com/v1")
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            with self.assertRaises(SystemExit):
                setup.api_key()

    def test_run_demo_live_redirects_to_the_bounded_harness(self):
        from examples.architecture import run_demo
        with self.assertRaises(SystemExit) as ctx:
            run_demo.main(["--live"])
        self.assertIn("live_smoke", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
