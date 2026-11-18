"""Render the local execution receipts to a standalone offline HTML exhibit."""
from __future__ import annotations
from html import escape
from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[1]
from turnwise_lab.live_demo import run_demo


def render(data:dict)->str:
    rows=[]
    for case in data['turns']:
        receipt=case['receipt']; status=receipt['status']; color=('good' if status=='completed' else 'warn' if status=='approval_required' else 'info')
        safe_json=escape(json.dumps(receipt,ensure_ascii=False,indent=2),quote=True)
        rows.append(f'''<details class="turn"><summary><span class="num">{escape(case['turn_id'])}</span><span class="prompt">{escape(case['user_request'])}</span><span class="status {color}">{escape(status.replace('_',' '))}</span></summary><div class="detail"><p class="meta">Route: <b>{escape(case['proposed_route'])}</b> · executed actions: <b>{len(receipt['executed_actions'])}</b> · evidence IDs: <b>{len(receipt['context_ids'])}</b></p><pre>{safe_json}</pre></div></details>''')
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Turnwise — Execution receipts</title><style>
:root{{--bg:#0b101b;--panel:#151e2d;--line:#324057;--text:#f5f7fc;--muted:#b5c4d9;--accent:#7cd1e3}}*{{box-sizing:border-box}}body{{font:16px/1.6 system-ui,-apple-system,Segoe UI,sans-serif;background:var(--bg);color:var(--text);margin:0}}main{{max-width:1020px;margin:auto;padding:48px 22px 80px}}h1{{font-size:clamp(2rem,6vw,3.4rem);line-height:1.1;letter-spacing:-.04em;margin:16px 0}}.kicker{{font-size:.75rem;letter-spacing:.15em;color:var(--accent);font-weight:700;text-transform:uppercase}}p{{color:var(--muted)}}a{{color:var(--accent)}}.lead{{max-width:660px}}.stats{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:30px 0 34px}}.stat{{padding:18px;border:1px solid var(--line);border-radius:13px;background:var(--panel)}}.stat strong{{display:block;font-size:1.8rem}}.stat span{{font-size:.76rem;color:var(--muted)}}details{{background:var(--panel);border:1px solid var(--line);border-radius:12px;margin:10px 0;overflow:hidden}}summary{{display:flex;align-items:center;gap:14px;padding:16px;cursor:pointer;list-style:none}}summary::-webkit-details-marker{{display:none}}summary:hover{{background:#202c40}}.num{{font:700 1rem ui-monospace,monospace;color:var(--accent)}}.prompt{{flex:1;font-weight:600}}.status{{border-radius:99px;border:1px solid;font-size:.75rem;padding:3px 10px;white-space:nowrap}}.good{{color:#84efbc;border-color:#3a8862}}.warn{{color:#ffe3a6;border-color:#ab864b}}.info{{color:#b1c7ff;border-color:#5f78b6}}.detail{{border-top:1px solid var(--line);padding:16px}}.meta{{font-size:.86rem;margin:0 0 10px}}pre{{white-space:pre-wrap;word-break:break-word;font:12px/1.55 ui-monospace,SFMono-Regular,Consolas,monospace;padding:14px;background:#080d15;border:1px solid #273146;border-radius:9px;overflow:auto}}.note{{padding:18px;border-left:3px solid var(--accent);background:var(--panel);margin:28px 0}}.foot{{font-size:.86rem;margin-top:35px}}@media(max-width:640px){{main{{padding-top:24px}}.stats{{grid-template-columns:repeat(2,1fr)}}summary{{flex-wrap:wrap}}.prompt{{flex-basis:80%}}.status{{margin-left:28px}}}}</style></head><body><main><div class="kicker">Turnwise / execution receipts / public synthetic</div><h1>Route the work.<br>Prove what ran.</h1><p class="lead">Six synthetic conversation turns. Three local Python operations finish, two require generation, and one write request stops at the authorization boundary. No remote LLM was called.</p><p><a href="index.html">← Outcome-scored v0.5 experiment</a> · <a href="planning-contract.html">v0.4 planning-only exhibit</a> · <a href="live-local-run.json">Raw JSON</a></p><div class="stats"><div class="stat"><strong>6</strong><span>synthetic turns</span></div><div class="stat"><strong>3</strong><span>locally completed</span></div><div class="stat"><strong>2</strong><span>generation handoffs</span></div><div class="stat"><strong>1</strong><span>approval hold</span></div></div><div class="note"><b>Read this first:</b> real local Python handlers executed. The monitoring data is invented; the incident explanation was <b>not</b> generated. An SHA-256 receipt digest is not a security signature or production audit guarantee.</div><section>{''.join(rows)}</section><p class="foot">Reproduce from a checkout: <code>python -m turnwise_lab.live_demo --output reports/live-local-run.json</code>. The source of truth is the Python runner and generated JSON, not this page.</p></main></body></html>'''

if __name__=='__main__':
    from pathlib import Path
    data=run_demo()
    (ROOT/'demo/live-local-run.json').write_text(json.dumps(data,indent=2,sort_keys=True,ensure_ascii=False)+'\n',encoding='utf-8')
    (ROOT/'demo/local-run.html').write_text(render(data),encoding='utf-8')
    print('Updated demo/local-run.html')
