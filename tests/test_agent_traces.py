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
