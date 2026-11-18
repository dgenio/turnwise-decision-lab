"""Render the v0.6 trace viewer (demo/index.html) from recorded traces.

Static and self-contained: data embedded as JSON, rendered with textContent,
no network requests. It REPLAYS traces recorded from real local inference; the
page says when and where that inference ran. Nothing is inferred in the browser.
"""
from __future__ import annotations

from html import escape
from pathlib import Path
import json

from .bench import ARM_LABELS, OUT, SETS, load_scenarios
from .render import render_facts

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "demo" / "index.html"
REPO = "https://github.com/dgenio/turnwise-decision-lab"
SHOWCASE = ["C-investigation", "A-greeting", "B-health", "C-errors-flat", "C-no-deploy", "C-flaky-metrics",
            "D-rollback", "D-negated", "E-followup", "F-ambiguous", "F-unknown-service", "G-smoke", "H-concept", "I-search-slow"]
VIEW_ARMS = ("dm_dynamic", "heavy_agent")


def _q(q: dict) -> dict:
    sc = q.get("scores") or {}
    top = sorted(sc.items(), key=lambda kv: -kv[1])[:6]
    return {"name": q["name"], "answer": q.get("answer"), "top": [[k, v] for k, v in top], "kind": q.get("score_kind"),
            "ms": q.get("latency_ms"), "tokens": q.get("input_tokens"), "note": q.get("note", ""), "n_options": len(q.get("options") or [])}


def _obs(o: dict | None) -> dict | None:
    if not o:
        return None
    return {"status": o["status"], "target": o.get("target"), "args": o.get("arguments"), "reason": o.get("reason"),
            "text": o.get("text"), "rendered": render_facts(o["facts"]) if o.get("facts") else ""}


def _step(s: dict) -> dict:
    out = {"i": s["step_index"], "id": s.get("decision_call_id"), "continue": s.get("continue_reason"), "terminate": s.get("terminate_reason")}
    d = s.get("decision")
    if d:
        out["decision"] = {"op": d["operation"], "target": d.get("target"), "args": d.get("arguments"), "tier": d.get("model_tier"),
                           "provider": d.get("provider"), "model": d.get("model"), "ms": d.get("latency_ms"), "tokens": d.get("input_tokens"),
                           "rationale": d.get("rationale"), "questions": [_q(q) for q in d.get("questions", [])]}
    if s.get("validation"):
        out["validation"] = s["validation"]
    out["observation"] = _obs(s.get("observation"))
    if s.get("tool_calls"):
        out["tool_calls"] = [{"target": c["decision"]["target"], "args": c["decision"]["arguments"], "validation": c["validation"],
                              "observation": _obs(c["observation"])} for c in s["tool_calls"]]
    if s.get("context"):
        c = s["context"]
        out["context"] = {"policy": c["decision"]["policy"], "proposed": c["decision"]["proposed"],
                          "questions": [_q(q) for q in c["decision"]["questions"]],
                          "included": c["assembled"]["included"], "excluded": c["assembled"]["excluded"],
                          "tokens": c["assembled"]["tokens"], "counter": c["assembled"]["token_counter"],
                          "messages": c["assembled"]["messages"]}
    g = s.get("generation")
    if g:
        out["generation"] = {"tier": g.get("tier"), "model": g.get("model"), "status": g.get("status"), "text": g.get("text"),
                             "prompt_tokens": g.get("prompt_tokens"), "cached": g.get("cached_prompt_tokens"),
                             "completion_tokens": g.get("completion_tokens"), "ms": round((g.get("prefill_ms") or 0) + (g.get("decode_ms") or 0), 1)}
    return out


def page_data() -> dict:
    scen = {s["id"]: s for s in load_scenarios(SETS["dev"])}
    arms, prov = {}, {}
    for arm in VIEW_ARMS:
        p = OUT / "traces" / "dev" / f"{arm}.json"
        data = json.loads(p.read_text())
        prov[arm] = data["provenance"]
        arms[arm] = {t["scenario_id"]: {"steps": [_step(s) for s in t["steps"]], "final": t["final"], "totals": t["totals"],
                                        "score": t["score"]} for t in data["traces"]}
    summary = json.loads((OUT / "summary.json").read_text())
    return {"scenarios": [{"id": i, "message": scen[i]["message"], "variant": scen[i]["world_variant"],
                           "conversation": scen[i].get("conversation", []), "category": scen[i]["category"],
                           "note": scen[i]["expect"]["note"]} for i in SHOWCASE if i in scen and all(i in arms[a] for a in VIEW_ARMS)],
            "arms": arms, "labels": {a: ARM_LABELS[a] for a in ARM_LABELS}, "provenance": prov,
            "heldout": summary["sets"].get("heldout", {}), "predictions": summary.get("predictions", []),
            "not_run": summary.get("arms_not_run", {}), "qce": summary.get("quality_constrained")}


def render() -> str:
    data = json.dumps(page_data(), ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    data = data.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return TEMPLATE.replace("{{REPO}}", REPO).replace("__DATA__", data)


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Turnwise Decision Loop</title>
<meta name="description" content="A lightweight decision model repeatedly chooses an agent's next operation; every result can trigger a new decision. Recorded real local inference, compared with a heavy-only LLM agent.">
<style>
:root{color-scheme:light;--bg:#f6f5f2;--surface:#fcfcfb;--raised:#fff;--line:#e3e1db;--line-strong:#cfccc4;--text:#0b0b0b;--text-2:#52514e;--muted:#77756f;
--accent:#1c5cab;--dec:#2a78d6;--tool:#008300;--gen:#6250d6;--host:#52514e;--good:#0ca30c;--warn:#fab219;--crit:#d03b3b;--code:#f1f0ec;--track:#ecebe7}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#121211;--surface:#1a1a19;--raised:#212120;--line:#2f2f2c;--line-strong:#3d3d39;
--text:#f0efec;--text-2:#c3c2b7;--muted:#9a998f;--accent:#86b6ef;--dec:#3987e5;--tool:#0ca30c;--gen:#9085e9;--host:#c3c2b7;--code:#151514;--track:#2a2a28}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#121211;--surface:#1a1a19;--raised:#212120;--line:#2f2f2c;--line-strong:#3d3d39;
--text:#f0efec;--text-2:#c3c2b7;--muted:#9a998f;--accent:#86b6ef;--dec:#3987e5;--tool:#0ca30c;--gen:#9085e9;--host:#c3c2b7;--code:#151514;--track:#2a2a28}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:16px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif}
a{color:var(--accent)}code,.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.86em}
main{max-width:1240px;margin:0 auto;padding:24px 16px 72px}
.top{display:flex;justify-content:space-between;gap:12px;align-items:center;font-size:.84rem;color:var(--muted)}
.top nav{display:flex;gap:14px;flex-wrap:wrap}.top button{font:inherit;color:var(--text-2);background:none;border:1px solid var(--line-strong);border-radius:8px;padding:4px 10px;cursor:pointer}
.eyebrow{margin:32px 0 8px;font-size:.78rem;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);font-weight:650}
h1{font-size:clamp(1.8rem,4.2vw,3rem);line-height:1.08;letter-spacing:-.025em;margin:0 0 14px;max-width:24ch}
h2{font-size:1.4rem;margin:0 0 6px}.lede{font-size:1.05rem;color:var(--text-2);max-width:74ch;margin:0}
section{margin-top:44px}.sub{color:var(--text-2);max-width:78ch;margin:0 0 14px}
.prov{margin-top:18px;border:1px solid var(--line);background:var(--surface);border-radius:12px;padding:12px 14px;font-size:.88rem;color:var(--text-2);overflow-wrap:anywhere}
.card,.small,.request,.col{overflow-wrap:anywhere;min-width:0}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;margin-top:10px;font-size:.82rem;color:var(--text-2)}
.legend span{display:inline-flex;gap:6px;align-items:center}.dot{width:10px;height:10px;border-radius:3px;display:inline-block}
.picker{display:flex;flex-wrap:wrap;gap:6px;margin:12px 0}
.picker button{font:inherit;font-size:.82rem;border:1px solid var(--line-strong);background:var(--surface);color:var(--text);border-radius:999px;padding:5px 11px;cursor:pointer}
.picker button[aria-pressed="true"]{background:var(--text);color:var(--bg);border-color:var(--text)}
.request{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin-bottom:14px}
.request .q{font-size:1.25rem;font-weight:620;line-height:1.3}.request .meta{font-size:.82rem;color:var(--muted);margin-top:4px}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:16px;align-items:start}
.col{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px}
.col h3{margin:0 0 2px;font-size:1rem}.col .sub2{font-size:.8rem;color:var(--muted);margin-bottom:10px}
.totals{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px;margin:8px 0 12px}
.totals div{border:1px solid var(--line);border-radius:8px;padding:6px 8px;background:var(--raised)}.totals b{display:block;font-size:1.05rem;font-variant-numeric:tabular-nums}.totals small{color:var(--muted);font-size:.72rem}
ol.tl{list-style:none;margin:0;padding:0;position:relative}
ol.tl>li{position:relative;padding:0 0 12px 22px}ol.tl>li::before{content:"";position:absolute;left:6px;top:14px;bottom:0;width:2px;background:var(--line)}
ol.tl>li:last-child::before{display:none}
.card{border:1px solid var(--line);border-left:4px solid var(--host);border-radius:10px;background:var(--raised);padding:9px 11px}
.card.dec{border-left-color:var(--dec)}.card.tool{border-left-color:var(--tool)}.card.gen{border-left-color:var(--gen)}.card.final{border-left-color:var(--text)}
.card.bad{border-left-color:var(--crit)}.card.hold{border-left-color:var(--warn)}
.pin{position:absolute;left:0;top:10px;width:14px;height:14px;border-radius:50%;background:var(--surface);border:3px solid var(--host)}
.pin.dec{border-color:var(--dec)}.pin.tool{border-color:var(--tool)}.pin.gen{border-color:var(--gen)}.pin.final{border-color:var(--text)}
.kind{font-size:.68rem;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);font-weight:650}
.title{font-weight:640;margin:2px 0 4px;word-break:break-word}.small{font-size:.8rem;color:var(--text-2)}
.bars{display:grid;gap:3px;margin:6px 0}.bar{display:grid;grid-template-columns:minmax(0,150px) 1fr 44px;gap:6px;align-items:center;font-size:.76rem}
.bar .lab{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.bar .tr{height:7px;border-radius:4px;background:var(--track);overflow:hidden}
.bar .fl{height:7px;border-radius:4px;background:var(--dec)}.bar.sel .lab{font-weight:700}.bar .v{text-align:right;font-variant-numeric:tabular-nums;color:var(--text-2)}
.chips{display:flex;flex-wrap:wrap;gap:4px;margin:4px 0}.chip{font:.72rem ui-monospace,monospace;border:1px solid var(--line-strong);border-radius:999px;padding:1px 7px}
.chip.in{border-color:var(--tool)}.chip.out{color:var(--muted);text-decoration:line-through}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:var(--code);border:1px solid var(--line);border-radius:8px;padding:8px;font-size:.74rem;line-height:1.45;max-height:300px;overflow:auto;margin:6px 0 0}
details summary{cursor:pointer;font-size:.8rem;color:var(--accent)}
.verdict{display:inline-flex;gap:6px;align-items:center;font-size:.8rem;font-weight:650;border-radius:999px;padding:1px 9px;border:1px solid var(--line-strong)}
.verdict.ok{border-color:var(--good)}.verdict.no{border-color:var(--crit)}
table{width:100%;border-collapse:collapse;font-size:.86rem}th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:.72rem;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);font-weight:600}td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:12px;overflow-x:auto}
.two{display:grid;grid-template-columns:1fr 1fr;gap:16px}.list{margin:6px 0 0;padding-left:18px;color:var(--text-2);font-size:.92rem}
footer{margin-top:56px;padding-top:18px;border-top:1px solid var(--line);font-size:.88rem;color:var(--text-2)}
@media (max-width:900px){.cols,.two{grid-template-columns:1fr}.totals{grid-template-columns:repeat(2,minmax(0,1fr))}.top nav{display:none}}
</style>
</head>
<body>
<main>
<div class="top"><span>Turnwise Decision Lab · v0.6</span><nav><a href="#trace">Trace</a><a href="#results">Held-out results</a><a href="#limits">Limits</a><a href="v05-explorer.html">v0.5 explorer</a><a href="{{REPO}}">Source</a></nav><button type="button" id="theme">Theme</button></div>
<p class="eyebrow">Route the work, not just the model · decision-driven agent control</p>
<h1>One user turn, many decisions, each one made after the last result came back.</h1>
<p class="lede">A trained lightweight decision model picks the agent's next operation: a tool, a workflow, a light or heavy generation model, finishing with verified data, or a clarifying question. An independent host validates every proposal before it runs, and each result feeds the next decision. Below, the same request handled by this loop and by a conventional agent whose whole loop is the heavy LLM.</p>
<div class="prov" id="prov"></div>

<section id="trace" aria-labelledby="t-h">
<h2 id="t-h">Pick a request</h2>
<div class="picker" id="picker" role="group" aria-label="Scenario"></div>
<div class="request" id="request"></div>
<div class="cols"><div class="col" id="colA"></div><div class="col" id="colB"></div></div>
</section>

<section id="results" aria-labelledby="r-h">
<h2 id="r-h">Held-out results (30 tasks written by an independent agent)</h2>
<p class="sub">Success is checked from the outcome alone: the right kind of reply, the needed evidence actually gathered, answer content, and no forbidden or executed write. Cost comes after success. Latency is local CPU time, and no provider was billed.</p>
<div class="panel"><table id="resTable"></table></div>
<h3 style="margin-top:20px">Pre-registered predictions</h3>
<div class="panel"><table id="predTable"></table></div>
<h3 style="margin-top:20px">Quality-constrained reading (added after the run)</h3>
<p class="sub">The project's <a href="{{REPO}}/blob/main/docs/quality-constrained-efficiency-v06.md">quality-constrained efficiency protocol</a> asks a different question. Is the cheaper architecture <em>no worse</em> than the heavy-only agent, within a margin agreed in advance? Only if it is does cost per attempted task count. No margin has been agreed, so no arm passes that gate yet. The table shows how wide a margin each arm would need, given its paired 95% interval on these 30 tasks.</p>
<div class="panel"><table id="qceTable"></table></div>
</section>

<section id="limits" aria-labelledby="l-h">
<h2 id="l-h">What is real and what is not</h2>
<div class="two">
<div><h3>Observed</h3><ul class="list">
<li>Every decision in these traces is real local inference by turnwise-dm. Its inputs are a trained head, one cached scoring pass of Qwen3.5-0.8B and s1-llm-auto-router; the operation comes from that inference, not a fixture.</li>
<li>Every tool and workflow really ran through the host's permission harness, against a synthetic world.</li>
<li>Every generation is real output from Qwen2.5-0.5B (light tier) or Qwen3.5-0.8B (heavy tier and heavy-only agent).</li>
<li>Token counts come from each model's tokenizer; latencies were measured on the CPU named above.</li></ul></div>
<div><h3>Not shown or not measured</h3><ul class="list">
<li>Hosted decision services (OpenAI Decisions, Jev): adapters exist, but none was called. There were no credentials and no approved spend.</li>
<li>Frontier models. "Heavy" here is a 0.8B model on CPU, so the conclusions hold at this scale only.</li>
<li>Dollar costs, hosted latency, and answer quality beyond the lexical checks.</li>
<li>This page replays recorded traces and runs no inference in your browser.</li></ul></div>
</div>
</section>
<footer><p>Reproduce: <code>python -m unittest discover -s tests</code> (no models). To re-run real inference: <code>python -m scripts.fetch_models</code>, then <code>python -m turnwise_lab.agent.bench --set heldout --arms all</code>. <a href="{{REPO}}/blob/main/reports/v06/summary.md">Full report</a> · <a href="{{REPO}}/blob/main/docs/preregistration-v0.6.md">Pre-registration</a> · <a href="v05-explorer.html">v0.5 explorer (historical)</a> · <a href="local-run.html">v0.4 receipts</a>. All data is synthetic. MIT.</p></footer>
</main>
<script type="application/json" id="data">__DATA__</script>
<script>
(function(){"use strict";
var D=JSON.parse(document.getElementById("data").textContent);
function el(t,a,k){var n=document.createElement(t);if(a)for(var x in a){if(x==="text")n.textContent=a[x];else if(x==="cls")n.className=a[x];else n.setAttribute(x,a[x]);}
(k||[]).forEach(function(c){if(c!=null)n.appendChild(typeof c==="string"?document.createTextNode(c):c);});return n;}
function fmtArgs(a){return a?Object.keys(a).map(function(k){return k+"="+a[k];}).join(", "):"";}
function ms(v){return v==null?"n/a":(v>=1000?(v/1000).toFixed(1)+" s":Math.round(v)+" ms");}
(function(){var r=document.documentElement,b=document.getElementById("theme");try{var t=localStorage.getItem("tw-theme");if(t)r.setAttribute("data-theme",t);}catch(e){}
b.addEventListener("click",function(){var dark=r.getAttribute("data-theme")?r.getAttribute("data-theme")==="dark":matchMedia("(prefers-color-scheme: dark)").matches;var n=dark?"light":"dark";r.setAttribute("data-theme",n);try{localStorage.setItem("tw-theme",n);}catch(e){}});})();
(function(){var p=D.provenance.dm_dynamic||{};var box=document.getElementById("prov");
box.appendChild(el("div",null,[el("strong",{text:"Recorded, then replayed. "}),"Inference ran on "+(p.recorded_at_utc||"?")+" on "+(p.cpu||"a local CPU")+" ("+(p.cpu_threads||"?")+" threads, onnxruntime "+(p.onnxruntime||"?")+"), "+(p.where||"")+". Decoding was greedy. One-off prefix cache fills, not charged to any turn: "+Object.keys(p.cold_start||{}).map(function(k){return k.replace(/_/g," ").replace(/ ms$/,"")+" "+ms(p.cold_start[k]);}).join(", ")+"."]));
var lg=el("div",{cls:"legend"});[["dec","observed decision-model inference"],["tool","executed tool or workflow call"],["gen","observed generation-model inference"],["host","host decision (validation, finalisation)"]].forEach(function(x){lg.appendChild(el("span",null,[el("i",{cls:"dot",style:"background:var(--"+x[0]+")"}),x[1]]));});
lg.appendChild(el("span",{text:"World data is synthetic. Bars are model scores; see each card for what the score means."}));box.appendChild(lg);})();
function bars(q){var b=el("div",{cls:"bars"});(q.top||[]).forEach(function(kv){var sel=kv[0]===q.answer;b.appendChild(el("div",{cls:"bar"+(sel?" sel":"")},[el("span",{cls:"lab",title:kv[0],text:(sel?"▶ ":"")+kv[0]}),el("div",{cls:"tr"},[el("div",{cls:"fl",style:"width:"+(100*kv[1]).toFixed(1)+"%"})]),el("span",{cls:"v",text:kv[1].toFixed(2)})]));});return b;}
function item(kind,card){return el("li",null,[el("span",{cls:"pin "+kind}),card]);}
function decisionCard(s){var d=s.decision,q=d.questions[0];var c=el("div",{cls:"card dec"});
c.appendChild(el("div",{cls:"kind",text:"decision "+(s.i+1)+" · "+d.provider+" · "+ms(d.ms)+(d.tokens?" · "+d.tokens+" input tokens":"")}));
var what=d.op==="call_tool"||d.op==="call_workflow"?d.target+"("+fmtArgs(d.args)+")":(d.op==="call_model"?d.tier+" model":d.op);
c.appendChild(el("div",{cls:"title",text:"→ "+what}));
if(q&&q.top&&q.top.length){c.appendChild(el("div",{cls:"small",text:"Evaluated "+q.n_options+" admissible operations; top scores:"}));c.appendChild(bars(q));c.appendChild(el("div",{cls:"small",text:"Score: "+q.kind+". "+(q.note||"")}));}
d.questions.slice(1).forEach(function(x){var line=x.name+": "+x.answer+(x.note?" ("+x.note+")":"");c.appendChild(el("div",{cls:"small",text:line}));});
if(s.validation){c.appendChild(el("div",{cls:"small"},[el("strong",{text:"Host: "}),s.validation.status+" ("+s.validation.reason+")"]));}
return item("dec",c);}
function obsCard(o,label){var bad=o.status!=="ok";var c=el("div",{cls:"card tool"+(o.status==="approval_required"?" hold":(bad?" bad":""))});
c.appendChild(el("div",{cls:"kind",text:label}));c.appendChild(el("div",{cls:"title",text:(o.target||"")+"("+fmtArgs(o.args)+") → "+o.status}));
if(o.rendered)c.appendChild(el("pre",{text:o.rendered}));else if(o.text||o.reason)c.appendChild(el("div",{cls:"small",text:o.text||o.reason}));return item("tool",c);}
function ctxCard(cx){var c=el("div",{cls:"card gen"});c.appendChild(el("div",{cls:"kind",text:"context selection · "+cx.policy+" · prompt "+cx.tokens+" tokens ("+cx.counter+")"}));
var inc=el("div",{cls:"chips"});cx.included.forEach(function(b){inc.appendChild(el("span",{cls:"chip in",title:b.trust+" · "+b.source,text:b.id+(b.mandatory?" (mandatory)":"")+" "+b.tokens}));});
var exc=el("div",{cls:"chips"});cx.excluded.forEach(function(b){exc.appendChild(el("span",{cls:"chip out",title:b.reason,text:b.id+": "+b.reason}));});
c.appendChild(el("div",{cls:"small",text:"Included:"}));c.appendChild(inc);c.appendChild(el("div",{cls:"small",text:"Excluded:"}));c.appendChild(exc);
if(cx.questions&&cx.questions.length&&cx.questions[0].top&&cx.questions[0].top.length){var tbl=el("div",{cls:"small",text:"Per-block decisions: "+cx.questions.map(function(q){return q.name.replace("include:","")+"="+q.answer+(q.top&&q.top.length?"("+q.top.filter(function(kv){return kv[0]==="yes";}).map(function(kv){return kv[1].toFixed(2);})[0]+")":"");}).join(", ")});c.appendChild(tbl);}
var det=el("details",null,[el("summary",{text:"Show the exact assembled prompt"}),el("pre",{text:cx.messages.map(function(m){return "["+m.role+"]\n"+m.content;}).join("\n\n")})]);c.appendChild(det);return item("gen",c);}
function genCard(g,label){var c=el("div",{cls:"card gen"});c.appendChild(el("div",{cls:"kind",text:label+" · "+g.tier+" · "+g.model+" · "+(g.prompt_tokens||0)+" new prompt tokens"+(g.cached?" + "+g.cached+" cached":"")+" → "+(g.completion_tokens||0)+" generated · "+ms(g.ms)}));
c.appendChild(el("pre",{text:g.text||""}));return item("gen",c);}
function finalCard(t){var sc=t.score,ok=sc.success;var c=el("div",{cls:"card final"+(ok?"":" bad")});c.appendChild(el("div",{cls:"kind",text:"final · "+t.final.kind+" · by "+t.final.by}));
c.appendChild(el("pre",{text:t.final.text||""}));var v=el("span",{cls:"verdict "+(ok?"ok":"no"),text:ok?"✓ outcome check passed":"✗ outcome check failed"});c.appendChild(v);
if(!ok){var why=[];if(sc.missing_facts.length)why.push("missing "+sc.missing_facts.join(", "));if(sc.false_clarify)why.push("clarified instead of answering");if(sc.dropped_action)why.push("action not raised");if(!why.length)why.push("answer content check failed");c.appendChild(el("div",{cls:"small",text:why.join("; ")}));}
return item("final",c);}
function column(box,arm,sid){var t=D.arms[arm][sid];box.textContent="";box.appendChild(el("h3",{text:arm==="dm_dynamic"?"Decision-driven loop (turnwise-dm)":"Heavy-only agent (native tool calling)"}));
box.appendChild(el("div",{cls:"sub2",text:D.labels[arm]}));var tt=t.totals,g=tt.generation_calls||{};
var tot=el("div",{cls:"totals"});[["wall time",ms(tt.wall_ms)],["decision calls",String(tt.decision_calls)],["tool calls",String(tt.tool_calls)],["LLM calls (light/heavy)",(g.light||0)+" / "+(g.heavy||0)]].forEach(function(x){tot.appendChild(el("div",null,[el("b",{text:x[1]}),el("small",{text:x[0]})]));});box.appendChild(tot);
var ol=el("ol",{cls:"tl"});t.steps.forEach(function(s){
 if(arm==="dm_dynamic"){if(s.decision)ol.appendChild(decisionCard(s));if(s.observation&&s.observation.status!=="generated"&&s.observation.status!=="needs_evidence"&&s.observation.status!=="rejected")ol.appendChild(obsCard(s.observation,"executed by host"));
  if(s.observation&&(s.observation.status==="rejected"||s.observation.status==="needs_evidence")){var c=el("div",{cls:"card bad"},[el("div",{cls:"kind",text:"observation added to state"}),el("div",{cls:"small",text:s.observation.status+": "+(s.observation.reason||s.observation.text||"")})]);ol.appendChild(item("host",c));}
  if(s.context)ol.appendChild(ctxCard(s.context));if(s.generation)ol.appendChild(genCard(s.generation,"generation"));
  if(s["continue"])ol.appendChild(item("host",el("div",{cls:"card"},[el("div",{cls:"kind",text:"why the loop continues"}),el("div",{cls:"small",text:s["continue"]})])));}
 else{if(s.generation)ol.appendChild(genCard(s.generation,"LLM step "+(s.i+1)));(s.tool_calls||[]).forEach(function(tc){ol.appendChild(obsCard(Object.assign({},tc.observation,{target:tc.target,args:tc.args}),"host validated: "+tc.validation.status));});}
});ol.appendChild(finalCard(t));box.appendChild(ol);}
var cur=null;function show(sid){cur=sid;var s=D.scenarios.filter(function(x){return x.id===sid;})[0];
[].forEach.call(document.querySelectorAll("#picker button"),function(b){b.setAttribute("aria-pressed",String(b.dataset.id===sid));});
var r=document.getElementById("request");r.textContent="";(s.conversation||[]).forEach(function(m){r.appendChild(el("div",{cls:"meta",text:"earlier "+m.role+": "+m.content}));});
r.appendChild(el("div",{cls:"q",text:"“"+s.message+"”"}));r.appendChild(el("div",{cls:"meta",text:"world: "+s.variant+" · "+s.category+" · expected: "+s.note}));
column(document.getElementById("colA"),"dm_dynamic",sid);column(document.getElementById("colB"),"heavy_agent",sid);}
var pk=document.getElementById("picker");D.scenarios.forEach(function(s){var b=el("button",{type:"button","aria-pressed":"false",text:s.id});b.dataset.id=s.id;b.addEventListener("click",function(){show(s.id);});pk.appendChild(b);});
show(D.scenarios[0].id);
(function(){var t=document.getElementById("resTable"),H=D.heldout;var hd=el("tr");["Architecture","Success","Silent failures","Heavy calls","Heavy tokens","Decision calls","p50 / p95","Compute per success"].forEach(function(h,i){hd.appendChild(el("th",{text:h}));});t.appendChild(el("thead",null,[hd]));var tb=el("tbody");
Object.keys(H).forEach(function(a){var s=H[a].summary;tb.appendChild(el("tr",null,[el("td",{text:D.labels[a]}),el("td",{cls:"n",text:s.successes+"/"+s.tasks}),el("td",{cls:"n",text:String(s.silent_failures)}),el("td",{cls:"n",text:String(s.heavy_calls)}),el("td",{cls:"n",text:s.heavy_tokens.toLocaleString("en-US")}),el("td",{cls:"n",text:String(s.decision_calls)}),el("td",{cls:"n",text:ms(s.wall_ms_p50)+" / "+ms(s.wall_ms_p95)}),el("td",{cls:"n",text:s.local_compute_s_per_success==null?"n/a":s.local_compute_s_per_success+" s"})]));});
Object.keys(D.not_run).forEach(function(k){tb.appendChild(el("tr",null,[el("td",{text:k}),el("td",{cls:"n",text:"not run"}),el("td",{colspan:"6",text:D.not_run[k]})]));});t.appendChild(tb);
var p=document.getElementById("predTable");var h2=el("tr");["ID","Prediction","Verdict"].forEach(function(h){h2.appendChild(el("th",{text:h}));});p.appendChild(el("thead",null,[h2]));var pb=el("tbody");
D.predictions.forEach(function(x){pb.appendChild(el("tr",null,[el("td",{cls:"mono",text:x.id}),el("td",null,[x.prediction,el("div",{cls:"small",text:"observed: "+JSON.stringify(x.observed)})]),el("td",null,[el("span",{cls:"verdict "+(x.verdict==="supported"?"ok":"no"),text:x.verdict})])]));});p.appendChild(pb);
var q=document.getElementById("qceTable");if(D.qce){var h3=el("tr");["Architecture","Success","Difference vs heavy-only (95% CI)","Margin it would need","Compute per attempted task","Heavy input tokens per heavy call (tool schemas)"].forEach(function(h){h3.appendChild(el("th",{text:h}));});q.appendChild(el("thead",null,[h3]));var qb=el("tbody");
var sg=function(v){return (v>0?"+":"")+v.toFixed(1);};
D.qce.rows.forEach(function(r){var v=r.vs_reference;qb.appendChild(el("tr",null,[el("td",{text:D.labels[r.arm]}),el("td",{cls:"n",text:r.successes+"/"+r.tasks}),el("td",{cls:"n",text:v?sg(v.difference_pp)+" pp ("+sg(v.ci95_pp[0])+" to "+sg(v.ci95_pp[1])+")":"reference"}),el("td",{cls:"n",text:v?r.margin_needed_pp.toFixed(1)+" pp":"-"}),el("td",{cls:"n",text:r.local_compute_s_per_task+" s"}),el("td",{cls:"n",text:r.heavy_input_tokens_per_heavy_call==null?"no heavy calls":Math.round(r.heavy_input_tokens_per_heavy_call).toLocaleString("en-US")+" ("+Math.round(r.heavy_schema_tokens_per_heavy_call).toLocaleString("en-US")+")"})]));});q.appendChild(qb);}})();
})();
</script>
</body>
</html>
"""


def main() -> None:
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(render(), encoding="utf-8")
    print(f"Wrote {PAGE} ({PAGE.stat().st_size // 1024} KiB)")


if __name__ == "__main__":
    main()
