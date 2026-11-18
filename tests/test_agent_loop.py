"""v0.6 decision-driven loop: acceptance tests without any model (CI-safe).

The principal demonstration uses a real learned decision model (see
reports/v06/traces); these tests use scripted or rule-based deciders only to
pin the loop, host and context semantics deterministically.
"""
from __future__ import annotations

import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch

from turnwise_lab.agent.context import BLOCKS_BY_ID, assemble
from turnwise_lab.agent.contracts import ContextDecision, Decision, Observation
from turnwise_lab.agent.heavy_agent import run_heavy_agent
from turnwise_lab.agent.host import Host, Limits
from turnwise_lab.agent.loop import TurnState, execute_user_turn
from turnwise_lab.agent.providers import (ArgumentBuilder, HeuristicDecider, PendingGenerator, RuleContextSelector,
                                          ScriptedDecider, admissible, focus_services)
from turnwise_lab.agent.world import IncidentWorld

ROOT = Path(__file__).resolve().parents[1]
MSG_C = "Could the latest checkout deployment explain the increase in errors?"


def tool(target, **args):
    return Decision("call_tool", target, args)


class EchoGenerator:
    """Records the assembled prompt; 'generates' a fixed string."""

    def __init__(self, text="ok"):
        self.prompts, self.text = [], text

    def generate(self, prompt, tier, max_new_tokens):
        self.prompts.append(prompt)
        t = self.text(prompt) if callable(self.text) else self.text
        return {"status": "ok", "tier": tier, "model": "echo", "text": t, "prompt_tokens": prompt.tokens,
                "completion_tokens": 1, "prefill_ms": 0.0, "decode_ms": 0.0}


def run(decider, variant="baseline", message=MSG_C, gen=None, ctx="heuristic", **kw):
    host = Host(IncidentWorld(variant), limits=kw.pop("limits", None))
    gen = gen or EchoGenerator()
    tr = execute_user_turn(message, host=host, decider=decider, context=RuleContextSelector(ctx), generator=gen,
                           turn_id="T1", **kw)
    return tr, host, gen


class MultiDecisionTurnTests(unittest.TestCase):
    def test_three_decisions_tool_tool_heavy_in_one_turn(self):
        d = ScriptedDecider([tool("get_error_metrics", service="checkout"), tool("get_deployment_history", service="checkout"),
                             Decision("call_model", model_tier="heavy")])
        tr, host, gen = run(d)
        self.assertEqual(tr.totals["decision_calls"], 3)
        self.assertEqual({s["decision_call_id"].split("/")[0] for s in tr.steps}, {"T1"})  # one user turn
        self.assertEqual([s["decision"]["target"] or s["decision"]["model_tier"] for s in tr.steps],
                         ["get_error_metrics", "get_deployment_history", "heavy"])
        self.assertEqual(tr.final["kind"], "answer")

    def test_second_decision_sees_first_tool_output_and_third_sees_both(self):
        d = ScriptedDecider([tool("get_error_metrics", service="checkout"), tool("get_deployment_history", service="checkout"),
                             Decision("call_model", model_tier="heavy")])
        run(d)
        snaps = d.seen_snapshots
        self.assertEqual(snaps[0]["observations"], [])
        self.assertIn("errors:checkout", snaps[1]["observations"][0])
        self.assertIn("6.4", snaps[1]["observations"][0])
        self.assertEqual(len(snaps[2]["observations"]), 2)
        self.assertIn("d-142", snaps[2]["observations"][1])

    def test_different_observations_lead_to_different_decisions(self):
        # Same message and policy; only the world (tool output) differs.
        base, _, _ = run(HeuristicDecider(), "baseline")
        flat, _, _ = run(HeuristicDecider(), "errors_flat")
        nodep, _, _ = run(HeuristicDecider(), "no_recent_deploy")
        self.assertEqual(base.observations[0]["facts"]["errors:checkout"]["change_point"], "11:05")
        self.assertIsNone(flat.observations[0]["facts"]["errors:checkout"]["change_point"])
        self.assertEqual(nodep.observations[1]["facts"]["deploys:checkout"]["deploys"], [])

    def test_observation_dependent_decider_changes_path(self):
        def after_metrics(state):
            f = state.observations[-1].facts["errors:checkout"]
            return tool("get_deployment_history", service="checkout") if f["change_point"] else Decision("call_model", model_tier="light")
        mk = lambda: ScriptedDecider([tool("get_error_metrics", service="checkout"), after_metrics, Decision("call_model", model_tier="heavy")])
        base, _, _ = run(mk(), "baseline")
        flat, _, _ = run(mk(), "errors_flat")
        self.assertEqual(base.steps[1]["decision"]["target"], "get_deployment_history")
        self.assertEqual(flat.steps[1]["decision"]["model_tier"], "light")
        self.assertEqual(flat.totals["decision_calls"], 2)

    def test_final_prompt_reflects_collected_observations(self):
        d = ScriptedDecider([tool("get_error_metrics", service="checkout"), tool("get_deployment_history", service="checkout"),
                             Decision("call_model", model_tier="heavy")])
        _, _, gen = run(d)
        text = gen.prompts[0].text()
        self.assertIn("errors:checkout", text)
        self.assertIn("deploys:checkout", text)
        self.assertIn("d-142", text)
        self.assertIn(MSG_C, text)

    def test_light_model_then_tool_then_heavy(self):
        d = ScriptedDecider([Decision("call_model", model_tier="light", requires_continuation=True),
                             tool("get_service_health", service="checkout"), Decision("call_model", model_tier="heavy")])
        tr, _, gen = run(d, message="summarise the checkout situation")
        self.assertEqual([p.tier for p in gen.prompts], ["light", "heavy"])
        self.assertEqual(tr.observations[0]["status"], "generated")
        self.assertEqual(tr.final["kind"], "answer")

    def test_early_finish_with_verified_data_needs_no_model(self):
        d = ScriptedDecider([tool("get_service_health", service="checkout"), Decision("finish")])
        tr, _, gen = run(d, message="checkout status?")
        self.assertEqual(tr.final["kind"], "verified")
        self.assertIn("degraded", tr.final["text"])
        self.assertEqual(gen.prompts, [])


class TerminationTests(unittest.TestCase):
    def test_repeated_action_is_rejected_then_abstains(self):
        d = ScriptedDecider([tool("get_service_health", service="checkout")] * 5)
        tr, _, _ = run(d, message="checkout status?")
        self.assertEqual([s["validation"]["status"] for s in tr.steps], ["accepted", "rejected", "rejected", "rejected"])
        self.assertEqual(tr.final["kind"], "abstain")
        self.assertIn("repeated action", tr.steps[1]["validation"]["reason"])

    def test_invalid_operation_and_unknown_tool_and_bad_args_are_rejected(self):
        bad = [Decision("teleport"), tool("delete_database", service="checkout"), tool("get_service_health", service="mars"),
               tool("get_service_health", service="checkout", extra="x")]
        tr, _, _ = run(ScriptedDecider(bad))
        reasons = [s["validation"]["reason"] for s in tr.steps]
        self.assertIn("unknown operation", reasons[0])
        self.assertIn("unknown capability", reasons[1])
        self.assertIn("not one of", reasons[2])
        self.assertEqual(tr.final["kind"], "abstain")

    def test_step_limit(self):
        seq = [tool(t, service=s) for t in ("get_service_health", "get_error_metrics") for s in ("checkout", "payments", "search", "auth")]
        tr, _, _ = run(ScriptedDecider(seq), limits=Limits(max_steps=3))
        self.assertEqual(tr.final["kind"], "step_limit")
        self.assertEqual(len(tr.steps), 3)

    def test_provider_failure_abstains_without_guessing(self):
        tr, host, _ = run(ScriptedDecider([]))
        self.assertEqual(tr.final["kind"], "abstain")
        self.assertEqual(tr.observations, [])

    def test_transient_tool_error_then_retry(self):
        d = ScriptedDecider([tool("get_error_metrics", service="checkout"), tool("get_error_metrics", service="checkout"), Decision("finish")])
        tr, _, _ = run(d, variant="metrics_flaky", message="Show the checkout error trend")
        self.assertEqual([o["status"] for o in tr.observations], ["error", "ok"])
        self.assertEqual(tr.final["kind"], "verified")

    def test_retry_budget_is_bounded(self):
        w = IncidentWorld("metrics_flaky")
        w._flaky_remaining = 10
        host = Host(w)
        d = ScriptedDecider([tool("get_error_metrics", service="checkout")] * 6)
        tr = execute_user_turn(MSG_C, host=host, decider=d, context=RuleContextSelector("minimal"), generator=EchoGenerator(), turn_id="T")
        self.assertEqual(sum(o["status"] == "error" for o in tr.observations), 2)
        self.assertIn("retry budget", tr.steps[2]["validation"]["reason"])


class AuthorityTests(unittest.TestCase):
    def test_decision_cannot_execute_a_write(self):
        # A requested write is held for approval, never executed. (Before the write-intent gate this test proposed
        # the rollback on MSG_C, a causal question that requests no action; that proposal is now rejected, below.)
        tr, host, _ = run(ScriptedDecider([tool("rollback_deployment", service="checkout")]), message="Roll back checkout.")
        self.assertEqual(tr.final["kind"], "approval_required")
        self.assertEqual(host.world.write_ledger, [])
        self.assertEqual(tr.totals["writes_executed"], 0)

    def test_decision_cannot_request_approval_for_an_unrequested_write(self):
        tr, host, _ = run(ScriptedDecider([tool("rollback_deployment", service="checkout"), Decision("abstain")]))
        self.assertEqual(tr.observations[0]["status"], "rejected")
        self.assertTrue(tr.observations[0]["reason"].startswith("not_requested"))
        self.assertEqual(tr.final["denied_write_proposals"][0]["code"], "not_requested")
        self.assertEqual(host.world.write_ledger, [])

    def test_context_policy_cannot_add_forbidden_or_remove_mandatory_blocks(self):
        st = TurnState("T", "hello")
        p = assemble(st, "light", ["restricted_escalation_notes", "made_up_block"], Host(IncidentWorld()).permitted_blocks, "test")
        ids = [b["id"] for b in p.included]
        self.assertIn("core_instructions", ids)
        self.assertIn("safety_policy", ids)
        self.assertNotIn("restricted_escalation_notes", ids)
        self.assertIn({"id": "restricted_escalation_notes", "reason": "not_permitted"}, p.excluded)
        self.assertIn({"id": "made_up_block", "reason": "unknown_block"}, p.excluded)

    def test_heavy_agent_writes_are_approval_only(self):
        class FakeLM:
            version, arch = "fake", "qwen3_5"
            def __init__(self):
                self.n = 0
            def extend(self, text, state=None, past_len=0):
                return None, None, past_len + 100
            def assistant_header(self):
                return "<|im_start|>assistant\n"
            def generate_continue(self, text, state, past, max_new_tokens=160):
                from turnwise_lab.local_models import Generation
                self.n += 1
                out = ("<tool_call>\n<function=rollback_deployment>\n<parameter=service>\ncheckout\n</parameter>\n</function>\n</tool_call>"
                       if self.n == 1 else "I requested approval; nothing was rolled back.")
                return Generation(out, 10, 5, 0.0, 0.0, "eos"), None, past + 15
        host = Host(IncidentWorld())
        tr = run_heavy_agent("roll back checkout", host=host, lm=FakeLM(), turn_id="H")
        self.assertEqual(tr.observations[0]["status"], "approval_required")
        self.assertEqual(host.world.write_ledger, [])
        self.assertEqual(tr.totals["generation_calls"]["heavy"], 2)


class NativeToolFormatTests(unittest.TestCase):
    def test_parse_both_native_formats(self):
        from turnwise_lab.agent.heavy_agent import parse_call
        self.assertEqual(parse_call('{"name": "get_service_health", "arguments": {"service": "auth"}}'),
                         ("get_service_health", {"service": "auth"}))
        self.assertEqual(parse_call("<function=get_error_metrics>\n<parameter=service>\ncheckout\n</parameter>\n</function>"),
                         ("get_error_metrics", {"service": "checkout"}))
        self.assertEqual(parse_call("not a call"), (None, {}))


class ContextTests(unittest.TestCase):
    def test_greeting_prompt_is_minimal_and_investigation_prompt_has_evidence(self):
        d1 = ScriptedDecider([Decision("call_model", model_tier="light")])
        _, _, g1 = run(d1, message="Hi, how are you?")
        ids1 = [b["id"] for b in g1.prompts[0].included]
        self.assertNotIn("latest_tool_result", ids1)
        self.assertNotIn("runbook_snippets", ids1)
        d2 = ScriptedDecider([tool("get_error_metrics", service="checkout"), tool("get_deployment_history", service="checkout"),
                              Decision("call_model", model_tier="heavy")])
        _, _, g2 = run(d2)
        ids2 = [b["id"] for b in g2.prompts[0].included]
        self.assertIn("latest_tool_result", ids2)
        self.assertIn("earlier_tool_results", ids2)
        self.assertGreater(g2.prompts[0].tokens, g1.prompts[0].tokens)

    def test_budget_drops_lowest_priority_optional_blocks(self):
        st = TurnState("T", "x" * 2000)
        p = assemble(st, "light", ["tool_catalog", "response_style"], Host(IncidentWorld()).permitted_blocks, "t", budget=600)
        self.assertTrue(any(e["reason"] == "over_budget" for e in p.excluded))
        self.assertIn("core_instructions", [b["id"] for b in p.included])

    def test_secrets_are_redacted_in_recorded_prompt(self):
        st = TurnState("T", "my api_key=sk-abcdef123456 please")
        p = assemble(st, "light", [], Host(IncidentWorld()).permitted_blocks, "t")
        self.assertNotIn("sk-abcdef123456", p.text())
        self.assertEqual(p.redactions, 1)

    def test_verification_request_reenters_the_loop(self):
        def text(prompt):
            return "NEED_MORE_EVIDENCE: deployment history" if "deploys:checkout" not in prompt.text() else "d-142 explains it."
        d = ScriptedDecider([tool("get_error_metrics", service="checkout"), Decision("call_model", model_tier="heavy"),
                             tool("get_deployment_history", service="checkout"), Decision("call_model", model_tier="heavy")])
        tr, _, gen = run(d, gen=EchoGenerator(text), verification=True)
        self.assertEqual(tr.totals["verification_requests"], 1)
        self.assertEqual(tr.final["text"], "d-142 explains it.")
        self.assertIn("verification_protocol", [b["id"] for b in gen.prompts[0].included])


class ArgumentTests(unittest.TestCase):
    def test_deterministic_arguments_need_no_model(self):
        st = TurnState("T", "is payments healthy?")
        args, q = ArgumentBuilder().build("get_service_health", st)
        self.assertEqual(args, {"service": "payments"})
        self.assertIn("deterministic", q.note)

    def test_service_carried_from_trusted_state(self):
        st = TurnState("T", "and who owns it?", conversation=[{"role": "user", "content": "how is search?"}])
        self.assertEqual(focus_services(st), ["search"])

    def test_ambiguous_without_extractor_clarifies(self):
        st = TurnState("T", "can you check it?")
        args, q = ArgumentBuilder().build("get_service_health", st)
        self.assertIsNone(args)
        self.assertIn("clarify", q.note)

    def test_action_mask_removes_succeeded_calls(self):
        st = TurnState("T", "checkout?")
        self.assertNotIn("finish", admissible(st, "checkout"))
        st.observations.append(Observation(0, "c", "call_tool", "get_service_health", {"service": "checkout"}, "ok",
                                           facts={"health:checkout": {}}))
        allowed = admissible(st, "checkout")
        self.assertNotIn("get_service_health", allowed)
        self.assertIn("finish", allowed)


class NotHardCodedTests(unittest.TestCase):
    DEMO = ["Hi, how are you?", "What's the current health status of checkout?", MSG_C]

    def test_no_demo_sentence_in_decision_code_prompts_or_training_data(self):
        files = list((ROOT / "turnwise_lab" / "agent").glob("*.py")) + [ROOT / "fixtures" / "v06_dm_train.jsonl"]
        for f in files:
            if f.name in ("bench.py", "demo.py"):
                continue
            text = f.read_text(encoding="utf-8").lower()
            for s in self.DEMO:
                self.assertNotIn(s.lower(), text, f"{s!r} found in {f.name}")

    def test_paraphrases_follow_the_same_rule_path(self):
        a, _, _ = run(HeuristicDecider(), message="Is the recent checkout release to blame for the error spike?")
        b, _, _ = run(HeuristicDecider())
        path = lambda t: [s["decision"]["target"] or s["decision"]["model_tier"] for s in t.steps]
        self.assertEqual(path(a), path(b))


class RemoteAdapterTests(unittest.TestCase):
    def setUp(self):
        captured = self.captured = []

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                captured.append(body)
                if "questions" in body and isinstance(body["questions"], list):
                    resp = {"answers": [{"type": "choice", "name": "next_operation", "choice": "get_deployment_history",
                                         "probabilities": [{"value": "get_deployment_history", "probability": 0.8}], "confidence": 0.7}],
                            "model": "gpt-6-luna", "usage": {"input_tokens": 900, "output_tokens": 0}}
                else:
                    resp = {"choices": {"next_operation": {"choice": "get_error_metrics", "probabilities": {"get_error_metrics": 0.9}}}}
                data = json.dumps(resp).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass
        self.srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_port}/v1/decisions"

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()

    def test_openai_decisions_adapter_contract_and_spend_cap(self):
        from turnwise_lab.agent.remote import OpenAIDecisionsProvider
        with self.assertRaises(PermissionError):
            OpenAIDecisionsProvider(endpoint=self.url, api_key_env="TW_FAKE", spend_cap_usd=1.0)
        with patch.dict(os.environ, {"TW_FAKE": "k"}):
            with self.assertRaises(PermissionError):
                OpenAIDecisionsProvider(endpoint=self.url, api_key_env="TW_FAKE", allow_remote=True)
            p = OpenAIDecisionsProvider(endpoint=self.url, api_key_env="TW_FAKE", allow_remote=True, spend_cap_usd=0.01)
            st = TurnState("T", MSG_C)
            st.observations.append(Observation(0, "T/d1", "call_tool", "get_error_metrics", {"service": "checkout"}, "ok",
                                               facts={"errors:checkout": {"change_point": "11:05"}}))
            d = p.decide(st, Host(IncidentWorld()))
            body = self.captured[0]
            self.assertEqual(body["model"], "gpt-6-luna")
            self.assertEqual([i.get("type") for i in body["input"] if i.get("type")], ["function_call", "function_call_output"])
            self.assertEqual(d.target, "get_deployment_history")
            self.assertEqual(d.arguments, {"service": "checkout"})
            self.assertAlmostEqual(p.spend.spent_usd, 900 * 0.10 / 1e6)
            p.spend.cap_usd = p.spend.spent_usd
            with self.assertRaises(PermissionError):
                p.decide(st, Host(IncidentWorld()))
            self.assertEqual(len(self.captured), 1)  # the capped request was never sent

    def test_system_one_adapter_requires_price_and_opt_in(self):
        from turnwise_lab.agent.remote import SystemOneProvider
        with patch.dict(os.environ, {"TW_FAKE": "k"}):
            with self.assertRaises(PermissionError):
                SystemOneProvider(model="jev", endpoint=self.url, api_key_env="TW_FAKE", allow_remote=True, spend_cap_usd=1.0)
            p = SystemOneProvider(model="jev", endpoint=self.url, api_key_env="TW_FAKE", allow_remote=True, spend_cap_usd=1.0,
                                  price_per_input_token=1e-9)
            d = p.decide(TurnState("T", MSG_C), Host(IncidentWorld()))
            self.assertEqual(d.target, "get_error_metrics")
            self.assertIn("criteria", self.captured[0]["questions"]["next_operation"])


if __name__ == "__main__":
    unittest.main()
