"""Generate an honest, host-only six-turn architecture exhibit. No model calls."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .__main__ import ROOT, request_from_record
from .core import Planner, state_preview
from .deciders import FixtureDecider
from .evaluate import _simple_rules

SHOWCASE = ROOT / "fixtures" / "showcase.json"


def make_exhibit(rows: list[dict]) -> dict:
    if not rows or len({r["id"] for r in rows}) != len(rows):
        raise ValueError("Showcase must have distinct, nonempty case IDs")
    if len({r["text"] for r in rows}) != len(rows):
        raise ValueError("Fixture decider needs unique turn text")
    decider = FixtureDecider({r["text"]: r["mock_judgment"] for r in rows})
    planner = Planner(decider)
    cases = []
    for index, row in enumerate(rows, 1):
        req = request_from_record(row)
        plan = planner.plan(req)
        rule = _simple_rules(req)
        cases.append({
            "number": index,
            "id": row["id"],
            "title": row["title"],
            "request": row["text"],
            "host_summary": req.task_summary,
            "lesson": row["lesson"],
            "plan": plan.as_json(),
            "simple_rule": {"path": rule.path, "model_tier": rule.model_tier, "capability_id": rule.capability_id},
            "decider_received": None if not plan.decision_model_called else state_preview(req, external=False),
            "source_catalog": [{"id": s.id, "chars": len(s.body)} for s in req.sources],
            "full_source_chars": sum(len(s.body) for s in req.sources),
            "selected_source_chars": sum(len(s["text"]) for s in plan.context_pack),
            "available_capabilities": len(req.tools) + len(req.flows),
        })
    return {
        "format": "showcase-v1",
        "status": "CONTRACT DEMONSTRATION ONLY — NO MODEL OR TOOL EXECUTED",
        "limitations": [
            "All decision scores are synthetic fixture values and are not model probabilities.",
            "The six authored scenarios and their fixture decisions are not independent evaluation data.",
            "Routes are proposals; the demonstration never executes tools or generative models.",
            "Character counts cover only fixture source bodies, not prompts or billable tokens.",
            "Approvals and confidentiality shown here are illustrative host contracts, not production enforcement.",
            "A simple rule baseline should be preferred if it delivers equal outcomes at lower complexity.",
        ],
        "cases": cases,
    }


def text_report(e: dict) -> str:
    lines = ["ONE TURN. FOUR PATHS. (+ HOLD)",
             "Fixture-based decision-contract demonstration; no real model/tool calls.", ""]
    for case in e["cases"]:
        p = case["plan"]
        r = case["simple_rule"]
        lines.extend([
            f"{case['number']}. {case['title']}",
            f"   USER     {case['request']}",
            f"   FIXTURE  path={p['path']} tier={p['model_tier'] or 'none'} capability={p['capability_id'] or 'none'}",
            f"   CONTEXT  selected={p['context_ids']} ({case['selected_source_chars']}/{case['full_source_chars']} source-body chars)",
            f"   RULES    path={r['path']} tier={r['model_tier'] or 'none'}",
            f"   TRACE    reasons={','.join(p['reasons']) or 'none'} classifier_called={p['decision_model_called']}",
            "",
        ])
    lines += ["INTERPRETATION: This demonstrates contracts, NOT decision-model quality,",
              "latency savings, model accuracy, safety in production or comparative advantage."]
    return "\n".join(lines) + "\n"


def page(e: dict) -> str:
    """Build a self-contained GitHub Pages-compatible static demo from Python evidence."""
    raw = json.dumps(e, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    html = '''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>One Turn. Four Paths. — Decision Contract Demo</title>
<meta name="description" content="A reproducible, offline exhibit: when should an agent skip the LLM, run a reviewed flow, read a tool, or reason?">
<style>
:root{color-scheme:dark;--bg:#071016;--panel:#10202a;--edge:#29404b;--muted:#b4c5cc;--accent:#8febd0;--text:#edf8f5}
*{box-sizing:border-box}body{font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Arial;background:radial-gradient(ellipse at 15% 0%,#163745 0%,var(--bg) 57%);color:var(--text);margin:0;line-height:1.52}
main{max-width:1120px;margin:auto;padding:54px 24px 80px}h1{font-size:clamp(2.4rem,7vw,5.4rem);line-height:1.03;letter-spacing:-.055em;margin:14px 0}h2{margin:0 0 10px;font-size:1.45rem}p{margin:8px 0}a{color:var(--accent)}.eyebrow{text-transform:uppercase;letter-spacing:.15em;color:var(--accent);font-size:.77rem;font-weight:800}
.lead{font-size:clamp(1rem,2vw,1.24rem);max-width:850px;color:var(--muted)}.flag{display:inline-flex;gap:8px;align-items:center;padding:7px 11px;border-radius:999px;border:1px solid var(--edge);font-size:.76rem;color:#f5d19d;margin:15px 0 8px}
.board{display:grid;grid-template-columns:280px 1fr;gap:16px;margin-top:32px}.panel{border:1px solid var(--edge);border-radius:16px;background:rgba(16,32,42,.9);padding:22px}.case-btn{background:transparent;color:var(--text);width:100%;border:1px solid transparent;border-radius:10px;text-align:left;padding:12px;cursor:pointer;font:inherit;margin:3px 0}.case-btn:hover,.case-btn:focus-visible{border-color:var(--accent);outline:none}.case-btn[aria-pressed=true]{background:#17343d;border-color:var(--accent)}.case-btn span{display:block;color:var(--muted);font-size:.78rem}.case-btn strong{display:block;font-size:.94rem}.tag{font-size:.72rem;text-transform:uppercase;letter-spacing:.09em;color:var(--accent)}
.request{font-size:clamp(1.15rem,3vw,1.9rem);line-height:1.25;margin:12px 0 22px;letter-spacing:-.02em}.meter{display:flex;flex-wrap:wrap;gap:10px;margin:18px 0}.metric{flex:1;min-width:135px;border:1px solid var(--edge);border-radius:12px;padding:12px;background:#0a1a23}.metric b{display:block;font-size:1.15rem}.metric small{color:var(--muted);font-size:.74rem}.section{margin-top:20px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#06121a;border-radius:10px;border:1px solid var(--edge);padding:15px;color:#d1ece4;line-height:1.5;max-height:330px;overflow:auto;font-size:.82rem}
.keys{font-family:ui-monospace,monospace;color:var(--accent)}.note{color:var(--muted);font-size:.9rem}.legend{margin-top:26px;border-top:1px solid var(--edge);padding-top:18px}.pills{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0}.pills span{border:1px solid var(--edge);border-radius:30px;padding:5px 10px;font-size:.77rem;color:var(--muted)}
@media(max-width:780px){main{padding-top:28px}.board{grid-template-columns:1fr}.case-btn{padding:9px}}
</style></head><body><div style="background:#152135;padding:13px;text-align:center;color:#e5efff;font:14px/1.4 system-ui">New: <a style="color:#75dce8" href="local-run.html">see receipts from real local Python execution</a> (no LLM inference)</div><main>
<div class="eyebrow">Agent architecture · runnable exhibit</div><h1>One Turn.<br>Four Paths.</h1>
<p class="lead">Reason, use a tool, run a reviewed flow, or skip the model. And when the request can write to the world: hold for approval. Explore six synthetic turns and inspect exactly what the planner receives and proposes.</p>
<div class="flag">⚠ Fixture decisions only · no model/tool calls · no performance claims</div>
<div class="pills"><span>0 provider credentials</span><span>Python standard library</span><span>Deterministic replay</span><span>Source code is the ground truth</span></div>
<div class="board"><nav class="panel" aria-label="Turn selector"><div class="eyebrow">Select a turn</div><div id="buttons"></div></nav>
<section class="panel" aria-live="polite"><div class="tag" id="turn"></div><h2 id="title"></h2><div class="request" id="request"></div>
<div class="meter"><div class="metric"><small>Fixture proposal</small><b id="path"></b></div><div class="metric"><small>Plain-rule baseline</small><b id="rule"></b></div><div class="metric"><small>Context body characters</small><b id="chars"></b></div></div>
<p class="note" id="lesson"></p><div class="section"><strong>Decision receipt</strong><pre id="receipt"></pre></div>
<div class="section"><strong>Bounded classifier input</strong><p class="note">No raw source bodies. Local bypass skips classification altogether.</p><pre id="state"></pre></div></section></div>
<div class="panel legend"><h2>The result that matters</h2><p>The existing eight-case smoke benchmark does <strong>not</strong> show decision-model advantage: a simple rule policy matches all eight authored labels without a classifier. This exhibit shows implementation contracts, not real-world accuracy. To establish additional value we would need independent multi-turn tasks, verified outcomes, a provider-native comparator, safety checks, and real latency/cost data.</p><p class="note">Inputs, simulated labels and receipts are generated by the Python source; no data is transmitted from this page.</p></div>
</main><script type="application/json" id="dataset">__DATA__</script>
<script>
const exhibit=JSON.parse(document.getElementById('dataset').textContent);
const byId=id=>document.getElementById(id);
function show(i){const c=exhibit.cases[i],p=c.plan;byId('turn').textContent=`Turn ${c.number} of ${exhibit.cases.length}`;byId('title').textContent=c.title;byId('request').textContent=`“${c.request}”`;
byId('path').textContent=p.path.toUpperCase()+(p.model_tier?` · ${p.model_tier}`:'');byId('rule').textContent=c.simple_rule.path.toUpperCase();byId('chars').textContent=`${c.selected_source_chars} / ${c.full_source_chars}`;
byId('lesson').textContent=c.lesson;byId('receipt').textContent=JSON.stringify({path:p.path,model_tier:p.model_tier,capability_id:p.capability_id,context_ids:p.context_ids,approval_required:p.approval_required,classifier_called:p.decision_model_called,reason_codes:p.reasons},null,2);
byId('state').textContent=c.decider_received?JSON.stringify(c.decider_received,null,2):'No classifier call — host provided a verified answer.';
[...byId('buttons').children].forEach((b,j)=>b.setAttribute('aria-pressed',String(i===j)));}
exhibit.cases.forEach((c,i)=>{const b=document.createElement('button');b.className='case-btn';b.setAttribute('aria-pressed','false');const k=document.createElement('span');k.textContent=`TURN ${c.number}`;const v=document.createElement('strong');v.textContent=c.title;b.append(k,v);b.addEventListener('click',()=>show(i));byId('buttons').append(b)});show(0);
</script></body></html>'''
    return html.replace("__DATA__", raw)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-out", type=Path, help="Write inspectable JSON receipt")
    parser.add_argument("--html-out", type=Path, help="Write a self-contained offline browser exhibit")
    parser.add_argument("--fixtures", type=Path, default=SHOWCASE)
    args = parser.parse_args()
    rows = json.loads(args.fixtures.read_text(encoding="utf-8"))
    exhibit = make_exhibit(rows)
    print(text_report(exhibit), end="")
    for destination, value in ((args.json_out, json.dumps(exhibit, ensure_ascii=False, sort_keys=True, indent=2) + "\n"),
                               (args.html_out, page(exhibit))):
        if destination:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(value, encoding="utf-8")


if __name__ == "__main__":
    main()
