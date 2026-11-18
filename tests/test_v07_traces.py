"""Offline replay and integrity checks for the recorded v0.7 traces (no models needed).

CI cannot re-run local inference. It does the next best thing: it feeds every
recorded model output (controller decisions, context proposals, generations)
back through the real loop, host, world, exit gate and contract planner, and
checks that every observation, every final reply and every score reproduces.
A hand-edited trace, or a gate whose behaviour depended on anything but its
inputs, fails here.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from turnwise_lab.agent.contracts import ContextDecision, Decision
from turnwise_lab.agent.heavy_agent import run_heavy_agent
from turnwise_lab.agent.host import Host
from turnwise_lab.agent.loop import execute_user_turn
from turnwise_lab.agent.providers import HeuristicDecider, RuleContextSelector
from turnwise_lab.local_models import Generation
from turnwise_lab.v07 import bench, microscope, report
from turnwise_lab.v07.controllers import run_contract_turn, run_gated_loop
from turnwise_lab.v07.gate import ExitGate
from turnwise_lab.v07.tasks import SETS, load_tasks, sha256
from turnwise_lab.v07.world import StudyWorld

ROOT = Path(__file__).resolve().parents[1]
TRACES = sorted((ROOT / "reports" / "v07" / "traces").glob("*/*.json"))
SCORE_FIELDS = ("success", "final_kind", "missing_facts", "silent_failure", "dropped_action", "serious_failure", "tool_calls",
                "heavy_calls", "light_calls", "gate_interventions", "writes_executed")


def _raw(g: dict) -> dict:
    g = dict(g)
    if "withheld_text" in g:
        g["text"] = g.pop("withheld_text")
    g.pop("grounding", None)
    return g


class ReplayInner:
    """The controller's own proposals, including the ones the gate replaced."""
    name, model = "replay", "recorded"

    def __init__(self, tr):
        blocked = {e["step_index"]: e["proposed"] for e in tr["totals"].get("gate_events", []) if e.get("action") != "allow" and "proposed" in e}
        self.seq = []
        for s in tr["steps"]:
            d = s.get("decision")
            if not d:
                continue
            if s["step_index"] in blocked:
                p = blocked[s["step_index"]]
                self.seq.append(Decision(p["operation"], p["target"], dict(p["arguments"]), p["model_tier"]))
            elif not d["provider"].startswith("exit-gate"):
                self.seq.append(Decision(d["operation"], d.get("target"), dict(d.get("arguments") or {}), d.get("model_tier"),
                                         d.get("requires_continuation", False)))

    def decide(self, state, host):
        return self.seq.pop(0)


class ReplayContext:
    name = "replay"

    def __init__(self, tr):
        self.ctx = [s["context"]["decision"] for s in tr["steps"] if s.get("context")]

    def select(self, state, tier, permitted):
        c = self.ctx.pop(0)
        return ContextDecision(list(c["proposed"]), c["policy"])


class ReplayGenerator:
    def __init__(self, tr):
        self.gens = [_raw(s["generation"]) for s in tr["steps"] if s.get("generation")]

    def generate(self, prompt, tier, max_new_tokens):
        return self.gens.pop(0)


class ReplayLM:
    version, arch = "replay", "qwen3_5"

    def __init__(self, tr):
        self.gens = [s["generation"] for s in tr["steps"] if s.get("generation")]

    def extend(self, text, state=None, past_len=0):
        return None, None, past_len

    def assistant_header(self):
        return ""

    def generate_continue(self, text, state, past, max_new_tokens=220):
        g = self.gens.pop(0)
        return Generation(g["text"], g["prompt_tokens"], g["completion_tokens"], 0.0, 0.0, g.get("stopped", "eos")), None, past


def replay(arm: str, task: dict, tr: dict) -> dict:
    host = Host(StudyWorld(task["world_variant"]))
    msg, convo, tid = task["message"], task["conversation"], task["id"]
    gated = arm.endswith("_gated")
    base = arm[:-6] if gated else arm
    if base == "heavy_agent":
        return run_heavy_agent(msg, host=host, lm=ReplayLM(tr), turn_id=tid, conversation=convo, gate=ExitGate() if gated else None, arm=arm).as_json()
    if base in ("contract", "contract_narrated"):
        return run_contract_turn(msg, host=host, generator=ReplayGenerator(tr), heavy_lm=ReplayLM(tr), turn_id=tid, conversation=convo,
                                 narrate=base == "contract_narrated", arm=arm)
    decider = HeuristicDecider() if base == "rules" else ReplayInner(tr)
    ctx = RuleContextSelector("heuristic") if base == "rules" else ReplayContext(tr)
    kw = dict(host=host, decider=decider, context=ctx, generator=ReplayGenerator(tr), turn_id=tid, arm=arm, conversation=convo,
              verification=base != "rules")
    return run_gated_loop(msg, **kw) if gated else execute_user_turn(msg, **kw).as_json()


def _obs(o):
    return (o["operation"], o["target"], json.dumps(o["arguments"], sort_keys=True), o["status"], json.dumps(o["facts"], sort_keys=True))


@unittest.skipUnless(TRACES, "v0.7 traces not recorded")
class ReplayTests(unittest.TestCase):
    def test_every_recorded_turn_reproduces_through_the_real_host_gate_and_planner(self):
        checked = 0
        for path in TRACES:
            data = json.loads(path.read_text())
            tasks = {t["id"]: t for t in load_tasks(SETS[data["set"]])}
            self.assertEqual(data["task_file_sha256"], sha256(SETS[data["set"]]), f"{path.name} was recorded on a different task file")
            for tr in data["traces"]:
                task = tasks[tr["scenario_id"]]
                where = f"{data['set']}/{data['arm']}/{task['id']}"
                again = replay(data["arm"], task, tr)
                self.assertEqual([_obs(o) for o in again["observations"]], [_obs(o) for o in tr["observations"]], where)
                self.assertEqual((again["final"].get("kind"), again["final"].get("text")), (tr["final"].get("kind"), tr["final"].get("text")), where)
                a, b = bench.score(task, again), bench.score(task, tr)
                self.assertEqual({k: a[k] for k in SCORE_FIELDS}, {k: b[k] for k in SCORE_FIELDS}, where)
                if data["set"] == "locked":  # the scorer was frozen before the locked run, so the stored score must still hold
                    self.assertEqual({k: tr["score"][k] for k in SCORE_FIELDS}, {k: b[k] for k in SCORE_FIELDS},
                                     f"{where}: the score stored at run time differs from a fresh score")
                checked += 1
        self.assertGreater(checked, 0)

    def test_no_arm_executed_a_write(self):
        for path in TRACES:
            for tr in json.loads(path.read_text())["traces"]:
                self.assertEqual(tr["totals"]["writes_executed"], 0, path.name)

    def test_gate_and_planner_steps_never_cost_model_tokens(self):
        for path in TRACES:
            for tr in json.loads(path.read_text())["traces"]:
                for s in tr["steps"]:
                    d = s.get("decision") or {}
                    if d.get("provider", "").startswith("exit-gate") and not any(q["name"] in ("operation", "arguments", "escalation") for q in d["questions"]):
                        self.assertIsNone(d["input_tokens"], path.name)
                    if d.get("provider") == "contract-planner":
                        self.assertIsNone(d["input_tokens"], path.name)


@unittest.skipUnless((ROOT / "reports" / "v07" / "summary.md").exists(), "v0.7 report not generated")
class GeneratedArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rep = bench.report()

    def test_committed_report_is_generated_from_committed_traces(self):
        self.assertEqual((ROOT / "reports" / "v07" / "summary.md").read_text(encoding="utf-8"), report.markdown(self.rep))

    def test_locked_traces_were_recorded_after_the_freeze_and_on_the_frozen_task_file(self):
        freeze = self.rep.get("freeze")
        locked = self.rep["sets"].get("locked")
        if not locked:
            self.skipTest("locked set not run")
        self.assertIsNotNone(freeze, "locked traces exist without a freeze manifest")
        self.assertEqual(freeze["sha256"]["fixtures/v07_locked.json"], sha256(SETS["locked"]))
        for arm, a in locked["arms"].items():
            self.assertGreaterEqual(a["provenance"]["recorded_at_utc"], freeze["frozen_at_utc"], arm)

    def test_microscope_page_is_generated_offline_and_injection_safe(self):
        page = ROOT / "demo" / "microscope.html"
        if not page.exists():
            self.skipTest("page not generated")
        html = microscope.render()
        self.assertEqual(page.read_text(encoding="utf-8"), html)
        script = html.split("<script>", 1)[1]
        for banned in ("fetch(", "XMLHttpRequest", "innerHTML", "eval(", "document.write", "http://", "https://"):
            self.assertNotIn(banned, script)
        data = html.split('<script type="application/json" id="data">', 1)[1].split("</script>", 1)[0]
        self.assertNotIn("<", data)
        self.assertIn("Recorded, then replayed", html)
        self.assertIn("not a capable agent", html)


if __name__ == "__main__":
    unittest.main()
