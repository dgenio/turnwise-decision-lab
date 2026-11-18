"""Hosted capable-agent adapter: exercised against a local fake server only. No hosted provider is ever called here."""
from __future__ import annotations

import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch

from turnwise_lab.agent.host import Host
from turnwise_lab.v07.gate import ExitGate
from turnwise_lab.v07.hosted import HostedChat, run_hosted_agent
from turnwise_lab.v07.world import StudyWorld

PRICES = dict(price_per_input_token=3e-6, price_per_output_token=15e-6)


def tool_call(name, **args):
    return {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


def serve(replies):
    received = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            body = json.dumps({"choices": [{"message": replies.pop(0)}],
                               "usage": {"prompt_tokens": 1000, "completion_tokens": 50, "prompt_tokens_details": {"cached_tokens": 800}}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, received, f"http://127.0.0.1:{srv.server_port}/v1/chat/completions"


class HostedAgentTests(unittest.TestCase):
    def chat(self, url, cap=1.0, **kw):
        with patch.dict(os.environ, {"FAKE_KEY": "k"}):
            return HostedChat(model="fake-capable", endpoint=url, api_key_env="FAKE_KEY", allow_remote=True, spend_cap_usd=cap, **{**PRICES, **kw})

    def test_nothing_is_sent_without_explicit_opt_in_cap_and_prices(self):
        with patch.dict(os.environ, {"FAKE_KEY": "k"}):
            for kw in (dict(allow_remote=False, spend_cap_usd=1.0, **PRICES), dict(allow_remote=True, spend_cap_usd=None, **PRICES),
                       dict(allow_remote=True, spend_cap_usd=1.0)):
                with self.assertRaises(PermissionError):
                    HostedChat(model="m", endpoint="https://example.invalid/v1/chat/completions", api_key_env="FAKE_KEY", **kw)

    def test_native_tool_calls_go_through_the_host_and_usage_is_costed(self):
        srv, received, url = serve([tool_call("get_error_metrics", service="checkout"), tool_call("rollback_deployment", service="checkout"),
                                    {"role": "assistant", "content": "Errors rose 0.4% to 6.4% at 11:05. I requested approval for the rollback; nothing was executed."}])
        try:
            host = Host(StudyWorld())
            tr = run_hosted_agent("check checkout errors and roll it back", host=host, chat=self.chat(url), turn_id="T")
        finally:
            srv.shutdown()
            srv.server_close()
        self.assertEqual([o["status"] for o in tr["observations"]], ["ok", "approval_required"])
        self.assertEqual(host.world.write_ledger, [])
        self.assertEqual(tr["totals"]["generation_cached_prompt_tokens"], 2400)
        self.assertAlmostEqual(tr["totals"]["provider_cost_usd"], 3 * (200 * 3e-6 + 800 * 3e-6 + 50 * 15e-6), places=8)
        self.assertEqual(received[0]["tools"][0]["type"], "function")

    def test_the_same_exit_gate_applies_to_a_hosted_agent(self):
        srv, received, url = serve([{"role": "assistant", "content": "The deploy caused it."},
                                    {"role": "assistant", "content": "Errors rose at 11:05, three minutes after d-142 at 11:02: consistent, not proven."}])
        try:
            tr = run_hosted_agent("did the checkout deploy cause the error spike?", host=Host(StudyWorld()), chat=self.chat(url), turn_id="T", gate=ExitGate())
        finally:
            srv.shutdown()
            srv.server_close()
        facts = {k for o in tr["observations"] if o["status"] == "ok" for k in o["facts"]}
        self.assertTrue({"errors:checkout", "deploys:checkout"} <= facts)
        self.assertIn("d-142", received[1]["messages"][-1]["content"])
        self.assertEqual(tr["final"]["kind"], "answer")
        self.assertEqual(tr["totals"]["gate_interventions"], 1)

    def test_contract_planner_can_delegate_untyped_requests_to_the_hosted_agent(self):
        from functools import partial
        from turnwise_lab.v07.controllers import run_contract_turn
        msg = "argh this whole morning has been a mess for the storefront folks, can you sort out whatever they need sorted"
        srv, received, url = serve([tool_call("page_oncall", service="checkout"),
                                    {"role": "assistant", "content": "I requested approval to page checkout on-call; nothing was executed."}])
        try:
            host = Host(StudyWorld())
            tr = run_contract_turn(msg, host=host, generator=None, heavy_lm=None, turn_id="T", fallback=partial(run_hosted_agent, chat=self.chat(url)))
        finally:
            srv.shutdown()
            srv.server_close()
        self.assertEqual(tr["plan"]["route"].split(":")[0], "delegate")
        self.assertEqual([o["status"] for o in tr["observations"]], ["approval_required"])
        self.assertEqual(len(received), 2)
        self.assertEqual(host.world.write_ledger, [])

    def test_spending_cap_stops_before_the_request_and_does_not_drop_the_action(self):
        srv, received, url = serve([])
        try:
            host = Host(StudyWorld())
            tr = run_hosted_agent("roll back checkout. now.", host=host, chat=self.chat(url, cap=1e-9), turn_id="T", gate=ExitGate())
        finally:
            srv.shutdown()
            srv.server_close()
        self.assertEqual(received, [], "nothing may be sent once the cap would be exceeded")
        self.assertEqual(tr["final"]["kind"], "approval_required")
        self.assertEqual(tr["totals"]["provider_cost_usd"], 0)
        self.assertEqual(host.world.write_ledger, [])


if __name__ == "__main__":
    unittest.main()
