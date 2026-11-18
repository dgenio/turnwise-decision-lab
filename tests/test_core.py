import json
import unittest
from pathlib import Path
from turnwise_lab import Capability, FixtureDecider, Judgment, JevDecider, Planner, Request, Source
from turnwise_lab.__main__ import request_from_record
from turnwise_lab.core import pack_sources, state_preview

ROWS = json.loads((Path(__file__).parent.parent / 'fixtures' / 'scenarios.json').read_text())
MOCK = {r['text']: r['mock_judgment'] for r in ROWS}

class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.p = Planner(FixtureDecider(MOCK))

    def test_fixture_contract_cases(self):
        for row in ROWS:
            with self.subTest(row=row['id']):
                p = self.p.plan(request_from_record(row))
                actual = 'llm_deep' if p.path == 'llm' and p.model_tier == 'deep' else p.path
                self.assertEqual(row['expected_label'], actual)
                self.assertEqual(p.decision_model_called, row.get("direct_answer") is None)

    def test_write_not_executed_on_model_advice(self):
        p = self.p.plan(request_from_record(ROWS[4]))
        self.assertTrue(p.approval_required)
        self.assertEqual(p.path, 'hold')
        self.assertEqual(p.capability_id, 'create_customer_incident_ticket')

    def test_approval_explicit_allows_planning_not_execution(self):
        original = request_from_record(ROWS[4])
        request = Request(text=original.text, tools=original.tools, approved_actions=frozenset(['create_customer_incident_ticket']))
        p = self.p.plan(request)
        self.assertEqual(p.path, 'tool')
        self.assertFalse(p.approval_required)

    def test_verified_local_answer_bypasses_even_external_nonpublic(self):
        class ExplodingExternal:
            external = True
            def decide(self, state):
                raise AssertionError('verified host answer must bypass external provider')
        plan = Planner(ExplodingExternal()).plan(Request(
            text='Sensitive local request', sensitivity='restricted',
            direct_answer='Trusted local response.'))
        self.assertEqual(plan.path, 'direct')
        self.assertFalse(plan.decision_model_called)

    def test_bypass_can_be_disabled_for_ablation(self):
        plan = Planner(FixtureDecider(MOCK), verified_direct_bypass=False).plan(request_from_record(ROWS[0]))
        self.assertTrue(plan.decision_model_called)
        self.assertEqual(plan.path, 'direct')

    def test_external_nonpublic_request_blocked_before_decider(self):
        class ExplodingExternal:
            external = True
            def decide(self, state):
                raise AssertionError('external call must never occur')
        p = Planner(ExplodingExternal()).plan(Request(text='Internal customer information', sensitivity='internal'))
        self.assertEqual(p.path, 'hold')
        self.assertFalse(p.decision_model_called)

    def test_external_summaries_do_not_include_sensitive_sources(self):
        request = Request(text='incident log', sources=(
            Source(id='sensitive', summary='incident log private', body='SECRET', sensitivity='restricted'),
            Source(id='public', summary='incident log public', body='safe', sensitivity='public')))
        preview = state_preview(request, external=True)
        self.assertNotIn('SECRET', str(preview))
        self.assertNotIn('sensitive', str(preview))
        self.assertEqual([x['text'] for x in pack_sources(request,'extended',external=True)], ['safe'])

    def test_nobody_sends_raw_source_bodies_to_decider(self):
        req = Request(text='incident log', sources=(Source(id='log',summary='incident log',body='PRIVATE RAW CONTENT'),))
        self.assertNotIn('PRIVATE RAW CONTENT', str(state_preview(req, False)))

    def test_context_is_relevance_ranked_budgeted_and_order_stable(self):
        req = Request(text='customer incident', sources=(
            Source(id='ignored',summary='recipe',body='abc'),
            Source(id='incident',summary='customer incident runbook',body='A'*120),
            Source(id='customer',summary='customer incident history',body='B'*180)), context_budget_chars=240)
        a = pack_sources(req, 'extended', external=False)
        b = pack_sources(req, 'extended', external=False)
        self.assertEqual(a, b)
        self.assertLessEqual(sum(len(x['text']) for x in a), 240)
        self.assertFalse(any(x['id']=='ignored' for x in a))

    def test_no_schema_hallucinations(self):
        class Bad:
            external=False
            def decide(self, state): return Judgment(route='sudo', route_probability=0.99, tier='small', tier_probability=1)
        p = Planner(Bad()).plan(Request(text='Anything'))
        self.assertEqual(p.path, 'llm')
        self.assertEqual(p.model_tier, 'deep')
        self.assertIn('classifier_unavailable_or_invalid', p.reasons)

    def test_provider_error_fallback_no_tool(self):
        p = self.p.plan(Request(text='unknown prompt', tools=(Capability(id='delete_records',description='delete records',side_effect=True),)))
        self.assertEqual(p.path, 'llm')
        self.assertIsNone(p.capability_id)

    def test_context_not_selected_for_hold(self):
        row=ROWS[4].copy()
        row['sources']=[{'id':'incident','summary':'customer incident ticket','body':'not for action'}]
        p = self.p.plan(request_from_record(row))
        self.assertEqual(p.context_pack, [])

    def test_context_budget_out_of_range(self):
        p=self.p.plan(Request(text='Say hello',context_budget_chars=100000))
        self.assertEqual(p.path,'hold')

    def test_flow_not_available_never_invent(self):
        row=ROWS[1].copy();row.pop('flows')
        p=self.p.plan(request_from_record(row))
        self.assertEqual(p.path,'llm')
        self.assertIsNone(p.capability_id)

    def test_direct_has_no_generation_model_or_classifier(self):
        p = self.p.plan(request_from_record(ROWS[0]))
        self.assertIsNone(p.model_tier)
        self.assertFalse(p.decision_model_called)
        self.assertEqual(p.deterministic_answer, 'Hello.')

    def test_direct_must_have_verifiable_host_answer(self):
        p = self.p.plan(Request(text='Say hello'))
        self.assertEqual(p.path, 'llm')
        self.assertIn('no_verified_deterministic_answer', p.reasons)

    def test_external_requires_explicit_permission(self):
        class External:
            external=True
            def decide(self, state): raise AssertionError('should not be called')
        p=Planner(External()).plan(Request(text='public thing'))
        self.assertEqual(p.path,'hold')
        self.assertIn('external_decider_requires_explicit_opt_in',p.reasons)

    def test_obvious_pii_or_token_prevents_external_call(self):
        class External:
            external=True
            def decide(self, state): raise AssertionError('must reject before call')
        for txt in ['Contact jane@example.com', 'api_key=supersecretvalue']:
            with self.subTest(txt=txt):
                p=Planner(External()).plan(Request(text=txt,allow_external_decider=True))
                self.assertEqual(p.path,'hold')
                self.assertIn('obvious_private_data_in_external_request',p.reasons)

if __name__=='__main__': unittest.main()

class JevAdapterContractTests(unittest.TestCase):
    def test_adapter_uses_three_typed_questions_and_probabilities(self):
        import sys
        from types import SimpleNamespace, ModuleType
        from unittest.mock import patch

        stub = ModuleType('typesafe_sdk')
        calls = []
        class Choice:
            def __init__(self, **kw):
                self.details = kw
        class Client:
            def __enter__(self): return self
            def __exit__(self, *args): return None
            def system_one(self, **kwargs):
                calls.append(kwargs)
                return SimpleNamespace(choices={
                    'path': SimpleNamespace(choice='tool', probabilities={'tool':.85}),
                    'tier': SimpleNamespace(choice='standard', probabilities={'standard':.9}),
                    'context': SimpleNamespace(choice='related', probabilities={'related':.8}),
                })
        stub.Choice = Choice
        stub.TypeSafeClient = Client
        with patch.dict(sys.modules, {'typesafe_sdk': stub}):
            d = JevDecider().decide({'new_turn':'Test'})
        self.assertEqual(len(calls),1)
        self.assertEqual(set(calls[0]['questions']),{'path','tier','context'})
        self.assertAlmostEqual(d.route_probability,.85)
        self.assertEqual(d.tier,'standard')
        self.assertEqual(d.context_mode,'related')
