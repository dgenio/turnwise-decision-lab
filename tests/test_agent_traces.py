"""Offline replay of the recorded v0.6 traces (no models needed).

The model outputs in reports/v06/traces were produced by real local inference.
CI cannot re-run that inference, so it does the next best thing: it feeds the
recorded decisions, context proposals and generations back into the real loop,
Host and world, and checks that every tool observation, final outcome and score
reproduces exactly. A trace that had been edited by hand, or that depended on
anything other than the deterministic host, would fail here.
"""
from __future__ import annotations

import json
from pathlib import Path
import unittest

from turnwise_lab.agent.bench import SETS, load_scenarios, score
from turnwise_lab.agent.contracts import ContextDecision, Decision
from turnwise_lab.agent.heavy_agent import run_heavy_agent
from turnwise_lab.agent.host import Host
from turnwise_lab.agent.loop import execute_user_turn
from turnwise_lab.agent.world import IncidentWorld
from turnwise_lab.local_models import Generation

ROOT = Path(__file__).resolve().parents[1]
TRACES = sorted((ROOT / "reports" / "v06" / "traces").glob("*/*.json"))
OUTCOME_FIELDS = ("success", "final_kind", "evidence_ok", "missing_facts", "silent_failure", "dropped_action", "false_clarify",
                  "wrong_argument_calls", "rejected_proposals", "forbidden_requested", "writes_executed", "tool_calls",
                  "heavy_calls", "light_calls", "under_provisioned", "unnecessary_heavy", "verification_requests")


class ReplayDecider:
    name = "replay"

    def __init__(self, steps):
        self.decisions = [s["decision"] for s in steps if s.get("decision")]

    def decide(self, state, host):
        d = self.decisions.pop(0)
        return Decision(d["operation"], d.get("target"), dict(d.get("arguments") or {}), d.get("model_tier"),
                        d.get("requires_continuation", False), provider="replay", model="recorded")


class ReplayContext:
    name = "replay"

    def __init__(self, steps):
        self.ctx = [s["context"]["decision"] for s in steps if s.get("context")]

    def select(self, state, tier, permitted):
        c = self.ctx.pop(0)
        return ContextDecision(list(c["proposed"]), c["policy"])


class ReplayGenerator:
    def __init__(self, steps):
        self.gens = [s["generation"] for s in steps if s.get("generation")]

    def generate(self, prompt, tier, max_new_tokens):
        return dict(self.gens.pop(0))


class ReplayLM:
    version, arch = "replay", "qwen3_5"

    def __init__(self, steps):
        self.gens = [s["generation"] for s in steps if s.get("generation")]

    def extend(self, text, state=None, past_len=0):
        return None, None, past_len

    def assistant_header(self):
        return ""

    def generate_continue(self, text, state, past, max_new_tokens=220):
        g = self.gens.pop(0)
        return Generation(g["text"], g["prompt_tokens"], g["completion_tokens"], 0.0, 0.0, g.get("stopped", "eos")), None, past


def _obs_key(o):
    return (o["operation"], o["target"], json.dumps(o["arguments"], sort_keys=True), o["status"],
            json.dumps(o["facts"], sort_keys=True))


@unittest.skipUnless(TRACES, "no recorded traces")
class TraceReplayTests(unittest.TestCase):
    def test_every_recorded_trace_replays_exactly(self):
        checked = 0
        for path in TRACES:
            data = json.loads(path.read_text())
            scen = {s["id"]: s for s in load_scenarios(SETS[data["set"]])}
            for t in data["traces"]:
                s = scen[t["scenario_id"]]
                host = Host(IncidentWorld(s["world_variant"]))
                if data["arm"] == "heavy_agent":
                    tr = run_heavy_agent(s["message"], host=host, lm=ReplayLM(t["steps"]), turn_id=s["id"],
                                         conversation=s.get("conversation", [])).as_json()
                else:
                    tr = execute_user_turn(s["message"], host=host, decider=ReplayDecider(t["steps"]),
                                           context=ReplayContext(t["steps"]), generator=ReplayGenerator(t["steps"]),
                                           turn_id=s["id"], arm=data["arm"], conversation=s.get("conversation", []),
                                           verification=data["arm"] != "rules").as_json()
                with self.subTest(arm=data["arm"], set=data["set"], scenario=s["id"]):
                    self.assertEqual([_obs_key(o) for o in tr["observations"]], [_obs_key(o) for o in t["observations"]])
                    self.assertEqual((tr["final"]["kind"], tr["final"]["text"]), (t["final"]["kind"], t["final"]["text"]))
                    tr["totals"] = {**t["totals"], "writes_executed": tr["totals"]["writes_executed"]}
                    replayed, recorded = score(s, tr), score(s, t)
                    # Tokens and latency are recorded measurements (not reproducible offline); everything that
                    # decides the outcome, the evidence, the counts and the safety result must reproduce exactly.
                    self.assertEqual({k: replayed[k] for k in OUTCOME_FIELDS}, {k: recorded[k] for k in OUTCOME_FIELDS})
                    self.assertEqual({k: v for k, v in t["score"].items() if k in recorded},
                                     {k: v for k, v in recorded.items() if k in t["score"]})
                checked += 1
        self.assertGreater(checked, 0)

    def test_recorded_traces_carry_provenance_and_real_decisions(self):
        for path in TRACES:
            data = json.loads(path.read_text())
            p = data["provenance"]
            self.assertIn("cpu", p)
            self.assertIn("recorded_at_utc", p)
            if data["arm"] in ("dm_dynamic", "dm_full", "dm_nogate", "dm_llm_args"):
                for t in data["traces"]:
                    for st in t["steps"]:
                        if st.get("decision"):
                            self.assertEqual(st["decision"]["provider"], "turnwise-dm")
                            q = st["decision"]["questions"][0]
                            self.assertTrue(q["scores"], "a learned decision must carry its scores")

    def test_showcase_investigation_has_three_real_decisions(self):
        path = ROOT / "reports" / "v06" / "traces" / "dev" / "dm_dynamic.json"
        if not path.exists():
            self.skipTest("dev traces not recorded")
        t = next(t for t in json.loads(path.read_text())["traces"] if t["scenario_id"] == "C-investigation")
        decs = [s["decision"] for s in t["steps"] if s.get("decision")]
        self.assertGreaterEqual(len(decs), 3)
        self.assertEqual([d["target"] or d["model_tier"] for d in decs[:3]],
                         ["get_error_metrics", "get_deployment_history", "heavy"])
        self.assertTrue(all(s["decision_call_id"].startswith("C-investigation/") for s in t["steps"]))
        # The second decision's state contained the first tool's output; the third, both.
        self.assertIn("errors:checkout", t["steps"][1]["snapshot"]["observations"][0])
        self.assertEqual(len(t["steps"][2]["snapshot"]["observations"]), 2)
        gen = next(s for s in t["steps"] if s.get("generation"))
        prompt = "\n".join(m["content"] for m in gen["context"]["assembled"]["messages"])
        self.assertIn("d-142", prompt)
        self.assertIn("6.4", prompt)


if __name__ == "__main__":
    unittest.main()


class QualityConstrainedViewTests(unittest.TestCase):
    """The post-hoc non-inferiority view (docs/quality-constrained-efficiency-v06.md) is computed, not typed."""

    def test_square_and_add_matches_newcombe_worked_example(self):
        # With no pairing (phi = 0) the interval reduces to Newcombe's hybrid score interval;
        # his worked example 56/70 vs 48/80 gives 0.0524 to 0.3339.
        import math
        from turnwise_lab.agent.bench import _wilson
        p1, p2 = 56 / 70, 48 / 80
        l1, u1 = _wilson(56, 70)
        l2, u2 = _wilson(48, 80)
        self.assertAlmostEqual(p1 - p2 - math.hypot(p1 - l1, u2 - p2), 0.0524, places=4)
        self.assertAlmostEqual(p1 - p2 + math.hypot(u1 - p1, p2 - l2), 0.3339, places=4)

    def test_paired_difference_counts_and_exact_mcnemar(self):
        from turnwise_lab.agent.bench import paired_difference
        x = [True] * 6 + [True] * 10 + [False] * 7 + [False] * 7
        y = [True] * 6 + [False] * 10 + [True] * 7 + [False] * 7
        r = paired_difference(x, y)
        self.assertEqual((r["both"], r["only_candidate"], r["only_reference"], r["neither"]), (6, 10, 7, 7))
        self.assertEqual(r["difference_pp"], 10.0)
        self.assertAlmostEqual(r["mcnemar_exact_p"], 0.629, places=3)  # 2 * P(Bin(17, .5) <= 7)
        self.assertLess(r["ci95_pp"][0], 0)
        self.assertGreater(r["ci95_pp"][1], 10.0)
        same = paired_difference([True, False] * 5, [True, False] * 5)
        self.assertEqual((same["difference_pp"], same["mcnemar_exact_p"]), (0.0, 1.0))

    def test_committed_report_never_claims_non_inferiority(self):
        summary = json.loads((ROOT / "reports" / "v06" / "summary.json").read_text())
        q = summary["quality_constrained"]
        self.assertEqual(q["reference"], "heavy_agent")
        for row in q["rows"]:
            if row["arm"] != "heavy_agent":
                self.assertTrue(row["quality_gate"].startswith("inconclusive"))
                self.assertEqual(row["margin_needed_pp"], round(max(0.0, -row["vs_reference"]["ci95_pp"][0]), 1))


class PostHocAuditTests(unittest.TestCase):
    """reports/v06/audit.* is computed from the recorded traces and never changes frozen scores."""

    def test_accounting_matches_the_benchmark_summary(self):
        from turnwise_lab.agent.audit import audit
        a = audit()
        summary = json.loads((ROOT / "reports" / "v06" / "summary.json").read_text())["sets"]["heldout"]
        for arm, acc in a["accounting"].items():
            self.assertAlmostEqual(acc["per_task_s"]["total"], summary[arm]["summary"]["local_compute_s_per_task"], places=1)
            pre = acc["heavy_generation_tokens_per_task_as_preregistered"] * acc["tasks"]
            self.assertAlmostEqual(pre, summary[arm]["summary"]["heavy_tokens"], delta=1)

    def test_packet_is_blinded_and_deterministic(self):
        from turnwise_lab.agent.audit import ADJ_ARMS, ADJ_TASKS, build_packet
        p1, k1 = build_packet()
        p2, k2 = build_packet()
        self.assertEqual((p1, k1), (p2, k2))
        self.assertEqual(len(p1["items"]), len(ADJ_ARMS) * len(ADJ_TASKS))
        text = json.dumps(p1).lower()
        for arm in ADJ_ARMS + ("turnwise", "decision model", "heavy-only"):
            self.assertNotIn(arm.lower(), text)
        self.assertEqual({(v["scenario"], v["arm"]) for v in k1.values()}, {(s, a) for s in ADJ_TASKS for a in ADJ_ARMS})

    def test_gate_diagnosis_and_taxonomy_are_consistent_with_scores(self):
        from turnwise_lab.agent.audit import audit
        a = audit()
        summary = json.loads((ROOT / "reports" / "v06" / "summary.json").read_text())["sets"]["heldout"]
        g = a["gate"]["dm_dynamic"]
        self.assertEqual(sum(b["tasks"] for b in g["bins"]), 30)
        self.assertEqual(sum(b["successes"] for b in g["bins"]), summary["dm_dynamic"]["summary"]["successes"])
        self.assertEqual(len(g["escalated"]), summary["dm_dynamic"]["summary"]["escalations"])
        for arm, t in a["taxonomy"].items():
            self.assertEqual(sum(t["counts"].values()), 30 - summary[arm]["summary"]["successes"])


class AdjudicationRecordTests(unittest.TestCase):
    """The committed blinded adjudication is complete, matches its key and its packet, and uses only rubric values."""

    def test_grades_key_and_packet_line_up(self):
        from turnwise_lab.agent.audit import ADJ, build_packet
        packet, key = build_packet()
        self.assertEqual(json.loads((ADJ / "packet.json").read_text()), json.loads(json.dumps(packet)))
        self.assertEqual(json.loads((ADJ / "key.json").read_text()), key)
        grades = json.loads((ADJ / "grades.json").read_text())["grades"]
        self.assertEqual([g["item"] for g in grades], sorted(key))
        allowed = {"outcome": {"correct", "partial", "incorrect"}, "causal_claim": {"none", "supported", "unsupported", "contradicted"},
                   "severity": {"none", "minor", "major", "critical"}, "acknowledges_missing_evidence": {"yes", "no", "na"},
                   "action_handling": {"raised", "raised_wrong", "dropped", "claimed_executed", "na"}}
        for g in grades:
            for field, values in allowed.items():
                self.assertIn(g[field], values, (g["item"], field))

    def test_audit_merges_every_graded_item(self):
        from turnwise_lab.agent.audit import ADJ_ARMS, ADJ_TASKS, audit
        adj = audit()["adjudication"]
        self.assertEqual(len(adj["rows"]), len(ADJ_ARMS) * len(ADJ_TASKS))
        for arm, p in adj["per_arm"].items():
            self.assertEqual(p["correct"] + p["partial"] + p["incorrect"], len(ADJ_TASKS))
