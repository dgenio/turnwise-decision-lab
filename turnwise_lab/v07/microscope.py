"""Render the Decision Microscope (demo/microscope.html) from the recorded v0.7 traces.

Static and self-contained: data embedded as JSON, rendered with DOM text nodes,
no network requests, no tracking. Every cell is a recorded real run on the
pinned local models; nothing is inferred in the browser and nothing on the page
is a counterfactual.

    python -m turnwise_lab.v07.microscope
"""
from __future__ import annotations

from pathlib import Path
import json

from ..agent.render import render_facts
from .bench import ARM_LABELS, ARMS, PAIRS, SETS, report, score, trace_path
from .tasks import load_tasks

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "demo" / "microscope.html"
REPO = "https://github.com/dgenio/turnwise-decision-lab"
SHORT = {"heavy_agent": "Agent", "heavy_agent_gated": "Agent + gate", "rules": "Rules", "rules_gated": "Rules + gate",
         "dm_dynamic": "Learned head", "dm_dynamic_gated": "Learned head + gate", "contract": "Contract planner",
         "contract_narrated": "Planner, narrated"}


def _clip(text, n=1400):
    text = text or ""
    return text if len(text) <= n else text[:n] + " […]"


def _obs(o):
    if not o:
        return None
    return {"s": o["status"], "t": o.get("target"), "a": o.get("arguments") or {}, "r": o.get("reason") or "",
            "f": _clip(render_facts(o["facts"]), 700) if o.get("facts") else ""}


def _decision(d):
    q = next((x for x in d.get("questions") or [] if x.get("scores")), None)
    gate = next((x for x in d.get("questions") or [] if x["name"] == "exit_gate"), None)
    plan = next((x for x in d.get("questions") or [] if x["name"] == "plan"), None)
    return {"op": d["operation"], "t": d.get("target"), "a": d.get("arguments") or {}, "tier": d.get("model_tier"), "by": d.get("provider") or "",
            "ms": d.get("latency_ms"), "tok": d.get("input_tokens"), "why": d.get("rationale") or (plan or {}).get("note") or "",
            "top": round(max(q["scores"].values()), 3) if q else None,
            "esc": any(x["name"] == "escalation" for x in d.get("questions") or []),
            "gate": {"answer": gate["answer"], "note": gate.get("note", "")} if gate else None}


def _step(s):
    out = {"i": s["step_index"], "cont": s.get("continue_reason"), "term": s.get("terminate_reason")}
    if s.get("decision"):
        out["d"] = _decision(s["decision"])
    if s.get("validation"):
        out["v"] = s["validation"]["status"]
    if s.get("observation"):
        out["o"] = _obs(s["observation"])
    if s.get("tool_calls"):
        out["calls"] = [{"by": c["decision"].get("provider"), "t": c["decision"]["target"], "a": c["decision"].get("arguments") or {},
                         "v": c["validation"]["status"], "o": _obs(c["observation"])} for c in s["tool_calls"]]
    g = s.get("generation")
    if g:
        out["g"] = {"tier": g.get("tier"), "text": _clip(g.get("withheld_text") or g.get("text")), "withheld": "withheld_text" in g,
                    "pt": g.get("prompt_tokens"), "ct": g.get("completion_tokens"), "cached": g.get("cached_prompt_tokens"),
                    "ms": round((g.get("prefill_ms") or 0) + (g.get("decode_ms") or 0)),
                    "viol": [v["text"] for v in (g.get("grounding") or {}).get("violations", [])]}
    if s.get("context"):
        out["ctx"] = [[b["id"], b["tokens"]] for b in s["context"]["assembled"]["included"]]
    e = s.get("exit_gate")
    if e:
        out["gate"] = {"action": e["action"], "reason": e["reason"], "missing": e.get("missing") or [], "source": e.get("source"),
                       "viol": [v["text"] for v in (e.get("grounding") or {}).get("violations", [])]}
    return out


def _cell(task, tr):
    sc = score(task, tr)
    tot = tr["totals"]
    gens = [s["generation"] for s in tr["steps"] if s.get("generation") and s["generation"].get("status") == "ok"]
    ctx_tok = sum((q.get("input_tokens") or 0) for s in tr["steps"] if s.get("context") for q in s["context"]["decision"].get("questions", []))
    state = "pass" if sc["success"] else ("silent" if sc["silent_failure"] else "visible")
    return {
        "state": state, "serious": sc["serious_failure"], "kind": sc["final_kind"],
        "flags": [k for k in ("dropped_action", "one_sided_causal_claim", "claims_side_effect", "false_clarify") if sc[k]]
                 + (["ungrounded_values"] if sc["ungrounded_values"] else []) + (["unrequested_write_attempt"] if sc["unsafe_write_attempts"] else []),
        "missing": sc["missing_facts"], "via_context": sc["evidence_via_context"],
        "final": {"text": _clip(tr["final"].get("text"), 2200), "by": tr["final"].get("by"), "withheld": _clip(tr["final"].get("withheld_text"))},
        "plan": ({"type": tr["plan"]["claim"].get("type"), "route": tr["plan"]["route"], "cues": tr["plan"]["claim"].get("cues", []),
                  "need": [r["need"] for r in tr["plan"]["contract"]["requirements"]]} if tr.get("plan") else None),
        "steps": [_step(s) for s in tr["steps"]],
        "cost": {"wall": round(tot.get("wall_ms", 0)), "tools": tot.get("tool_calls", 0), "heavy": sc["heavy_calls"], "light": sc["light_calls"],
                 "ctl_tok": (tot.get("decision_input_tokens") or 0) + ctx_tok, "ctl_ms": round(tot.get("decision_latency_ms") or 0),
                 "gen_new": sum((g.get("prompt_tokens") or 0) + (g.get("completion_tokens") or 0) for g in gens),
                 "cached": sum(g.get("cached_prompt_tokens") or 0 for g in gens), "gate": tot.get("gate_interventions", 0)},
    }


def page_data() -> dict:
    rep = report()
    out = {"repo": REPO, "arms": [{"id": a, "short": SHORT[a], "label": ARM_LABELS[a]} for a in ARMS], "pairs": [list(p) for p in PAIRS], "sets": {}}
    for name in ("locked", "dev"):
        block = rep["sets"].get(name)
        if not block:
            continue
        tasks = load_tasks(SETS[name])
        arms = [a for a in ARMS if a in block["arms"]]
        traces = {a: {t["scenario_id"]: t for t in json.loads(trace_path(name, a).read_text())["traces"]} for a in arms}
        prov = block["arms"][arms[0]]["provenance"]
        out["sets"][name] = {
            "arms": arms,
            "provenance": {"recorded": prov["recorded_at_utc"], "cpu": prov["cpu"], "commit": (prov.get("git_commit_at_run") or "")[:8],
                           "heavy": prov["models"].get("dm_lm", {}).get("version", "")},
            "summary": {a: {"ok": block["arms"][a]["summary"]["successes"], "n": block["arms"][a]["summary"]["tasks"],
                            "serious": block["arms"][a]["summary"]["serious_failure"], "silent": block["arms"][a]["summary"]["silent_failures"],
                            "s": block["arms"][a]["summary"]["local_compute_s_per_task"],
                            "tok": block["arms"][a]["accounting"]["qwen35_tokens_computed_per_task"],
                            "tools": block["arms"][a]["accounting"]["calls_per_task"]["tools"]} for a in arms},
            "tasks": [{"id": t["id"], "cat": t["category"], "claim": t["claim_type"], "world": t["world_variant"], "msg": t["message"],
                       "convo": t["conversation"],
                       "gold": {"outcome": t["expect"]["outcome"], "facts": t["expect"]["required_facts"], "ref": t["expect"]["reference_answer"],
                                "approval": t["expect"]["approval_target"], "note": t["expect"].get("note", "")},
                       "cells": {a: _cell(t, traces[a][t["id"]]) for a in arms}} for t in tasks],
        }
    return out


CSS = """
:root{--bg:#f6f5f1;--surface:#fcfcfb;--ink:#1b1b1a;--ink2:#55544f;--ink3:#7c7b74;--line:#e1e0d9;--line2:#c3c2b7;--accent:#2f5fb3;
--good:#0ca30c;--warn:#fab219;--serious:#ec835a;--crit:#d03b3b;--chip:#eeede7;--gate:#e8eefb;--gateink:#1f458a;--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
@media (prefers-color-scheme:dark){:root{--bg:#121211;--surface:#1a1a19;--ink:#f0efea;--ink2:#b9b8b0;--ink3:#8d8c85;--line:#2c2c2a;--line2:#383835;--accent:#8fb2f0;
--chip:#262624;--gate:#1c2740;--gateink:#b9cdf5}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
a{color:var(--accent)}main{max-width:1280px;margin:0 auto;padding:20px 16px 64px}
h1{font-size:26px;line-height:1.2;margin:0 0 6px;letter-spacing:-.01em}h2{font-size:17px;margin:28px 0 8px}h3{font-size:14px;margin:0 0 6px}
p{margin:6px 0}.lede{font-size:16px;color:var(--ink2);max-width:76ch}.small{font-size:13px;color:var(--ink2)}.muted{color:var(--ink3)}
.card{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:14px}
.note{border-left:3px solid var(--warn);padding:8px 12px;background:var(--surface);border-radius:0 8px 8px 0;margin:12px 0;font-size:14px}
.bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:10px 0}
button,select,input{font:inherit;color:inherit}
.seg{display:inline-flex;border:1px solid var(--line2);border-radius:8px;overflow:hidden}
.seg button{border:0;background:transparent;padding:6px 12px;cursor:pointer}.seg button[aria-pressed=true]{background:var(--ink);color:var(--surface)}
.chipb{border:1px solid var(--line2);background:transparent;border-radius:999px;padding:4px 11px;cursor:pointer;font-size:13px}
.chipb[aria-pressed=true]{background:var(--accent);border-color:var(--accent);color:#fff}
select{background:var(--surface);border:1px solid var(--line2);border-radius:8px;padding:5px 8px;max-width:100%}
button:focus-visible,select:focus-visible,td button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:12px;font-weight:600;color:var(--ink2);white-space:nowrap}td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.track{display:inline-block;width:90px;height:8px;background:var(--chip);border-radius:4px;vertical-align:middle;margin-right:6px}
.fill{display:block;height:8px;border-radius:4px;background:var(--accent)}
#matrix th.arm{writing-mode:vertical-rl;transform:rotate(180deg);height:128px;vertical-align:bottom;padding:6px 3px;font-weight:500}
#matrix td.c{padding:3px;text-align:center}#matrix td.q{min-width:230px;max-width:420px}
#matrix tr.sel td.q{box-shadow:inset 3px 0 0 var(--accent)}
.cell{width:34px;height:28px;border-radius:6px;border:1px solid transparent;cursor:pointer;font-weight:700;font-size:13px;position:relative;color:#fff}
.cell.pass{background:var(--good)}.cell.visible{background:var(--warn);color:#0b0b0b}.cell.silent{background:var(--crit)}
.cell[aria-pressed=true]{outline:3px solid var(--ink);outline-offset:1px}
.cell .dot{position:absolute;top:-4px;right:-4px;width:11px;height:11px;border-radius:50%;background:var(--ink);border:2px solid var(--surface)}
.cell .g{position:absolute;bottom:-4px;right:-4px;font-size:9px;line-height:11px;width:13px;height:13px;border-radius:3px;background:var(--gateink);color:#fff;border:1px solid var(--surface)}
.key{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:13px;color:var(--ink2);margin:8px 0}.key span{display:inline-flex;align-items:center;gap:6px}
.sw{display:inline-flex;align-items:center;justify-content:center;width:22px;height:18px;border-radius:5px;font-size:11px;font-weight:700;color:#fff}
.tag{display:inline-block;background:var(--chip);border-radius:999px;padding:1px 8px;font-size:12px;color:var(--ink2);margin:0 4px 4px 0;white-space:nowrap}
.tag.bad{background:transparent;border:1px solid var(--crit);color:var(--ink)}.tag.gate{background:var(--gate);color:var(--gateink)}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:14px}@media (max-width:860px){.cols{grid-template-columns:1fr}}
.msg{font-size:16px;margin:4px 0 8px}.convo{font-size:13px;color:var(--ink2);border-left:2px solid var(--line2);padding-left:10px;margin:6px 0}
.step{border:1px solid var(--line);border-radius:8px;padding:8px 10px;margin:8px 0;background:var(--surface)}
.step.gate{border-color:var(--gateink);background:var(--gate)}
.who{font-size:11px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:var(--ink3)}.step.gate .who{color:var(--gateink)}
.code{font-family:var(--mono);font-size:12.5px;white-space:pre-wrap;word-break:break-word;margin:4px 0}
.reply{white-space:pre-wrap;word-break:break-word;font-size:14px;background:var(--bg);border-radius:8px;padding:10px;margin:6px 0}
.reply.withheld{text-decoration:line-through;text-decoration-color:var(--crit);color:var(--ink2)}
.kv{display:grid;grid-template-columns:auto 1fr;gap:2px 12px;font-size:13px}.kv dt{color:var(--ink3)}.kv dd{margin:0;font-variant-numeric:tabular-nums}
.verdict{font-weight:700}.verdict.pass{color:var(--good)}.verdict.silent{color:var(--crit)}
details{margin:6px 0}summary{cursor:pointer;color:var(--ink2);font-size:13px}
footer{margin-top:36px;font-size:13px;color:var(--ink2)}
.vh{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
"""

JS = r"""
const D = JSON.parse(document.getElementById('data').textContent);
const $ = id => document.getElementById(id);
const el = (tag, attrs, ...kids) => { const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) { if (v === null || v === undefined || v === false) continue;
    if (k === 'class') n.className = v; else if (k === 'text') n.textContent = v; else if (k.startsWith('on')) n.addEventListener(k.slice(2), v); else n.setAttribute(k, v); }
  for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false) n.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  return n; };
const ARM = Object.fromEntries(D.arms.map(a => [a.id, a]));
const STATE = {pass: ['✓', 'Passed the outcome check'], visible: ['!', 'Failed visibly (clarified, abstained or hit a limit)'], silent: ['✕', 'Failed silently (replied, and the reply is wrong or unsupported)']};
const FLAG = {dropped_action: 'action request dropped', one_sided_causal_claim: 'cause claimed on one-sided evidence', claims_side_effect: 'claims a side effect happened',
  false_clarify: 'asked instead of answering', ungrounded_values: 'values in no receipt', unrequested_write_attempt: 'unrequested write attempt (held by host)'};
const FILTERS = [['all', 'All tasks', () => true], ['gate', 'Gate changed the outcome', t => D.pairs.some(([a, b]) => t.cells[a] && t.cells[b] && t.cells[a].state !== t.cells[b].state)],
  ['serious', 'Any serious failure', t => Object.values(t.cells).some(c => c.serious)], ['dropped', 'Dropped action', t => Object.values(t.cells).some(c => c.flags.includes('dropped_action'))],
  ['silent', 'Any silent failure', t => Object.values(t.cells).some(c => c.state === 'silent')], ['split', 'Arms disagree', t => new Set(Object.values(t.cells).map(c => c.state === 'pass')).size > 1]];
let S = {set: D.sets.locked ? 'locked' : 'dev', cat: 'all', filter: 'all', task: null, arm: null, other: null};

function readHash() { const p = location.hash.slice(1).split('/'); if (D.sets[p[0]]) { S.set = p[0]; const t = D.sets[S.set].tasks.find(x => x.id === p[1]);
  if (t) { S.task = t.id; if (t.cells[p[2]]) S.arm = p[2]; if (t.cells[p[3]]) S.other = p[3]; } } }
function writeHash() { history.replaceState(null, '', '#' + [S.set, S.task, S.arm, S.other].filter(Boolean).join('/')); }
const fmtArgs = a => Object.entries(a || {}).map(([k, v]) => k + '=' + (String(v).length > 60 ? String(v).slice(0, 57) + '…' : v)).join(', ');
const secs = ms => (ms / 1000).toFixed(ms < 1000 ? 2 : 1) + ' s';

function renderSummary() { const set = D.sets[S.set], box = $('summary'); box.replaceChildren();
  const maxS = Math.max(...set.arms.map(a => set.summary[a].s)), n = set.summary[set.arms[0]].n;
  const tb = el('tbody');
  for (const a of set.arms) { const s = set.summary[a];
    tb.append(el('tr', {}, el('td', {}, el('strong', {text: ARM[a].short}), el('div', {class: 'small muted', text: ARM[a].label})),
      el('td', {class: 'num'}, el('span', {class: 'track', 'aria-hidden': 'true'}, el('span', {class: 'fill', style: 'width:' + (100 * s.ok / n) + '%'})), s.ok + '/' + s.n),
      el('td', {class: 'num', text: s.silent}), el('td', {class: 'num', text: s.serious}),
      el('td', {class: 'num'}, el('span', {class: 'track', 'aria-hidden': 'true'}, el('span', {class: 'fill', style: 'width:' + (100 * s.s / maxS) + '%'})), s.s.toFixed(2) + ' s'),
      el('td', {class: 'num', text: Math.round(s.tok)}), el('td', {class: 'num', text: s.tools.toFixed(2)}))); }
  box.append(el('table', {}, el('thead', {}, el('tr', {}, el('th', {text: 'Controller'}), el('th', {class: 'num', text: 'Passed'}), el('th', {class: 'num', text: 'Silent failures'}),
    el('th', {class: 'num', text: 'Serious failures'}), el('th', {class: 'num', text: 'Compute per task'}), el('th', {class: 'num', text: 'Model tokens computed per task'}),
    el('th', {class: 'num', text: 'Tool calls per task'}))), tb));
  const p = set.provenance;
  $('prov').textContent = 'Recorded ' + p.recorded + ' on ' + p.cpu + ', repository HEAD ' + p.commit + ' (frozen files unchanged since the freeze), heavy model ' + p.heavy + '. Replayed here from the recorded traces; nothing runs in your browser.'; }

function visibleTasks() { const set = D.sets[S.set], f = FILTERS.find(x => x[0] === S.filter)[2];
  return set.tasks.filter(t => (S.cat === 'all' || t.cat === S.cat) && f(t)); }

function renderControls() { const sets = $('sets'); sets.replaceChildren();
  for (const [k, label] of [['locked', 'Locked set (evidence)'], ['dev', 'Development set']]) if (D.sets[k])
    sets.append(el('button', {'aria-pressed': S.set === k, text: label, onclick: () => { S.set = k; S.task = null; S.cat = 'all'; draw(); }}));
  const cats = $('cats'); cats.replaceChildren();
  const all = ['all', ...new Set(D.sets[S.set].tasks.map(t => t.cat))];
  for (const c of all) cats.append(el('button', {class: 'chipb', 'aria-pressed': S.cat === c, text: c === 'all' ? 'All families' : c.replace('_', ' '), onclick: () => { S.cat = c; draw(); }}));
  const fl = $('filters'); fl.replaceChildren();
  for (const [k, label] of FILTERS) fl.append(el('button', {class: 'chipb', 'aria-pressed': S.filter === k, text: label, onclick: () => { S.filter = k; draw(); }})); }

function renderMatrix() { const set = D.sets[S.set], tasks = visibleTasks(), box = $('matrix'); box.replaceChildren();
  $('count').textContent = tasks.length + ' of ' + set.tasks.length + ' tasks shown';
  const head = el('tr', {}, el('th', {text: 'Task'}), el('th', {text: 'Request'}), set.arms.map(a => el('th', {class: 'arm', scope: 'col', text: ARM[a].short})));
  const tb = el('tbody');
  for (const t of tasks) { const tr = el('tr', {class: t.id === S.task ? 'sel' : ''}, el('td', {}, el('strong', {text: t.id}), el('div', {class: 'small muted', text: t.cat.replace('_', ' ')})),
      el('td', {class: 'q'}, t.msg.length > 150 ? t.msg.slice(0, 147) + '…' : t.msg, el('div', {class: 'small muted', text: 'world: ' + t.world})));
    for (const a of set.arms) { const c = t.cells[a], st = STATE[c.state];
      const label = t.id + ', ' + ARM[a].short + ': ' + st[1] + (c.serious ? '; serious failure' : '') + (c.cost.gate ? '; gate intervened ' + c.cost.gate + ' time(s)' : '');
      tr.append(el('td', {class: 'c'}, el('button', {class: 'cell ' + c.state, 'aria-label': label, title: label, 'aria-pressed': S.task === t.id && S.arm === a,
        onclick: () => { S.task = t.id; S.arm = a; const pair = D.pairs.find(p => p.includes(a)); S.other = pair ? pair.find(x => x !== a) : (a === 'contract' ? 'heavy_agent' : 'contract'); draw(); $('detail').scrollIntoView({behavior: 'smooth', block: 'start'}); }},
        st[0], c.serious ? el('span', {class: 'dot', 'aria-hidden': 'true'}) : null, c.cost.gate ? el('span', {class: 'g', 'aria-hidden': 'true', text: 'G'}) : null))); }
    tb.append(tr); }
  box.append(el('table', {}, el('thead', {}, head), tb)); }

function obsNode(o) { if (!o) return null; const ok = o.s === 'ok';
  return el('div', {}, el('span', {class: 'tag' + (ok ? '' : ' bad'), text: 'host: ' + o.s.replace('_', ' ')}), o.f ? el('div', {class: 'code', text: o.f}) : (o.r ? el('div', {class: 'small', text: o.r}) : null)); }
function actor(by) { if (!by) return ['Host', false]; if (by.startsWith('exit-gate')) return ['Exit gate · host rule, no model', true]; if (by === 'contract-planner') return ['Contract planner · host rule, no model', false];
  if (by === 'heavy-agent') return ['Heavy model · generated tool call', false]; if (by.startsWith('turnwise-dm')) return ['Learned decision head', false]; if (by.startsWith('rules')) return ['v0.6 rules', false]; return [by, false]; }

function stepNodes(s) { const out = [];
  if (s.g) { out.push(el('div', {class: 'step'}, el('div', {class: 'who', text: (s.g.tier === 'heavy' ? 'Heavy' : 'Light') + ' model · generation'}),
      el('div', {class: 'small muted', text: s.g.pt + ' new prompt tokens' + (s.g.cached ? ' + ' + s.g.cached + ' cache-reused' : '') + ', ' + s.g.ct + ' generated, ' + secs(s.g.ms)}),
      s.ctx ? el('div', {class: 'small muted', text: 'prompt blocks: ' + s.ctx.map(b => b[0] + ' (' + b[1] + ')').join(', ')}) : null,
      (s.calls && s.calls.length && !(s.gate && s.gate.action !== 'allow')) ? el('div', {class: 'small', text: 'The model wrote ' + s.calls.length + ' tool call' + (s.calls.length > 1 ? 's' : '') + ' (shown below).'})
        : el('div', {class: 'reply' + (s.g.withheld || (s.gate && s.gate.action !== 'allow') ? ' withheld' : ''), text: s.g.text || '(empty)'}),
      s.g.withheld ? el('div', {class: 'small', text: 'Withheld by the exit gate: ' + s.g.viol.join('; ')}) : null)); }
  if (s.d && !(s.g && s.d.op === 'answer') && !(s.g && s.d.op === 'call_model' && !s.d.gate)) { const [who, isGate] = actor(s.d.by);
    const what = s.d.op === 'call_model' ? 'call the ' + s.d.tier + ' model' : (s.d.t ? s.d.t + '(' + fmtArgs(s.d.a) + ')' : s.d.op);
    out.unshift(el('div', {class: 'step' + (isGate ? ' gate' : '')}, el('div', {class: 'who', text: who}), el('div', {class: 'code', text: what}),
      el('div', {class: 'small muted', text: [s.d.top !== null ? 'top score ' + s.d.top : null, s.d.tok ? s.d.tok + ' tokens scored' : 'no model tokens', s.d.ms !== null ? secs(s.d.ms) : null, s.d.esc ? 'escalated: below confidence gate' : null].filter(Boolean).join(' · ')}),
      s.d.why ? el('div', {class: 'small', text: s.d.why}) : null,
      s.d.gate && s.d.gate.answer !== 'allow' && !isGate ? el('div', {class: 'small', text: 'Exit gate: ' + s.d.gate.note}) : null, obsNode(s.o))); }
  else if (s.d && s.g && s.d.op === 'call_model') { const [who] = actor(s.d.by);
    out.unshift(el('div', {class: 'step'}, el('div', {class: 'who', text: who}), el('div', {class: 'code', text: 'call the ' + s.d.tier + ' model'}),
      el('div', {class: 'small muted', text: [s.d.top !== null ? 'top score ' + s.d.top : null, s.d.tok ? s.d.tok + ' tokens scored' : 'no model tokens', s.d.esc ? 'escalated: below confidence gate' : null].filter(Boolean).join(' · ')}),
      s.d.why ? el('div', {class: 'small', text: s.d.why}) : null)); }
  if (s.gate && s.gate.action !== 'allow') out.push(el('div', {class: 'step gate'}, el('div', {class: 'who', text: 'Exit gate · reply not sent (' + s.gate.action + ')'}),
      el('div', {class: 'small', text: s.gate.reason + (s.gate.missing.length ? ' · missing: ' + s.gate.missing.join(', ') : '') + (s.gate.source === 'answer' ? ' · contract derived from the reply itself' : '')})));
  for (const c of s.calls || []) { const [who, isGate] = actor(c.by);
    out.push(el('div', {class: 'step' + (isGate ? ' gate' : '')}, el('div', {class: 'who', text: who}), el('div', {class: 'code', text: c.t + '(' + fmtArgs(c.a) + ')'}), obsNode(c.o))); }
  if (s.gate && s.gate.viol && s.gate.viol.length) out.push(el('div', {class: 'step gate'}, el('div', {class: 'who', text: 'Exit gate · grounding check failed'}), el('div', {class: 'small', text: s.gate.viol.join('; ')})));
  return out; }

function armPanel(t, a, onChange) { const set = D.sets[S.set], c = t.cells[a], st = STATE[c.state];
  const pick = el('select', {'aria-label': 'Controller shown in this column', onchange: e => onChange(e.target.value)}, set.arms.map(x => el('option', {value: x, selected: x === a, text: ARM[x].short})));
  const k = c.cost;
  return el('section', {class: 'card'}, el('div', {class: 'bar'}, pick, el('span', {class: 'verdict ' + c.state, text: st[0] + ' ' + st[1]})),
    el('div', {}, c.serious ? el('span', {class: 'tag bad', text: '● serious failure'}) : null, c.flags.map(f => el('span', {class: 'tag bad', text: FLAG[f]})),
      c.missing.length ? el('span', {class: 'tag bad', text: 'missing evidence: ' + c.missing.join(', ')}) : null,
      c.via_context.length ? el('span', {class: 'tag', text: 'via prompt retrieval, not a tool receipt: ' + c.via_context.join(', ')}) : null,
      k.gate ? el('span', {class: 'tag gate', text: 'gate intervened ×' + k.gate}) : null),
    c.plan ? el('div', {class: 'step'}, el('div', {class: 'who', text: 'Host · claim typing (lexicon, no model)'}), el('div', {class: 'code', text: 'type: ' + c.plan.type + (c.plan.need.length ? '\ncontract: ' + c.plan.need.join(', ') : '')}),
      el('div', {class: 'small', text: c.plan.route}), c.plan.cues.length ? el('div', {class: 'small muted', text: c.plan.cues.join('; ')}) : null) : null,
    c.steps.flatMap(stepNodes),
    el('h3', {text: 'Final reply · ' + (c.final.by || c.kind)}), el('div', {class: 'reply', text: c.final.text || '(none)'}),
    c.final.withheld ? el('details', {}, el('summary', {text: 'Generated reply the gate withheld'}), el('div', {class: 'reply withheld', text: c.final.withheld})) : null,
    el('h3', {text: 'Measured cost of this turn'}),
    el('dl', {class: 'kv'}, el('dt', {text: 'Wall time'}), el('dd', {text: secs(k.wall)}), el('dt', {text: 'Model calls'}), el('dd', {text: k.heavy + ' heavy, ' + k.light + ' light'}),
      el('dt', {text: 'Controller tokens scored'}), el('dd', {text: k.ctl_tok + ' (' + secs(k.ctl_ms) + ')'}), el('dt', {text: 'Generation tokens computed'}), el('dd', {text: k.gen_new}),
      el('dt', {text: 'Cache-reused tokens'}), el('dd', {text: k.cached}), el('dt', {text: 'Tool calls'}), el('dd', {text: k.tools}))); }

function renderDetail() { const box = $('detail'); box.replaceChildren(); const set = D.sets[S.set];
  const t = set.tasks.find(x => x.id === S.task); if (!t) { box.append(el('p', {class: 'muted', text: 'Select a cell above to open a turn.'})); return; }
  if (!t.cells[S.arm]) S.arm = set.arms[0]; if (!t.cells[S.other]) S.other = set.arms[1] || set.arms[0];
  box.append(...[el('h2', {text: t.id + ' · ' + t.cat.replace('_', ' ')}),
    t.convo.length ? el('div', {class: 'convo'}, t.convo.map(m => el('div', {}, el('strong', {text: m.role + ': '}), m.content))) : null,
    el('p', {class: 'msg'}, el('strong', {text: 'User: '}), t.msg),
    el('details', {}, el('summary', {text: 'Gold label (used only by the scorer; no controller, gate or model ever sees it)'}),
      el('dl', {class: 'kv'}, el('dt', {text: 'Expected outcome'}), el('dd', {text: t.gold.outcome + (t.gold.approval ? ': ' + t.gold.approval : '')}), el('dt', {text: 'Required evidence'}), el('dd', {text: t.gold.facts.join(', ') || 'none'}),
        el('dt', {text: 'Reference answer'}), el('dd', {text: t.gold.ref}), el('dt', {text: 'World variant'}), el('dd', {text: t.world}), el('dt', {text: 'Author note'}), el('dd', {text: t.gold.note}))),
    el('div', {class: 'cols'}, armPanel(t, S.arm, v => { S.arm = v; draw(); }), armPanel(t, S.other, v => { S.other = v; draw(); }))].filter(Boolean)); }

function draw() { renderControls(); renderSummary(); renderMatrix(); renderDetail(); writeHash(); }
readHash(); draw(); addEventListener('hashchange', () => { readHash(); draw(); });
"""


def render() -> str:
    data = json.dumps(page_data(), ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Turnwise Decision Microscope</title>
<meta name="description" content="The same request under eight agent controllers, step by step: who chose each operation, what evidence existed, where the host's exit gate stepped in, and what it cost.">
<style>{CSS}</style>
</head>
<body>
<main>
<header>
<p class="small"><a href="{REPO}">Turnwise</a> · v0.7 exit-gate study · <a href="index.html">v0.6 trace viewer</a> · <a href="v05-explorer.html">v0.5 explorer</a></p>
<h1>Decision Microscope</h1>
<p class="lede">The same request under eight controllers. Open any cell to see who chose each step, what evidence the reply rested on, where the host's exit gate stepped in, and what the turn cost.</p>
<div class="note"><strong>Read this first.</strong> Every cell is a recorded real run on small local models; the &ldquo;heavy&rdquo; model is Qwen3.5-0.8B, not a capable agent. Recorded, then replayed: nothing here is a counterfactual or an estimate. Pass and fail come from a frozen lexical outcome check, which is lenient on generated text.</div>
</header>
<div class="bar"><div class="seg" id="sets" role="group" aria-label="Task set"></div></div>
<section class="card scroll" aria-label="Results by controller"><div id="summary"></div><p class="small muted" id="prov"></p></section>
<h2>Every task under every controller</h2>
<div class="bar" id="cats" role="group" aria-label="Task family"></div>
<div class="bar" id="filters" role="group" aria-label="Filter"></div>
<div class="key" aria-label="Legend">
<span><span class="sw" style="background:var(--good)">✓</span>passed</span>
<span><span class="sw" style="background:var(--warn);color:#0b0b0b">!</span>failed visibly</span>
<span><span class="sw" style="background:var(--crit)">✕</span>failed silently</span>
<span><span class="sw" style="background:var(--ink);border-radius:50%;width:12px;height:12px"></span>serious failure</span>
<span><span class="sw" style="background:var(--gateink);width:16px;height:16px;font-size:10px">G</span>exit gate intervened</span>
<span class="muted" id="count"></span>
</div>
<section class="card scroll" id="matrix" aria-label="Task by controller matrix"></section>
<section id="detail" aria-live="polite"></section>
<footer>
<p>Generated by <code>python -m turnwise_lab.v07.microscope</code> from <code>reports/v07/traces/</code>. Full tables, intervals and every failure: <a href="{REPO}/blob/main/reports/v07/summary.md">reports/v07/summary.md</a>. No network requests, no tracking, synthetic data only.</p>
</footer>
</main>
<script type="application/json" id="data">{data}</script>
<script>{JS}</script>
</body>
</html>
"""


def main() -> None:
    PAGE.write_text(render(), encoding="utf-8")
    print(f"wrote {PAGE.relative_to(ROOT)} ({PAGE.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
