"""HONEST offline routing experiment: trained tiny model versus host rules.

Does not measure LLM quality, native-provider performance, live economics,
calibration, or full end-to-end task success. All labels are authored synthetic.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
import argparse
import hashlib
import json
import re
import statistics
import time

from .learning import TinyMultinomialNB

ROOT = Path(__file__).resolve().parents[1]

# Frozen baseline rules. Do not tune against the test file.
RISK = re.compile(r"\b(delete|drop|purge|publish|broadcast|post|refund|transfer|revoke|remove|merge|deploy|cancel|close|update|push|approve|terminate|switch off)\b", re.I)
FLOW = re.compile(r"\b(validate|validation|verify|verification|reconcile|reconciliation|checklist|checks|procedure|pipeline|smoke|standard|approved|reviewed|template)\b", re.I)
TOOL = re.compile(r"\b(fetch|lookup|look up|search|query|read|retrieve|latest|current|status|metrics|monitor|queue|health|logs|track|inspect|find|present|newest|locate)\b", re.I)


def simple_rule(row: dict) -> str:
    if row.get('verified_answer') is not None:
        return 'direct'
    q = row['text']
    if RISK.search(q):
        return 'hold'
    if FLOW.search(q):
        return 'flow'
    if TOOL.search(q):
        return 'tool'
    return 'llm'


def read_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _score(predicted: list[str], rows: list[dict], arm: str, durations: list[float],
           classifier_calls: int, classifier_selected: int) -> dict:
    case_results=[]
    for row,pred in zip(rows,predicted):
        case_results.append({'id':row['id'],'expected':row['label'],'predicted':pred,
                             'correct': pred==row['label'], 'text':row['text']})
    correct=sum(r['correct'] for r in case_results)
    cm={k:dict(Counter(x['predicted'] for x in case_results if x['expected']==k)) for k in sorted({r['label'] for r in rows})}
    sorted_lat=sorted(durations)
    return {'arm':arm,'n':len(rows),'route_matches':correct,'route_accuracy':round(correct/len(rows),4),
            'non_direct_accuracy':round(sum(x['correct'] for x in case_results if x['expected']!='direct') / max(1,sum(x['expected']!='direct' for x in case_results)),4),
            'unsafe_write_route_misses':sum(r['expected']=='hold' and r['predicted']!='hold' for r in case_results),
            'local_policy_latency_ms_p50':round(statistics.median(sorted_lat)*1000,4),
            'local_policy_latency_ms_p95':round(sorted_lat[min(len(sorted_lat)-1,int((len(sorted_lat)-1)*.95))]*1000,4),
            'confusion':cm,'cases':case_results,
            'classifier_calls':classifier_calls,'classifier_selected_routes':classifier_selected,
            'cost_usd':None,'model_input_tokens':None,'e2e_task_success':None}


def run_benchmark(train_path: Path | None=None, test_path: Path | None=None, *, threshold:float=.55) -> dict:
    a=train_path or ROOT/'fixtures/route_train.jsonl'
    b=test_path or ROOT/'fixtures/route_test.jsonl'
    train,test=read_rows(a),read_rows(b)
    if not train or not test:
        raise ValueError('Both splits required')
    if any('label' not in r or 'text' not in r or 'id' not in r for r in train+test):
        raise ValueError('Missing required dataset fields')
    if set(r['id'] for r in train) & set(r['id'] for r in test):
        raise ValueError('Train/test ID overlap')
    if set(r['text'].casefold() for r in train) & set(r['text'].casefold() for r in test):
        raise ValueError('Train/test text overlap')
    if not 0<=threshold<=1:
        raise ValueError('Invalid threshold')
    model=TinyMultinomialNB().fit(train)
    # Fit only on the training split. The held-out file never changes weights.
    results=[]
    predictions={}
    times={}
    for arm in ['strong_simple_rules','tiny_trained_nb','preflight_plus_nb']:
        pred=[]; durations=[]; classifier_calls=0; classifier_selected=0
        for row in test:
            t0=time.perf_counter()
            if arm=='strong_simple_rules':
                route=simple_rule(row)
            elif arm=='tiny_trained_nb':
                classifier_calls += 1
                classifier_selected += 1
                route=model.predict(row['text']).route
            else:
                if row.get('verified_answer') is not None or RISK.search(row['text']):
                    route=simple_rule(row)
                else:
                    classifier_calls += 1
                    n=model.predict(row['text'])
                    if n.score>=threshold:
                        classifier_selected += 1
                        route=n.route
                    else:
                        route=simple_rule(row)
            durations.append(time.perf_counter()-t0)
            pred.append(route)
        results.append(_score(pred,test,arm,durations,classifier_calls,classifier_selected))
        predictions[arm]=pred
        times[arm]=durations
    return {
        'schema_version':'trained-routing-synthetic-v1',
        'question':'Can a tiny fitted classifier improve route-label agreement versus strong host rules on held-out synthetic phrasing?',
        'train':{'count':len(train),'sha256':_sha(a)},
        'test':{'count':len(test),'sha256':_sha(b)},
        'hyperparameters':{'model':'multinomial_naive_bayes','smoothing_alpha':1.0,'confidence_threshold_hybrid':threshold},
        'classifiers_actually_run':['tiny self-trained multinomial NB in stdlib Python'],
        'not_run':['Jev','LiteLLM Auto Router','vLLM Semantic Router','provider native tool search','any generative LLM'],
        'limitations':[
          'Train and test labels were manually authored by the same project author; this is not independently labeled external evaluation.',
          'Different exact text strings do not ensure semantic template independence; all cases are synthetic.',
          'Route-label agreement is not end-to-end success. Local Python timing does not include networking or LLM latency.',
          'The trained scores are not calibrated probabilities. Never use as confidence for consequential actions.',
          'Cost, model tokens and true task success are null, not zero. Missing native baselines prevent comparative product claims.',
          'The no-preflight naive Bayes ablation intentionally ignores host-verified answers. The host-rules and hybrid arms use that metadata; compare those two for fair marginal value.'
        ],
        'arms':results}


def render_markdown(out:dict)->str:
    lines=[
        '# Initial trained routing benchmark — synthetic, not provider-comparative',
        '', 'All reported route labels were authored for this experiment. **No hosted decision model or LLM was called.**',
        f"Training examples: {out['train']['count']}; disjoint test examples: {out['test']['count']}.",
        '', '| Strategy | Matching route labels | Missed hold labels | Classifier calls | Predictions adopted |',
        '|---|---:|---:|---:|---:|'
    ]
    for arm in out['arms']:
        lines.append(f"| `{arm['arm']}` | {arm['route_matches']}/{arm['n']} ({arm['route_accuracy']:.1%}) | {arm['unsafe_write_route_misses']} | {arm['classifier_calls']} | {arm['classifier_selected_routes']} |")
    lines += ['', '> **These are classification matches, not solved tasks or economic savings.** The toy classifier is genuinely fitted on a separate synthetic training split, but is not a Jev or LLM evaluation.',
              '', '## Where each strategy fails', '']
    for arm in out['arms']:
        failures=[c for c in arm['cases'] if not c['correct']]
        lines.append(f"### {arm['arm']} — {len(failures)} misses")
        if not failures:
            lines.append('No classification misses on this hand-authored test set.')
        else:
            for f in failures:
                lines.append(f"- `{f['id']}` — expected `{f['expected']}`, predicted `{f['predicted']}`: “{f['text']}”")
        lines.append('')
    lines += ['## Threats to validity','']+['- '+s for s in out['limitations']]
    lines += ['', '## Reproduce', '', '```bash','python -m turnwise_lab.benchmark --output reports/trained-routing-synthetic.json --markdown reports/trained-routing-synthetic.md','```','',
              'Dataset SHA-256 (train): `'+out['train']['sha256']+'`',
              'Dataset SHA-256 (test): `'+out['test']['sha256']+'`','',
              'Promote neither strategy without real-model and independent multi-turn evaluation.']
    return '\n'.join(lines)+'\n'


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--train',type=Path)
    p.add_argument('--test',type=Path)
    p.add_argument('--threshold',type=float,default=.55)
    p.add_argument('--output',type=Path,default=ROOT/'reports/trained-routing-synthetic.json')
    p.add_argument('--markdown',type=Path,default=ROOT/'reports/trained-routing-synthetic.md')
    args=p.parse_args()
    data=run_benchmark(args.train,args.test,threshold=args.threshold)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(data,indent=2,sort_keys=True,ensure_ascii=False)+'\n',encoding='utf-8')
    args.markdown.parent.mkdir(parents=True,exist_ok=True)
    args.markdown.write_text(render_markdown(data),encoding='utf-8')
    print('Completed', data['test']['count'], 'synthetic test cases; no provider calls')
    for arm in data['arms']:
        print(arm['arm'],arm['route_matches'],'/',arm['n'],'missed holds',arm['unsafe_write_route_misses'])

if __name__=='__main__':
    main()
