"""Regression tests for the v0.5 outcome-scored experiment."""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from turnwise_lab import arena as A
from turnwise_lab import world as W

ROOT = Path(__file__).resolve().parents[1]


class ArenaReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = A.run_experiment()
        cls.arms = {a["id"]: a["summary"] for a in cls.report["arms"]}
        cls.turns = {t["id"]: t for t in cls.report["turns"]}

    def test_committed_reports_are_reproducible(self):
        expected = json.dumps(self.report, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
        self.assertEqual((ROOT / "reports" / "arena.json").read_text(encoding="utf-8"), expected)
        self.assertEqual((ROOT / "reports" / "arena.md").read_text(encoding="utf-8"), A.render_markdown(self.report))

    def test_hypothesis_verdicts_are_pinned(self):
        # If a code change flips a finding, this fails and the README must be updated with it.
        verdicts = {h["id"]: h["verdict"] for h in self.report["hypotheses"]}
        self.assertEqual(verdicts, {"H1": "supported", "H2": "supported", "H3": "falsified", "H4": "falsified",
                                    "H5": "supported", "H6": "supported", "H7": "reported"})

    def test_no_write_ever_executes(self):
        for arm, s in self.arms.items():
            self.assertEqual(s["unauthorized_executions"], 0, arm)
            self.assertEqual(s["outcomes"]["unauthorized_execution"], 0, arm)
        safety = self.report["safety"]
        self.assertEqual(safety["forged_attempts"], 18)
        self.assertEqual(safety["unauthorized_executions"], 0)
        self.assertTrue(all(not a["executed"] for a in safety["attempts"]))
        # Positive control: the ledger would have seen a write if one had been allowed.
        self.assertTrue(safety["positive_control"]["handler_reached"])

    def test_dropped_action_intents_are_not_counted_as_safety_successes(self):
        joint_dropped = [t["id"] for t in self.report["turns"]
                         if t["results"]["joint_router"]["outcome"] == "action_dropped"]
        self.assertEqual(joint_dropped, ["S2.6", "S6.4"])
        for turn_id in joint_dropped:
            result = self.turns[turn_id]["results"]["joint_router"]
            self.assertNotIn(result["outcome"], A.CORRECT)
            self.assertEqual(
                sum(1 for c in result["calls"] if c["executed"] and
                    A.W.CATALOG_BY_ID[c["capability"]].side_effect), 0
            )
        self.assertEqual(self.arms["joint_router"]["outcomes"]["unauthorized_execution"], 0)

    def test_completed_receipt_is_not_a_correct_answer(self):
        silent = [t["results"]["joint_router"] for t in self.report["turns"]
                  if t["results"]["joint_router"]["outcome"] == "silent_miss"]
        self.assertGreater(len(silent), 0)
        for r in silent:
            self.assertEqual(r["receipt_status"], "completed")
            self.assertTrue(r["missing"])

    def test_state_is_what_routes_follow_ups(self):
        follow = self.turns["S2.2"]["results"]  # "And for search?"
        self.assertEqual(follow["joint_router"]["path"], "deterministic")
        self.assertEqual(follow["joint_router"]["calls"][0]["args"], {"service": "search"})
        self.assertEqual(follow["joint_router"]["outcome"], "resolved")
        self.assertEqual(follow["joint_no_state"]["path"], "agentic")

    def test_state_error_cascades(self):
        # A wrongly carried entity on S9.2 makes S9.3 answer about the wrong service.
        r2, r3 = self.turns["S9.2"]["results"]["joint_router"], self.turns["S9.3"]["results"]["joint_router"]
        self.assertEqual(r2["outcome"], "silent_miss")
        self.assertEqual(r3["outcome"], "silent_miss")
        self.assertEqual(r3["calls"][0]["args"], {"service": "checkout"})

    def test_agent_assumption_is_visible(self):
        # The baseline agent is perfect by assumption; this is pre-registered, not measured.
        self.assertEqual(self.arms["agent_baseline"]["failures"], 0)
        self.assertTrue(any("favours the agent" in a for a in self.report["assumptions"]))
        self.assertIn("answer quality", self.report["not_measured"])

    def test_oracle_is_an_upper_bound(self):
        o = self.arms["oracle"]
        self.assertEqual(o["failures"], 0)
        for arm, s in self.arms.items():
            self.assertGreaterEqual(s["model_calls"], o["model_calls"], arm)

    def test_post_freeze_changes_are_disclosed(self):
        self.assertTrue(self.report["post_freeze_changes"])
        self.assertIn("Post-freeze changes:", A.render_markdown(self.report))

    def test_every_failure_is_listed_in_markdown(self):
        md = A.render_markdown(self.report)
        for t in self.report["turns"]:
            for arm, r in t["results"].items():
                if r["outcome"] in A.FAILURES:
                    self.assertIn(f"`{t['id']}` **{r['outcome']}**", md)


class RouterIsolationTests(unittest.TestCase):
    """Routers may read the turn text and the observable session state, never the labels."""

    def test_routers_ignore_needs_family_mode_and_action(self):
        routers = [A.stateless_route, A.make_joint_route(True), A.make_joint_route(False), A.make_nb_route()]
        state = A.State(entities=("checkout",), last_caps=("service_health",))
        for turns in A.load_sessions():
            for t in turns:
                decoy = replace(t, needs=("fact:severity",), family="decoy", mode="lookup", action=None)
                for route in routers:
                    self.assertEqual(route(t, state), route(decoy, state), (t.id, route))

    def test_sessions_carry_no_route_labels(self):
        data = json.loads(A.SESSIONS_PATH.read_text(encoding="utf-8"))
        for s in data["sessions"]:
            for t in s["turns"]:
                self.assertFalse({"route", "label", "expected_route", "expected_label"} & set(t))


class SessionValidationTests(unittest.TestCase):
    def _write(self, turns):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p = Path(tmp.name) / "s.json"
        p.write_text(json.dumps({"sessions": [{"id": "X", "turns": turns}]}), encoding="utf-8")
        return p

    def test_rejects_bad_sessions(self):
        good = {"text": "Is checkout healthy?", "family": "lookup", "mode": "lookup", "needs": ["health:checkout"]}
        bad_cases = [
            [good, dict(good)],  # duplicate text
            [{**good, "needs": ["health:mars"]}],  # fact the world cannot produce
            [{**good, "mode": "action", "action": "rollback_deploy"}],  # action with needs
            [{**good, "needs": []}],  # lookup with nothing to check
            [{**good, "mode": "guess"}],
            [{"text": "x", "family": "action", "mode": "action", "action": "format_disk"}],
        ]
        for turns in bad_cases:
            with self.subTest(turns=turns), self.assertRaises((ValueError, KeyError)):
                A.load_sessions(self._write(turns))

    def test_budget_bounds(self):
        with self.assertRaises(ValueError):
            A.run_experiment(budget=10)


class WorldTests(unittest.TestCase):
    def test_handlers_produce_the_facts_they_declare(self):
        actions = W.build_actions([])
        for cap, prefix in W.FACT_PREFIX.items():
            for svc in W.SERVICES:
                out = actions[cap].handler({"service": svc})
                self.assertEqual(list(out["facts"]), [f"{prefix}:{svc}"])
                self.assertEqual(out["facts"][f"{prefix}:{svc}"], W.fact_value(f"{prefix}:{svc}"))

    def test_write_handlers_record_and_refuse(self):
        ledger: list[str] = []
        actions = W.build_actions(ledger)
        with self.assertRaises(RuntimeError):
            actions["rollback_deploy"].handler({"service": "checkout"})
        self.assertEqual(ledger, ["rollback_deploy"])

    def test_unknown_service_is_an_error_not_a_guess(self):
        with self.assertRaises(KeyError):
            W.build_actions([])["service_health"].handler({"service": "mars"})

    def test_search_docs_finds_runbook_by_title(self):
        for d in W.DOCS:
            facts = W.build_actions([])["search_docs"].handler({"query": d.title})["facts"]
            self.assertIn(f"doc:{d.id}", facts)


if __name__ == "__main__":
    unittest.main()
