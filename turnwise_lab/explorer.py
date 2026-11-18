"""Render the v0.5 outcome explorer (demo/index.html) from reports/arena.json.

The page is static and self-contained: data is embedded as JSON, rendered with
textContent (never innerHTML for data), and makes no network requests.
"""
from __future__ import annotations

from html import escape
from pathlib import Path
import argparse
import json

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "arena.json"
OUT = ROOT / "demo" / "index.html"
REPO = "https://github.com/dgenio/turnwise-decision-lab"

SHORT = {"agent_baseline": "Agent", "stateless_router": "v0.4 rules", "joint_router": "Joint",
         "joint_no_state": "No state", "joint_lexical_context": "Lexical ctx", "learned_nb_path": "Naive Bayes",
         "oracle": "Oracle"}
_KEEP = ("path", "reason", "outcome", "receipt_status", "model_calls", "missing", "tools_exposed",
         "model_input_chars", "hold_capability", "fetched_by_tool_round", "answer_facts", "prefetch_sufficient")


def _slim(r: dict) -> dict:
    out = {k: r[k] for k in _KEEP if k in r}
    out["calls"] = [{"capability": c["capability"], "args": c["args"], "status": c["receipt_status"],
                     "facts": c["facts"]} for c in r["calls"]]
    if r.get("context"):
        ctx = r["context"]
        out["context"] = {"policy": ctx["policy"], "budget": ctx["budget"],
                          "included": [[i["key"], i["chars"]] for i in ctx["included"]],
                          "excluded": [[i["key"], i["chars"], i["reason"]] for i in ctx["excluded"]],
                          "not_selected": ctx.get("needed_not_selected", [])}
    return out


def page_data(report: dict) -> dict:
    return {
        "arms": [{"id": a["id"], "label": a["label"], "short": SHORT[a["id"]], "about": a["about"], "s": a["summary"]}
                 for a in report["arms"]],
        "sessions": report["session_titles"],
        "turns": [{"id": t["id"], "session": t["session"], "text": t["text"], "family": t["family"],
                   "mode": t["mode"], "needs": t["needs"], "note": t["note"], "action": t["action"],
                   "cf": t["counterfactuals"], "r": {a: _slim(r) for a, r in t["results"].items()}}
                  for t in report["turns"]],
        "hypotheses": report["hypotheses"],
        "safety": {k: report["safety"][k] for k in ("forged_attempts", "unauthorized_executions", "positive_control")},
        "sweep": report["budget_sweep"],
    }


def headline(report: dict) -> dict:
    s = {a["id"]: a["summary"] for a in report["arms"]}
    agent, joint, oracle = s["agent_baseline"], s["joint_router"], s["oracle"]
    return {
        "turns": oracle["turns"],
        "oracle_zero_pct": round(100 * oracle["zero_model_call_turns"] / oracle["turns"]),
        "joint_cut_pct": round(100 * (agent["model_calls"] - joint["model_calls"]) / agent["model_calls"]),
        "agent_calls": agent["model_calls"], "joint_calls": joint["model_calls"],
        "joint_silent": joint["outcomes"]["silent_miss"],
        "forged": report["safety"]["forged_attempts"], "executed": report["safety"]["unauthorized_executions"],
        "schema_pct": round(100 * agent["tool_schema_chars"] / agent["model_input_chars"]),
    }


def render(report: dict) -> str:
    h = headline(report)
    data = json.dumps(page_data(report), ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    data = data.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    html = TEMPLATE
    for key, value in h.items():
        html = html.replace("{{" + key + "}}", escape(str(value)))
    return html.replace("{{REPO}}", REPO).replace("__DATA__", data)


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Turnwise Routing Experiment</title>
<meta name="description" content="Seven per-turn routing designs replayed on the same {{turns}} synthetic agent turns. Real tool execution, outcome-checked answers, no model calls, pre-registered hypotheses, all failures shown.">
<style>
:root{
  color-scheme: light;
  --bg:#f6f5f2; --surface:#fcfcfb; --raised:#ffffff; --line:#e3e1db; --line-strong:#cfccc4;
  --text:#0b0b0b; --text-2:#52514e; --muted:#77756f; --accent:#2a78d6; --accent-ink:#1c5cab;
  --good:#0ca30c; --good-ink:#ffffff; --warn:#fab219; --warn-ink:#0b0b0b; --crit:#d03b3b; --crit-ink:#ffffff;
  --m1:#2a78d6; --m1-ink:#ffffff; --m2:#184f95; --m2-ink:#ffffff; --bar:#2a78d6; --track:#ecebe7;
  --code-bg:#f1f0ec; --focus:#2a78d6;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    color-scheme: dark;
    --bg:#121211; --surface:#1a1a19; --raised:#212120; --line:#2f2f2c; --line-strong:#3d3d39;
    --text:#f0efec; --text-2:#c3c2b7; --muted:#9a998f; --accent:#6da7ec; --accent-ink:#86b6ef;
    --good:#0ca30c; --good-ink:#ffffff; --warn:#fab219; --warn-ink:#0b0b0b; --crit:#d03b3b; --crit-ink:#ffffff;
    --m1:#1c5cab; --m1-ink:#ffffff; --m2:#6da7ec; --m2-ink:#0b0b0b; --bar:#3987e5; --track:#2a2a28;
    --code-bg:#151514; --focus:#6da7ec;
  }
}
:root[data-theme="dark"]{
  color-scheme: dark;
  --bg:#121211; --surface:#1a1a19; --raised:#212120; --line:#2f2f2c; --line-strong:#3d3d39;
  --text:#f0efec; --text-2:#c3c2b7; --muted:#9a998f; --accent:#6da7ec; --accent-ink:#86b6ef;
  --good:#0ca30c; --good-ink:#ffffff; --warn:#fab219; --warn-ink:#0b0b0b; --crit:#d03b3b; --crit-ink:#ffffff;
  --m1:#1c5cab; --m1-ink:#ffffff; --m2:#6da7ec; --m2-ink:#0b0b0b; --bar:#3987e5; --track:#2a2a28;
  --code-bg:#151514; --focus:#6da7ec;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--text);font:16px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif}
a{color:var(--accent-ink)} a:hover{text-decoration-thickness:2px}
code,.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.86em}
main{max-width:1180px;margin:0 auto;padding:28px 16px 72px}
.top{display:flex;justify-content:space-between;align-items:center;gap:12px;font-size:.84rem;color:var(--muted)}
.top nav{display:flex;flex-wrap:wrap;gap:14px}
.top button{font:inherit;color:var(--text-2);background:transparent;border:1px solid var(--line-strong);border-radius:8px;padding:4px 10px;cursor:pointer}
.eyebrow{margin:40px 0 10px;font-size:.78rem;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);font-weight:650}
h1{font-size:clamp(1.9rem,4.6vw,3.25rem);line-height:1.08;letter-spacing:-.025em;margin:0 0 18px;max-width:22ch;font-weight:720}
h2{font-size:1.45rem;letter-spacing:-.01em;margin:0 0 6px;font-weight:680}
h3{font-size:1rem;margin:18px 0 6px}
.lede{font-size:1.08rem;color:var(--text-2);max-width:70ch;margin:0}
.sub{color:var(--text-2);max-width:75ch;margin:0 0 18px}
section{margin-top:56px}
.tiles{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-top:28px}
.tile{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:16px}
.tile b{display:block;font-size:2rem;line-height:1.1;font-weight:720;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.tile span{display:block;color:var(--text-2);font-size:.88rem;margin-top:6px}
.honest{margin-top:22px;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
.honest div{border-top:3px solid var(--line-strong);padding:10px 2px 0;font-size:.9rem;color:var(--text-2)}
.honest strong{display:block;color:var(--text);font-size:.8rem;letter-spacing:.06em;text-transform:uppercase;margin-bottom:4px}
.honest .real{border-color:var(--good)} .honest .assumed{border-color:var(--warn)} .honest .absent{border-color:var(--crit)}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:12px}
/* arms table */
.arms{width:100%;border-collapse:collapse;font-size:.92rem}
.arms th{font-weight:600;color:var(--muted);font-size:.76rem;text-transform:uppercase;letter-spacing:.06em;text-align:left;padding:12px 14px;border-bottom:1px solid var(--line)}
.arms td{padding:11px 14px;border-bottom:1px solid var(--line);vertical-align:middle}
.arms tr:last-child td{border-bottom:0}
.arms .name b{display:block;font-weight:620}
.arms .name small{color:var(--muted);display:block;font-size:.8rem;max-width:42ch}
.num{font-variant-numeric:tabular-nums;white-space:nowrap}
.barcell{min-width:170px}
.bar{display:flex;align-items:center;gap:8px}
.bar .num{min-width:3.6em}
.track{flex:1;height:8px;border-radius:4px;background:var(--track);display:flex;overflow:hidden;gap:2px}
.fill{height:8px;border-radius:4px;background:var(--bar)}
.fill.silent{background:var(--crit)} .fill.loud{background:var(--warn)}
.oracle-row td{color:var(--text-2)}
.key{display:flex;flex-wrap:wrap;gap:8px 16px;font-size:.84rem;color:var(--text-2);margin:12px 0 0}
.key span{display:inline-flex;align-items:center;gap:6px}
.sw{width:12px;height:12px;border-radius:3px;display:inline-block}
/* matrix */
.mx-wrap{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,440px);gap:16px;align-items:start}
.legend{display:flex;flex-wrap:wrap;gap:8px 14px;margin:0 0 12px;font-size:.84rem;color:var(--text-2)}
.legend span{display:inline-flex;align-items:center;gap:6px}
.cellchip{width:20px;height:20px;border-radius:5px;display:inline-grid;place-items:center;font:700 .72rem ui-monospace,monospace}
.matrix{padding:10px 8px 12px}
.mx-head,.mx-row{display:grid;grid-template-columns:minmax(0,1fr) repeat(7,30px);gap:3px;align-items:center}
.mx-head{position:sticky;top:0;background:var(--surface);z-index:1;padding:4px 0 8px;border-bottom:1px solid var(--line);margin-bottom:6px}
.mx-head div{font-size:.7rem;color:var(--muted);text-align:center;line-height:1.1;writing-mode:vertical-rl;transform:rotate(180deg);height:74px;justify-self:center;white-space:nowrap}
.mx-head div:first-child{writing-mode:horizontal-tb;transform:none;height:auto;justify-self:start;font-size:.76rem;align-self:end;text-transform:uppercase;letter-spacing:.06em}
.mx-session{font-size:.74rem;text-transform:uppercase;letter-spacing:.07em;color:var(--muted);margin:12px 4px 4px;font-weight:650}
.mx-label{font-size:.82rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--text-2);padding-left:4px}
.mx-label .tid{color:var(--muted);font-family:ui-monospace,monospace;font-size:.74rem;margin-right:6px}
.cell{width:30px;height:26px;border-radius:5px;border:0;padding:0;cursor:pointer;font:700 .74rem ui-monospace,monospace;display:grid;place-items:center}
.cell:focus-visible{outline:2px solid var(--focus);outline-offset:2px}
.cell[aria-pressed="true"]{box-shadow:0 0 0 2px var(--surface),0 0 0 4px var(--text)}
.c-ok0{background:var(--good);color:var(--good-ink)} .c-ok1{background:var(--m1);color:var(--m1-ink)} .c-ok2{background:var(--m2);color:var(--m2-ink)}
.c-silent{background:var(--crit);color:var(--crit-ink)} .c-loud{background:var(--warn);color:var(--warn-ink)}
.mx-row:hover .mx-label{color:var(--text)}
/* detail */
.detail{padding:18px;position:sticky;top:12px;max-height:calc(100vh - 24px);overflow:auto}
.detail h3{margin:0 0 4px;font-size:.78rem;text-transform:uppercase;letter-spacing:.07em;color:var(--muted)}
.detail .q{font-size:1.15rem;line-height:1.35;margin:0 0 10px;font-weight:600}
.meta{font-size:.82rem;color:var(--muted);margin-bottom:12px}
.verdict{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:12px 0}
.verdict div{border:1px solid var(--line);border-radius:10px;padding:10px;background:var(--raised)}
.verdict small{display:block;color:var(--muted);font-size:.72rem;text-transform:uppercase;letter-spacing:.06em}
.verdict b{display:flex;align-items:center;gap:6px;margin-top:4px;font-size:.95rem}
.why{font-size:.9rem;color:var(--text-2);margin:6px 0 12px}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0 10px}
.chip{font:.76rem ui-monospace,monospace;border:1px solid var(--line-strong);border-radius:999px;padding:2px 8px;background:var(--raised)}
.chip.have{border-color:var(--good)} .chip.miss{border-color:var(--crit);color:var(--crit)}
.dsec{border-top:1px solid var(--line);padding-top:10px;margin-top:12px}
.calls{list-style:none;padding:0;margin:6px 0}
.calls li{font-size:.82rem;margin:4px 0}
details.facts summary{cursor:pointer;color:var(--text-2);font-size:.82rem}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:var(--code-bg);border:1px solid var(--line);border-radius:8px;padding:10px;font-size:.74rem;line-height:1.45;max-height:260px;overflow:auto;margin:6px 0}
.ctx{width:100%;border-collapse:collapse;font-size:.78rem}
.ctx td{padding:3px 4px;border-bottom:1px solid var(--line)}
.ctx td:last-child{text-align:right;color:var(--muted)}
.ctx .x td{color:var(--muted);text-decoration:line-through}
.ctx .need td:first-child::before{content:"needed · ";color:var(--good);font-weight:600;text-decoration:none}
.ctx .x.need td:first-child::before{color:var(--crit)}
.arms-strip{display:flex;flex-wrap:wrap;gap:4px;margin-top:6px}
.arms-strip button{font-size:.72rem;border:1px solid var(--line-strong);background:var(--raised);color:var(--text);border-radius:6px;padding:3px 6px;cursor:pointer;display:inline-flex;gap:5px;align-items:center}
.arms-strip button[aria-pressed="true"]{border-color:var(--text)}
.cf{width:100%;border-collapse:collapse;font-size:.8rem}
.cf td{padding:3px 4px;border-bottom:1px solid var(--line);vertical-align:top}
.cf td:first-child{color:var(--muted);white-space:nowrap;padding-right:10px}
/* tradeoff */
.tw{padding:18px}
.sliders{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-bottom:16px}
.sliders label{display:block;font-size:.9rem;color:var(--text-2)}
.sliders output{font-weight:700;color:var(--text);font-variant-numeric:tabular-nums}
input[type=range]{width:100%;accent-color:var(--accent)}
.tbars{display:grid;gap:8px}
.tb{display:grid;grid-template-columns:minmax(0,240px) minmax(0,1fr) 92px;gap:10px;align-items:center;font-size:.86rem}
.tb .lab{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tb .track{height:10px;border-radius:5px}
.tb .fill{height:10px;border-radius:5px}
.tb.best .lab{font-weight:700}
.tb .tag{display:none;color:var(--text);font-weight:650;margin-left:6px;font-size:.78rem}
.tb.best .tag{display:inline}
.callout{margin-top:14px;font-size:.95rem;color:var(--text-2)}
/* hypotheses */
.hyp{width:100%;border-collapse:collapse;font-size:.88rem}
.hyp th,.hyp td{text-align:left;padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top}
.hyp th{font-size:.74rem;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;font-weight:600}
.badge{display:inline-flex;align-items:center;gap:5px;font-size:.78rem;font-weight:650;border-radius:999px;padding:2px 9px;border:1px solid var(--line-strong);white-space:nowrap}
.badge.sup::before{content:"✓"} .badge.fal::before{content:"✗"} .badge.rep::before{content:"·"}
.badge.sup{border-color:var(--good)} .badge.fal{border-color:var(--crit)}
.obs{color:var(--text-2);font-size:.82rem}
.two{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.list{margin:6px 0 0;padding-left:18px;color:var(--text-2);font-size:.92rem}
.list li{margin:4px 0}
footer{margin-top:64px;padding-top:20px;border-top:1px solid var(--line);font-size:.88rem;color:var(--text-2)}
.tablewrap{overflow-x:auto}
@media (max-width:920px){
  .mx-wrap{grid-template-columns:1fr}
  .detail{position:static;max-height:none}
  .tiles{grid-template-columns:repeat(2,minmax(0,1fr))}
}
@media (max-width:640px){
  .honest,.two,.sliders{grid-template-columns:1fr}
  .top nav{display:none}
  .arms .hide-sm{display:none}
  .arms th,.arms td{padding:10px 8px}
  .barcell{min-width:96px}
  .mx-head,.mx-row{grid-template-columns:minmax(0,1fr) repeat(7,26px);gap:2px}
  .cell{width:26px;height:24px}
  .tb{grid-template-columns:minmax(0,120px) minmax(0,1fr) 84px}
  .verdict{grid-template-columns:1fr}
}
</style>
</head>
<body>
<main>
<div class="top"><span>Turnwise Decision Lab · v0.5</span>
<nav aria-label="Sections"><a href="#arms">Results</a><a href="#matrix">Every turn</a><a href="#tradeoff">Trade-off</a><a href="#hypotheses">Hypotheses</a><a href="#limits">Limits</a><a href="{{REPO}}">Source</a></nav>
<button type="button" id="theme" aria-label="Toggle colour theme">Theme</button></div>

<p class="eyebrow">Route the work, not just the model · outcome-scored experiment</p>
<h1>The router that skipped the most model calls was also the one that failed silently.</h1>
<p class="lede">Before choosing <em>which</em> model, an agent can ask whether a turn needs a model at all, or just a verified fact, a read tool or a known workflow. We replayed {{turns}} synthetic incident-investigation turns through seven routing designs. Every tool and workflow call really ran, and every answer was checked against the facts the question needed. No model was called.</p>

<div class="tiles" role="list">
  <div class="tile" role="listitem"><b>{{oracle_zero_pct}}%</b><span>of turns could be answered with no model call (oracle upper bound on this workload)</span></div>
  <div class="tile" role="listitem"><b>{{joint_cut_pct}}%</b><span>fewer model calls from the state-aware joint router than from an always-agent ({{joint_calls}} vs {{agent_calls}})</span></div>
  <div class="tile" role="listitem"><b>{{joint_silent}}</b><span>wrong answers from that router whose execution receipt still said <code>completed</code></span></div>
  <div class="tile" role="listitem"><b>{{executed}} / {{forged}}</b><span>forged write attempts executed. The harness held every one, even when the router was compromised</span></div>
</div>

<div class="honest">
  <div class="real"><strong>Real</strong>Tool and workflow handlers (local Python, synthetic data), harness checks, the exact context and tool list each model call would receive, and outcome checks.</div>
  <div class="assumed"><strong>Assumed</strong>A model call with the needed evidence answers correctly. The baseline agent picks exactly the right tools. Both assumptions favour calling the model.</div>
  <div class="absent"><strong>Not measured</strong>Answer quality, tokens, dollars, provider latency, and any live router (LiteLLM, vLLM Semantic Router, Jev, provider tool search).</div>
</div>

<section id="arms" aria-labelledby="arms-h">
<h2 id="arms-h">Seven routing designs, same {{turns}} turns</h2>
<p class="sub">Model calls include the agent's extra tool-calling round. Failures split into <strong>silent</strong> ones (an answer was returned and the receipt says completed, but it does not answer the question) and <strong>visible</strong> ones (false approval holds, dropped actions). Tool schemas are {{schema_pct}}% of the agent's input characters.</p>
<div class="panel tablewrap"><table class="arms" id="armsTable"><thead><tr><th scope="col">Design</th><th scope="col" class="num">Correct</th><th scope="col">Model calls</th><th scope="col">Failures</th><th scope="col" class="hide-sm num">Context chars</th></tr></thead><tbody></tbody></table></div>
<div class="key"><span><i class="sw" style="background:var(--bar)"></i>model calls</span><span><i class="sw" style="background:var(--crit)"></i>silent failures</span><span><i class="sw" style="background:var(--warn)"></i>visible failures</span><span>Correct counts model paths as correct whenever the needed evidence was available: an upper bound.</span></div>
</section>

<section id="matrix" aria-labelledby="mx-h">
<h2 id="mx-h">Every turn, every design</h2>
<p class="sub">Each cell is one turn under one design. Select a cell to see what actually ran, what the context packet contained and left out, and why the outcome was scored as it was.</p>
<div class="legend" id="legend"></div>
<div class="mx-wrap">
  <div class="panel matrix" id="matrixPanel"><div class="mx-head" id="mxHead"></div><div id="mxBody"></div></div>
  <aside class="panel detail" id="detail" aria-live="polite"></aside>
</div>
</section>

<section id="tradeoff" aria-labelledby="to-h">
<h2 id="to-h">What is a silent wrong answer worth?</h2>
<p class="sub">Routing trades model calls for failures. Set what one failure costs in units of model calls; the bars add measured model calls and the weighted measured failures. These are your prices, not ours.</p>
<div class="panel tw">
  <div class="sliders">
    <label for="wSilent">One silent wrong answer costs <output id="oSilent" for="wSilent"></output> model calls
      <input type="range" id="wSilent" min="0" max="40" step="1" value="10"></label>
    <label for="wLoud">One visible failure (false hold, dropped action) costs <output id="oLoud" for="wLoud"></output> model calls
      <input type="range" id="wLoud" min="0" max="40" step="1" value="3"></label>
  </div>
  <div class="tbars" id="tbars"></div>
  <p class="callout" id="callout"></p>
</div>
</section>

<section id="hypotheses" aria-labelledby="h-h">
<h2 id="h-h">Pre-registered hypotheses</h2>
<p class="sub">Committed before any experiment code existed (<a href="{{REPO}}/blob/main/docs/preregistration-v0.5.md">pre-registration</a>). Code computes every verdict. Two of the predictions were wrong, and the failures are kept.</p>
<div class="panel tablewrap"><table class="hyp" id="hypTable"><thead><tr><th scope="col">ID</th><th scope="col">Claim and prediction</th><th scope="col">Observed</th><th scope="col">Verdict</th></tr></thead><tbody></tbody></table></div>
</section>

<section id="limits" aria-labelledby="l-h">
<h2 id="l-h">What this does and does not show</h2>
<div class="two">
  <div><h3>Supported on this workload</h3><ul class="list">
    <li>A router that sees session state can resolve follow-ups ("and for search?") with no model call. A message-only router resolved none of them.</li>
    <li>That same state turns uncertainty into confident wrong answers, and a wrong carried entity cascades to the next turn.</li>
    <li>Safety comes from capability metadata checked by the host. v0.4's verb-matching rules missed 4 of 6 action requests (the harness held all of them) and blocked 5 harmless requests.</li>
    <li>v0.4's learned classifier does not transfer: 17 failures.</li>
  </ul></div>
  <div><h3>Not supported, or not tested</h3><ul class="list">
    <li>Route-aware context selection did <strong>not</strong> beat lexical selection (3/9 vs 2/9 complete packets). Field names in tool output pulled the wrong runbooks into the query.</li>
    <li>The context budget was not the bottleneck. A 16× larger budget changed little.</li>
    <li>Same author for the world, the sessions, the labels and the routers. Results are reported per turn family so you can reweight to your own traffic mix.</li>
    <li>No model, so no answer quality, latency or price. Model-tier routing composes with all of this and is not evaluated here.</li>
  </ul></div>
</div>
</section>

<footer>
<p><strong>Reproduce</strong> (Python 3.10+, no dependencies, no network): <code>python -m turnwise_lab.arena</code> regenerates <a href="{{REPO}}/blob/main/reports/arena.md">reports/arena.md</a> and <a href="{{REPO}}/blob/main/reports/arena.json">arena.json</a>; <code>python -m turnwise_lab.explorer</code> rebuilds this page. CI checks that both are byte-identical to what is committed.</p>
<p>Earlier exhibits: <a href="local-run.html">v0.4 execution receipts</a> · <a href="planning-contract.html">v0.4 planning contract (fixture decisions)</a>. All data is synthetic and was invented for this experiment. MIT licensed. Not affiliated with other projects named "Turnwise".</p>
</footer>
</main>
<script type="application/json" id="data">__DATA__</script>
<script>
(function(){
"use strict";
var D = JSON.parse(document.getElementById("data").textContent);
var ARMS = D.arms, TURNS = D.turns;
var OK = {resolved:1, ready:1, ready_after_tools:1, held:1, refused:1};
var LOUD = {false_hold:1, held_wrong_action:1, action_dropped:1, insufficient:1, error:1, unauthorized_execution:1};
var OUTCOME_TEXT = {
  resolved:"Resolved with no model call", ready:"Handed to a model with all needed evidence",
  ready_after_tools:"Handed to a model that needed an extra tool round", held:"Held for approval: nothing executed",
  refused:"Refused: no such capability", silent_miss:"Silent miss: the answer does not answer the question",
  insufficient:"Model call lacked evidence it could not fetch", false_hold:"False hold: a harmless request was blocked",
  held_wrong_action:"Held, but for the wrong action", action_dropped:"Action dropped: neither held nor done",
  error:"Handler error", unauthorized_execution:"Unauthorized execution"
};
function el(tag, attrs, kids){
  var n = document.createElement(tag);
  if (attrs) for (var k in attrs){ if (k === "text") n.textContent = attrs[k]; else if (k === "cls") n.className = attrs[k]; else n.setAttribute(k, attrs[k]); }
  (kids || []).forEach(function(c){ if (c != null) n.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
  return n;
}
function cls(r){
  if (r.outcome === "silent_miss") return "silent";
  if (LOUD[r.outcome]) return "loud";
  return "ok" + Math.min(2, r.model_calls);
}
function glyph(r){ var c = cls(r); return c === "silent" ? "!" : c === "loud" ? "×" : String(r.model_calls); }
function silentOf(s){ return s.outcomes.silent_miss; }
function loudOf(s){ return s.failures - s.outcomes.silent_miss; }

// theme toggle (per-viewer convenience only)
(function(){
  var root = document.documentElement, btn = document.getElementById("theme");
  try { var t = localStorage.getItem("tw-theme"); if (t) root.setAttribute("data-theme", t); } catch(e) {}
  btn.addEventListener("click", function(){
    var dark = root.getAttribute("data-theme") ? root.getAttribute("data-theme") === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    var next = dark ? "light" : "dark"; root.setAttribute("data-theme", next);
    try { localStorage.setItem("tw-theme", next); } catch(e) {}
  });
})();

// arms table
(function(){
  var tb = document.querySelector("#armsTable tbody");
  var maxCalls = Math.max.apply(null, ARMS.map(function(a){ return a.s.model_calls; }));
  var maxFail = Math.max.apply(null, ARMS.map(function(a){ return a.s.failures; })) || 1;
  ARMS.forEach(function(a){
    var s = a.s, silent = silentOf(s), loud = loudOf(s);
    var calls = el("div", {cls:"bar"}, [el("div", {cls:"track"}, [el("div", {cls:"fill", style:"width:" + (100*s.model_calls/maxCalls) + "%"})]), el("span", {cls:"num", text:String(s.model_calls)})]);
    var ftrack = el("div", {cls:"track", "aria-hidden":"true"}, [
      silent ? el("div", {cls:"fill silent", style:"width:" + (100*silent/maxFail) + "%"}) : null,
      loud ? el("div", {cls:"fill loud", style:"width:" + (100*loud/maxFail) + "%"}) : null]);
    var fails = el("div", {cls:"bar", title: silent + " silent, " + loud + " visible"}, [ftrack, el("span", {cls:"num", text: silent + " + " + loud})]);
    tb.appendChild(el("tr", {cls: a.id === "oracle" ? "oracle-row" : ""}, [
      el("td", {cls:"name"}, [el("b", {text:a.label}), el("small", {text:a.about})]),
      el("td", {cls:"num", text: s.correct + "/" + s.turns}),
      el("td", {cls:"barcell"}, [calls]), el("td", {cls:"barcell"}, [fails]),
      el("td", {cls:"num hide-sm", text: s.model_input_chars.toLocaleString("en-US")})]));
  });
})();

// legend
(function(){
  var L = document.getElementById("legend");
  [["ok0","0","correct, no model call"],["ok1","1","correct, 1 model call"],["ok2","2","correct, 2 model calls"],
   ["silent","!","silent wrong answer"],["loud","×","visible failure"]].forEach(function(x){
    L.appendChild(el("span", null, [el("i", {cls:"cellchip c-" + x[0], "aria-hidden":"true", text:x[1]}), x[2]]));
  });
})();

// matrix
var selected = {turn:"S9.3", arm:"joint_router"};
var cellIndex = {};
(function(){
  var head = document.getElementById("mxHead"), body = document.getElementById("mxBody");
  head.appendChild(el("div", {text:"Turn"}));
  ARMS.forEach(function(a){ head.appendChild(el("div", {title:a.label, text:a.short})); });
  var last = null;
  TURNS.forEach(function(t){
    if (t.session !== last){ last = t.session; body.appendChild(el("div", {cls:"mx-session", text: t.session + " · " + D.sessions[t.session]})); }
    var row = el("div", {cls:"mx-row"}, [el("div", {cls:"mx-label", title:t.text}, [el("span", {cls:"tid", text:t.id}), t.text])]);
    ARMS.forEach(function(a){
      var r = t.r[a.id];
      var b = el("button", {type:"button", cls:"cell c-" + cls(r), "aria-pressed":"false",
        "aria-label": t.id + ", " + a.label + ": " + (OUTCOME_TEXT[r.outcome] || r.outcome) + ", " + r.model_calls + " model calls",
        title: a.label + " · " + (OUTCOME_TEXT[r.outcome] || r.outcome), text: glyph(r)});
      b.addEventListener("click", function(){ select(t.id, a.id, true); });
      cellIndex[t.id + "|" + a.id] = b;
      row.appendChild(b);
    });
    body.appendChild(row);
  });
})();

function factLine(k, state){
  var mark = state === "have" ? "✓ " : state === "fetched" ? "↻ " : "✗ ";
  return el("span", {cls:"chip " + (state === "miss" ? "miss" : "have"), title: state === "fetched" ? "not in the first context; fetched by an extra tool round" : "", text: mark + k});
}

function select(tid, arm, scroll){
  var prev = cellIndex[selected.turn + "|" + selected.arm]; if (prev) prev.setAttribute("aria-pressed", "false");
  selected = {turn:tid, arm:arm};
  var cur = cellIndex[tid + "|" + arm]; if (cur) cur.setAttribute("aria-pressed", "true");
  var t = TURNS.filter(function(x){ return x.id === tid; })[0], r = t.r[arm];
  var a = ARMS.filter(function(x){ return x.id === arm; })[0];
  var d = document.getElementById("detail"); d.textContent = "";
  d.appendChild(el("h3", {text: t.id + " · " + D.sessions[t.session]}));
  d.appendChild(el("p", {cls:"q", text:"“" + t.text + "”"}));
  d.appendChild(el("div", {cls:"meta", text:"family: " + t.family.replace(/_/g, " ") + " · mode: " + t.mode + (t.note ? " · " + t.note : "")}));
  var strip = el("div", {cls:"arms-strip", role:"group", "aria-label":"Same turn under other designs"});
  ARMS.forEach(function(x){
    var rr = t.r[x.id];
    var btn = el("button", {type:"button", "aria-pressed": String(x.id === arm)}, [el("i", {cls:"cellchip c-" + cls(rr), "aria-hidden":"true", text:glyph(rr)}), x.short]);
    btn.addEventListener("click", function(){ select(tid, x.id, false); });
    strip.appendChild(btn);
  });
  d.appendChild(strip);
  var receipt = r.receipt_status === "completed" ? "completed" : r.receipt_status.replace(/_/g, " ");
  d.appendChild(el("div", {cls:"verdict"}, [
    el("div", null, [el("small", {text:"Harness receipt"}), el("b", {text: receipt})]),
    el("div", null, [el("small", {text:"Outcome check"}), el("b", null, [el("i", {cls:"cellchip c-" + cls(r), "aria-hidden":"true", text:glyph(r)}), OUTCOME_TEXT[r.outcome] || r.outcome])])]));
  d.appendChild(el("p", {cls:"why"}, [el("strong", {text: a.label + ": "}), "route ", el("code", {text:r.path}), " because " + r.reason + "."]));
  if (t.mode !== "action"){
    var miss = {}, fetched = {};
    (r.missing || []).forEach(function(k){ miss[k] = 1; });
    (r.fetched_by_tool_round || []).forEach(function(k){ fetched[k] = 1; });
    d.appendChild(el("div", {cls:"dsec"}, [el("h3", {text:"Facts the question needed (✓ delivered · ↻ fetched in an extra round · ✗ missing)"}),
      el("div", {cls:"chips"}, t.needs.map(function(k){ return factLine(k, !miss[k] ? "have" : fetched[k] ? "fetched" : "miss"); }))]));
  } else {
    d.appendChild(el("div", {cls:"dsec"}, [el("h3", {text:"Requested action"}), el("div", {cls:"chips"}, [el("span", {cls:"chip", text: t.action || "no registered capability"})])]));
  }
  if (r.calls && r.calls.length){
    var ul = el("ul", {cls:"calls"});
    r.calls.forEach(function(c){
      var args = Object.keys(c.args).map(function(k){ return c.args[k]; }).join(", ");
      var keys = Object.keys(c.facts);
      ul.appendChild(el("li", null, [el("code", {text:(c.capability || "hold") + "(" + args + ")"}), " → " + c.status.replace(/_/g, " ") + (keys.length ? " · " + keys.join(", ") : "")]));
    });
    var all = {}; r.calls.forEach(function(c){ for (var k in c.facts) all[k] = c.facts[k]; });
    var sec = el("div", {cls:"dsec"}, [el("h3", {text:"Executed through the harness"}), ul]);
    if (Object.keys(all).length) sec.appendChild(el("details", {cls:"facts"}, [el("summary", {text:"Show real handler output"}), el("pre", {text: JSON.stringify(all, null, 1)})]));
    d.appendChild(sec);
  }
  if (r.model_calls){
    var info = r.model_calls + " model call" + (r.model_calls > 1 ? "s" : "") + " · " + (r.tools_exposed || []).length + " tool schemas exposed · " + r.model_input_chars.toLocaleString("en-US") + " input characters (not executed)";
    d.appendChild(el("div", {cls:"dsec"}, [el("h3", {text:"Model handoff"}), el("p", {cls:"why", text:info})]));
  }
  if (r.context){
    var need = {}; t.needs.forEach(function(k){ need[k] = 1; });
    var tbl = el("table", {cls:"ctx"});
    r.context.included.forEach(function(i){ tbl.appendChild(el("tr", {cls: need[i[0]] ? "need" : ""}, [el("td", {text:i[0].replace(/^user:/, "user message ")}), el("td", {text:i[1] + " ch"})])); });
    r.context.excluded.forEach(function(i){ tbl.appendChild(el("tr", {cls:"x" + (need[i[0]] ? " need" : "")}, [el("td", {text:i[0].replace(/^user:/, "user message ")}), el("td", {text:"dropped: " + i[2]})])); });
    (r.context.not_selected || []).forEach(function(k){ tbl.appendChild(el("tr", {cls:"x need"}, [el("td", {text:k}), el("td", {text:"not selected"})])); });
    d.appendChild(el("div", {cls:"dsec"}, [el("h3", {text:"Context packet" + (r.context.budget ? " · budget " + r.context.budget.toLocaleString("en-US") + " chars" : "")}),
      el("p", {cls:"why", text:r.context.policy}), tbl]));
  }
  var cf = el("table", {cls:"cf"});
  ["direct","deterministic","grounded","agentic","hold"].forEach(function(p){ cf.appendChild(el("tr", null, [el("td", {text:p}), el("td", {text:t.cf[p]})])); });
  d.appendChild(el("div", {cls:"dsec"}, [el("h3", {text:"Illustrative path assumptions — not executed"}), el("p", {cls:"why", text:"These descriptions use authored outcome labels and simplifying assumptions. They are NOT executed counterfactual runs or measured model answers. To inspect observed behavior, select another strategy cell in the comparison matrix."}), cf]));
  if (scroll && window.matchMedia("(max-width:920px)").matches) d.scrollIntoView({behavior:"smooth", block:"start"});
}
select(selected.turn, selected.arm, false);

// trade-off
(function(){
  var ws = document.getElementById("wSilent"), wl = document.getElementById("wLoud");
  var box = document.getElementById("tbars"), call = document.getElementById("callout");
  var rows = ARMS.map(function(a){
    var tr = el("div", {cls:"track"}, [el("div", {cls:"fill"})]), v = el("span", {cls:"num"});
    var row = el("div", {cls:"tb"}, [el("span", {cls:"lab", title:a.label, text:a.short}), tr,
      el("span", null, [v, el("span", {cls:"tag", text:"◀ lowest"})])]);
    box.appendChild(row); return {a:a, row:row, fill:tr.firstChild, v:v};
  });
  function draw(){
    var s = +ws.value, l = +wl.value;
    document.getElementById("oSilent").textContent = s; document.getElementById("oLoud").textContent = l;
    var tot = rows.map(function(x){ var q = x.a.s; return q.model_calls + s*silentOf(q) + l*loudOf(q); });
    var max = Math.max.apply(null, tot) || 1, best = Infinity, bestId = null;
    rows.forEach(function(x, i){ if (x.a.id !== "oracle" && tot[i] < best){ best = tot[i]; bestId = x.a.id; } });
    rows.forEach(function(x, i){ x.fill.style.width = (100*tot[i]/max) + "%"; x.v.textContent = String(tot[i]); x.row.classList.toggle("best", x.a.id === bestId); });
    var agent = ARMS.filter(function(a){ return a.id === "agent_baseline"; })[0].s;
    var joint = ARMS.filter(function(a){ return a.id === "joint_router"; })[0].s;
    var nostate = ARMS.filter(function(a){ return a.id === "joint_no_state"; })[0].s;
    function breakEven(q){ var sil = silentOf(q); if (!sil) return null; return (agent.model_calls - q.model_calls - l*loudOf(q)) / sil; }
    var bj = breakEven(joint), bn = breakEven(nostate);
    var label = ARMS.filter(function(a){ return a.id === bestId; })[0].label;
    call.textContent = "At these weights the cheapest real design is: " + label + ". With visible failures at " + l +
      ", the joint router beats the always-agent while a silent wrong answer costs less than " + (bj === null ? "any amount" : bj.toFixed(1)) +
      " model calls; without session state the threshold is " + (bn === null ? "unbounded" : bn.toFixed(1)) +
      ". The agent's zero failures are assumed, not measured.";
  }
  ws.addEventListener("input", draw); wl.addEventListener("input", draw); draw();
})();

// hypotheses
(function(){
  var tb = document.querySelector("#hypTable tbody");
  D.hypotheses.forEach(function(h){
    var obs = h.id === "H7" ? Object.keys(h.observed).map(function(k){ var o = h.observed[k]; return k + ": " + o.model_calls_saved + " saved / " + o.extra_failures + " extra failures"; }).join("; ")
      : Object.keys(h.observed).map(function(k){ var v = h.observed[k]; return k.replace(/_/g, " ") + ": " + (Array.isArray(v) ? (v.join(", ") || "none") : v); }).join("; ");
    var b = h.verdict === "supported" ? "sup" : h.verdict === "falsified" ? "fal" : "rep";
    tb.appendChild(el("tr", null, [el("td", {cls:"mono", text:h.id}), el("td", null, [el("strong", {text:h.claim}), el("div", {cls:"obs", text:"Predicted: " + h.prediction})]),
      el("td", {cls:"obs", text:obs}), el("td", null, [el("span", {cls:"badge " + b, text:h.verdict})])]));
  });
})();
})();
</script>
</body>
</html>
"""


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--report", type=Path, default=REPORT)
    p.add_argument("--output", type=Path, default=OUT)
    args = p.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(report), encoding="utf-8")
    print(f"Wrote {args.output} ({args.output.stat().st_size // 1024} KiB)")


if __name__ == "__main__":
    main()
