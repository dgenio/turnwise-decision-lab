"""Opt-in one-request public synthetic generation smoke run.

No side effects, no provider access unless all explicit flags and key are set.
Not a provider-native routing comparison.
"""
from __future__ import annotations
import argparse
import json
from .core import Request, Source
from .provider import generate_public_synthetic


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--endpoint',required=True,help='HTTPS .../v1/chat/completions')
    p.add_argument('--model',required=True)
    p.add_argument('--api-key-env',default='OPENAI_API_KEY')
    p.add_argument('--allow-remote',action='store_true',help='Acknowledges real network egress of synthetic request')
    a=p.parse_args()
    req=Request(text='What plausibly caused the synthetic checkout-api incident?',task_summary='Synthetic checkout service degraded after deploy',
                sources=(Source(id='root_cause',summary='checkout root cause deploy timeout mismatch',
                                body='During deployment, configured timeout changed from 8 seconds to 12 seconds.'),))
    result=generate_public_synthetic(req,model=a.model,endpoint=a.endpoint,
                                     api_key_env=a.api_key_env,allow_remote=a.allow_remote)
    print(json.dumps(result.as_json(),indent=2,ensure_ascii=False))

if __name__=='__main__': main()
