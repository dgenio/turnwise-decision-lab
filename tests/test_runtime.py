import unittest
from dataclasses import replace

from turnwise_lab.core import Capability, Plan, Request, Source
from turnwise_lab.live_demo import actions, run_demo
from turnwise_lab.runtime import HostIdentity, LocalHarness, RegisteredAction

class LocalExecutionTests(unittest.TestCase):
    def setUp(self):
        self.h = LocalHarness(actions())
        self.reader = HostIdentity(principal='test-reader', permissions=frozenset({'read'}))

    def test_end_to_end_six_turns(self):
        run = run_demo()
        self.assertEqual(len(run['turns']), 6)
        self.assertEqual([x['receipt']['status'] for x in run['turns']],
                         ['completed','completed','completed','generation_required','approval_required','generation_required'])
        self.assertEqual(run['remote_provider_calls'],0)
        self.assertEqual(run['generative_model_calls'],0)
        self.assertEqual(run['turns'][1]['receipt']['answer']['changed_keys'],['timeout_seconds'])
        self.assertEqual(run['turns'][2]['receipt']['answer']['status'],'degraded')
        self.assertEqual(run['turns'][3]['receipt']['context_ids'],['checkout_health','rollback_cause'])

    def test_read_tool_is_executed(self):
        req=Request(text='status',tools=(Capability('fetch_service_health','Status'),))
        out=self.h.run(req,Plan(path='tool',model_tier='standard',capability_id='fetch_service_health'),identity=self.reader)
        self.assertEqual(out.status,'completed')
        self.assertEqual(out.executed_actions,['fetch_service_health'])
        self.assertIn('audit_digest',out.as_json())
        self.assertEqual(len(out.audit_digest),64)

    def test_forged_plan_cannot_invoke_unpresented_action(self):
        req=Request(text='other task')
        out=self.h.run(req,Plan(path='tool',model_tier=None,capability_id='fetch_service_health'),identity=self.reader)
        self.assertEqual(out.status,'blocked')
        self.assertEqual(out.executed_actions,[])

    def test_tool_flow_type_confusion_does_not_execute(self):
        req=Request(text='test',tools=(Capability('validate_deployment_baseline','baseline'),))
        out=self.h.run(req,Plan(path='flow',model_tier=None,capability_id='validate_deployment_baseline'),identity=self.reader)
        self.assertEqual(out.status,'blocked')

    def test_forged_direct_answer_not_used(self):
        out=self.h.run(Request(text='unknown'),Plan(path='direct',model_tier=None,deterministic_answer='FAKE'),identity=self.reader)
        self.assertEqual(out.status,'blocked')
        out=self.h.run(Request(text='known',direct_answer='trusted'),Plan(path='direct',model_tier=None,deterministic_answer='FAKE'),identity=self.reader)
        self.assertEqual(out.answer,'trusted')

    def test_unapproved_write_is_blocked_despite_forged_plan(self):
        req=Request(text='publish',flows=(Capability('publish_incident_report','publish',side_effect=True),))
        out=self.h.run(req,Plan(path='flow',model_tier=None,capability_id='publish_incident_report',approval_required=False),identity=self.reader)
        self.assertEqual(out.status,'blocked')
        self.assertEqual(out.executed_actions,[])

    def test_permission_and_grant_are_separate_from_plan(self):
        req=Request(text='publish',flows=(Capability('publish_incident_report','publish',side_effect=True),),approved_actions=frozenset({'publish_incident_report'}))
        auth=HostIdentity(principal='x',permissions=frozenset({'read','publish'}),granted_write_actions=frozenset({'publish_incident_report'}))
        out=self.h.run(req,Plan(path='flow',model_tier=None,capability_id='publish_incident_report'),identity=auth)
        self.assertEqual(out.status,'approval_required') # default write policy is OFF

    def test_host_metadata_mismatch_blocks(self):
        req=Request(text='publish',flows=(Capability('publish_incident_report','publish',side_effect=False),))
        out=self.h.run(req,Plan(path='flow',model_tier=None,capability_id='publish_incident_report'),identity=self.reader)
        self.assertEqual(out.status,'blocked')
        self.assertIn('capability_side_effect_metadata_mismatch',out.reason_codes)

    def test_an_exception_fails_closed(self):
        h=LocalHarness({'bad':RegisteredAction('bad','bad',lambda _:1/0)})
        req=Request(text='bad',tools=(Capability('bad','bad'),))
        out=h.run(req,Plan(path='tool',model_tier='standard',capability_id='bad'),identity=self.reader)
        self.assertEqual(out.status,'error')
        self.assertIsNone(out.answer)
        self.assertEqual(out.executed_actions,[])

    def test_generation_needed_is_not_counted_as_success(self):
        req=Request(text='Explain root cause incident',sources=(Source('root_cause','root cause incident','root cause text'),))
        out=self.h.run(req,Plan(path='llm',model_tier='deep'),identity=self.reader)
        self.assertEqual(out.status,'generation_required')
        self.assertIsNone(out.answer)
        self.assertEqual(out.context_ids,['root_cause'])

    def test_results_are_deterministic(self):
        self.assertEqual(run_demo(),run_demo())



class PlanContextHandoffTests(unittest.TestCase):
    """Regression: the harness used to discard the plan's context selection."""

    def setUp(self):
        self.h = LocalHarness(actions())
        self.reader = HostIdentity(principal='test-reader', permissions=frozenset({'read'}))
        self.req = Request(text='Explain the incident', sources=(
            Source('a', 'incident root cause', 'A' * 50), Source('b', 'unrelated note', 'B' * 40)))

    def test_plan_context_ids_reach_the_receipt(self):
        out = self.h.run(self.req, Plan(path='llm', model_tier='deep', context_ids=['b']), identity=self.reader)
        self.assertEqual(out.context_ids, ['b'])
        self.assertIn('plan_context_selection_used', out.reason_codes)

    def test_forged_or_duplicate_context_ids_are_dropped(self):
        out = self.h.run(self.req, Plan(path='llm', model_tier='deep', context_ids=['zzz', 'a', 'a']),
                         identity=self.reader)
        self.assertEqual(out.context_ids, ['a'])

    def test_plan_context_respects_host_budget(self):
        req = replace(self.req, context_budget_chars=80)
        out = self.h.run(req, Plan(path='llm', model_tier='deep', context_ids=['a', 'b']), identity=self.reader)
        self.assertEqual(out.context_ids, ['a'])

    def test_without_plan_context_falls_back_to_host_selection(self):
        out = self.h.run(self.req, Plan(path='llm', model_tier='deep'), identity=self.reader)
        self.assertEqual(out.context_ids, ['a'])
        self.assertNotIn('plan_context_selection_used', out.reason_codes)


if __name__=='__main__':unittest.main()
