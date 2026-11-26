"""#55 prospective developer regressions; NOT independent evaluation evidence.

All tests are stdlib, synthetic and offline. Frozen v0.5/v0.6/v0.7
datasets, traces, metrics, and scoring are neither read nor rewritten.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from examples.architecture.action_context_demo import (
    LIGHT_TASK, OfflineModelPort, QueryExtractionPolicy, run_case,
)
from examples.architecture.context_modules import (
    MANIFEST_PATH, ModuleSelectionError, load_manifest, select_modules,
)
from examples.architecture.incident_env import IncidentHost, TASKS
from examples.architecture.policies import TriagePolicy
from examples.architecture.scoped_runtime import ScopedContextRuntime
from examples.architecture.turnwise_core import Decision, ModelOutcome, Op, TurnwiseRuntime


def write_manifest(tmp, data):
    path = Path(tmp) / "manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class ManifestContractTests(unittest.TestCase):
    def test_manifest_is_versioned_and_has_provenance(self):
        registry = load_manifest()
        self.assertEqual(registry.version, "turnwise.action-modules.v2")
        self.assertEqual(len(registry.sha256), 64)
        self.assertEqual(len(registry.blocks), len({b.id for b in registry.blocks}))
        self.assertTrue(all(b.source.strip() for b in registry.blocks))

    def test_mandatory_blocks_come_first_then_the_requested_one_and_absences_are_recorded(self):
        s = select_modules("CALL_LIGHT", requested=("extract-arguments",))
        self.assertEqual([b.id for b in s.included],
                         ["host-authority", "receipt-grounding", "extract-arguments"])
        audit = s.audit()
        self.assertEqual(audit["excluded"], [{"id": "summarize-evidence", "reason": "not_requested"},
                                             {"id": "investigate-cause", "reason": "different_operation"}])
        self.assertEqual(audit["module_bytes"], sum(len(b.text.encode("utf-8")) for b in s.included))
        self.assertIn("NOT provider tokens", audit["units"])

    def test_several_requested_blocks_keep_request_order_and_appear_once(self):
        s = select_modules("CALL_LIGHT", requested=("summarize-evidence", "extract-arguments",
                                                    "summarize-evidence", "receipt-grounding"))
        self.assertEqual([b.id for b in s.included], ["host-authority", "receipt-grounding",
                                                      "summarize-evidence", "extract-arguments"])

    def test_any_overflow_fails_closed_and_nothing_is_dropped_silently(self):
        mandatory = sum(len(b.text.encode("utf-8")) for b in select_modules("CALL_LIGHT").included)
        with self.assertRaisesRegex(ModuleSelectionError, "module selection overflow"):
            select_modules("CALL_LIGHT", module_byte_limit=1)  # the mandatory blocks alone do not fit
        with self.assertRaisesRegex(ModuleSelectionError, "module selection overflow"):
            select_modules("CALL_LIGHT", requested=("extract-arguments",), module_byte_limit=mandatory)
        self.assertEqual(len(select_modules("CALL_LIGHT", module_byte_limit=mandatory).included), 2)

    def test_invalid_requests_rejected(self):
        for op, requested in (
            ("CALL_HEAVY", ("summarize-evidence",)),
            ("CALL_LIGHT", ("made-up-instructions",)),
            ("CALL_LIGHT", (["extract-arguments"],)),
            ("CALL_TOOL", ()),
        ):
            with self.subTest(op=op, requested=requested), self.assertRaises(ModuleSelectionError):
                select_modules(op, requested=requested)
        for limit in (0, -1, 1.5, True):
            with self.subTest(limit=limit), self.assertRaises(ModuleSelectionError):
                select_modules("CALL_LIGHT", module_byte_limit=limit)

    def test_malformed_or_unsupported_manifests_fail_closed(self):
        base = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

        def variant(change):
            data = json.loads(json.dumps(base))
            change(data)
            return data

        cases = {
            "v1 version": variant(lambda d: d.update(version="turnwise.action-modules.v1")),
            "unimplemented field": variant(lambda d: d["blocks"][2].update(depends_on=["receipt-grounding"])),
            "missing field": variant(lambda d: d["blocks"][0].pop("source")),
            "non-string id": variant(lambda d: d["blocks"][0].update(id=["host-authority"])),
            "duplicate id": variant(lambda d: d["blocks"][1].update(id="host-authority")),
            "string applies_to": variant(lambda d: d["blocks"][0].update(applies_to="CALL_HEAVY")),
            "non-model operation": variant(lambda d: d["blocks"][0].update(applies_to=["CALL_TOOL"])),
            "unhashable operation": variant(lambda d: d["blocks"][0].update(applies_to=[["CALL_HEAVY"]])),
            "non-bool mandatory": variant(lambda d: d["blocks"][0].update(mandatory=1)),
            "empty text": variant(lambda d: d["blocks"][0].update(text="  ")),
            "no blocks": variant(lambda d: d.update(blocks=[])),
        }
        for name, data in cases.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp, \
                    self.assertRaises(ModuleSelectionError):
                load_manifest(write_manifest(tmp, data))
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ModuleSelectionError):
            load_manifest(Path(tmp) / "absent.json")
        with tempfile.TemporaryDirectory() as tmp:  # the unchanged base loads, so the cases above are not vacuous
            self.assertEqual(load_manifest(write_manifest(tmp, base)).version, "turnwise.action-modules.v2")


class OptInRuntimeTests(unittest.TestCase):
    def test_default_core_packet_is_unchanged(self):
        port = OfflineModelPort()
        runtime = TurnwiseRuntime(IncidentHost(TASKS["investigate"]), TriagePolicy(), port)
        result = runtime.run()
        self.assertEqual(result.status, "finished")
        self.assertNotIn("instruction_modules", port.packets[0][1])

    def test_zero_model_direct_route(self):
        result, runtime, port = run_case("direct", TASKS["severity"], TriagePolicy())
        self.assertEqual(result.status, "answered_directly")
        self.assertEqual(port.packets, [])
        self.assertEqual(runtime.module_audits, [])

    def test_light_extraction_is_typed_and_read_only(self):
        result, runtime, port = run_case("extract", LIGHT_TASK, QueryExtractionPolicy())
        self.assertEqual(result.status, "finished")
        self.assertEqual([r.tool for r in runtime.host.receipts], ["search_docs"])
        self.assertEqual([r.status for r in runtime.host.receipts], ["executed"])
        self.assertEqual(runtime.host.receipts[0].arguments, {"query": "checkout error rate runbook"})
        self.assertEqual(len(port.packets), 2)
        self.assertEqual([[m["id"] for m in packet["instruction_modules"]] for _, packet in port.packets],
                         [["host-authority", "receipt-grounding", "extract-arguments"],
                          ["host-authority", "receipt-grounding", "summarize-evidence"]])
        self.assertEqual(runtime.module_audits[0]["evidence_included"], [])
        self.assertEqual(runtime.module_audits[0]["tools_visible_for_proposal"], ["search_docs"])
        self.assertEqual(runtime.module_audits[1]["evidence_included"], ["r1"])
        self.assertEqual(result.writes_executed, 0)

    def test_model_cannot_resolve_a_service_referent_the_user_did_not_name(self):
        """Integration with the host FINISH gate: a model-mapped alias is not user authority."""
        class AliasPort(OfflineModelPort):
            def call(self, tier, packet):
                self.packets.append((tier, packet))
                if packet.get("evidence"):
                    receipt = packet["evidence"][0]
                    return {"kind": "answer_candidate", "text": "It is degraded.", "tool": None,
                            "arguments_json": None, "cited_receipts": [receipt["receipt"]]}
                return {"kind": "tool_proposal", "text": "check-out means checkout.",
                        "tool": "service_health", "arguments_json": '{"service":"checkout"}',
                        "cited_receipts": []}

        port = AliasPort()
        rt = ScopedContextRuntime(IncidentHost("Is check-out healthy right now?"), QueryExtractionPolicy(), port)
        result = rt.run()
        self.assertEqual(result.status, "needs_clarification")
        self.assertEqual(rt.host.receipts, [])
        self.assertEqual(result.writes_executed, 0)

    def test_host_refuses_finish_when_only_a_model_resolved_the_service(self):
        host = IncidentHost("Is check-out healthy right now?")
        receipt = host.execute("service_health", {"service": "checkout"}, proposed_by="turnwise_policy")
        self.assertTrue(receipt.executed)  # a schema-valid read may run...
        rt = ScopedContextRuntime(host, QueryExtractionPolicy(), OfflineModelPort())
        rt.outcomes.append(ModelOutcome("m1", "light_model", "answer_candidate", "It is degraded.",
                                        cited=("r1",), shown=("r1",)))
        ok, why = rt.host_validates(Decision(Op.FINISH, "accept", candidate="m1"), 2)
        self.assertFalse(ok)  # ...but it cannot stand in for a referent the user named
        self.assertIn("unresolved service target", why)

    def test_the_validated_selection_is_the_one_sent_even_if_the_selector_changes(self):
        """Ported from session 01DBLHMGQbB1XHvfyByVFSQ4's review of #69: no check-then-recompute."""
        calls = []

        def drifting(decision):
            calls.append(decision)
            return ("investigate-cause",) if len(calls) == 1 else ()

        port = OfflineModelPort()
        rt = ScopedContextRuntime(IncidentHost(TASKS["investigate"]), TriagePolicy(), port,
                                  requested_modules=drifting)
        rt.run()
        first = [m["id"] for m in port.packets[0][1]["instruction_modules"]]
        self.assertEqual(first, ["host-authority", "receipt-grounding", "investigate-cause"])

    def test_a_selection_is_only_sent_for_the_decision_the_host_validated(self):
        rt = ScopedContextRuntime(IncidentHost(TASKS["investigate"]), TriagePolicy(), OfflineModelPort())
        validated = Decision(Op.CALL_HEAVY, "validated by the host")
        with self.assertRaisesRegex(RuntimeError, "not validated"):
            rt._packet(validated, "heavy")  # no host validation yet
        self.assertEqual(rt.host_validates(validated, 1), (True, ""))
        with self.assertRaisesRegex(RuntimeError, "not validated"):
            rt._packet(Decision(Op.CALL_HEAVY, "a different decision"), "heavy")
        self.assertEqual([m["id"] for m in rt._packet(validated, "heavy")["instruction_modules"]],
                         ["host-authority", "receipt-grounding", "investigate-cause"])

    def test_ambiguous_referent_must_clarify(self):
        result, runtime, port = run_case("unknown", "What do the runbooks say about it?",
                                         QueryExtractionPolicy())
        self.assertEqual(result.status, "needs_clarification")
        self.assertEqual(runtime.host.receipts, [])
        self.assertEqual(result.writes_executed, 0)

    def test_strong_model_remains_an_operation_not_the_loop(self):
        result, runtime, port = run_case("diagnostic", TASKS["investigate"], TriagePolicy())
        self.assertEqual(result.status, "finished")
        self.assertEqual([r.tool for r in runtime.host.receipts],
                         ["error_trend", "recent_deploys", "validate_config"])
        self.assertEqual({row.controller for row in runtime.rows}, {"Turnwise policy"})
        self.assertEqual({x["id"] for x in runtime.module_audits[0]["included"]},
                         {"host-authority", "receipt-grounding", "investigate-cause"})
        self.assertEqual(result.writes_executed, 0)

    def test_host_rejects_an_overflowing_selection_before_model_invocation(self):
        port = OfflineModelPort()
        rt = ScopedContextRuntime(IncidentHost(TASKS["status"]), TriagePolicy(), port,
                                  module_byte_limit=1)
        result = rt.run()
        self.assertEqual(result.status, "held")
        self.assertEqual(port.packets, [])
        self.assertTrue(any("module selection overflow" in row.host for row in rt.rows))

    def test_untrusted_write_proposal_does_not_get_authority(self):
        class RoguePort(OfflineModelPort):
            def call(self, tier, packet):
                self.packets.append((tier, packet))
                return {"kind": "tool_proposal", "text": "Execute the rollback now.",
                        "tool": "rollback_deploy", "arguments_json": '{"service":"checkout"}',
                        "cited_receipts": []}

        port = RoguePort()
        rt = ScopedContextRuntime(IncidentHost(LIGHT_TASK), QueryExtractionPolicy(), port)
        result = rt.run()
        self.assertEqual(result.status, "needs_clarification")
        self.assertEqual(rt.host.receipts, [])
        self.assertEqual(result.writes_executed, 0)
        self.assertEqual(len(port.packets), 1)

    def test_explicit_write_intent_is_held_for_approval_not_dropped(self):
        port = OfflineModelPort()
        rt = ScopedContextRuntime(IncidentHost(TASKS["rollback"]), TriagePolicy(), port)
        result = rt.run()
        self.assertEqual(result.status, "held")
        self.assertEqual([r.status for r in rt.host.receipts], ["held_for_approval"])
        self.assertEqual([r.tool for r in rt.host.receipts], ["rollback_deploy"])
        self.assertEqual(result.writes_executed, 0)
        self.assertEqual(port.packets, [])

    def test_cli_renders_all_three_paths_with_exclusions(self):
        import contextlib
        import io
        from examples.architecture.action_context_demo import main

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            main()
        shown = output.getvalue()
        self.assertIn("deterministic host answer: answered_directly", shown)
        self.assertIn("light argument extraction: finished", shown)
        self.assertIn("capable-tier decision (simulated): finished", shown)
        self.assertIn("modules excluded:", shown)
        self.assertIn("Mechanism only", shown)

    def test_omitted_old_evidence_is_visible_and_cannot_be_cited(self):
        class OmitEvidence(TriagePolicy):
            def decide(self, snapshot):
                d = super().decide(snapshot)
                if d.op in (Op.CALL_LIGHT, Op.CALL_HEAVY):
                    return replace(d, context=())
                return d

        port = OfflineModelPort()
        rt = ScopedContextRuntime(IncidentHost(TASKS["investigate"]), OmitEvidence(), port)
        result = rt.run()
        self.assertNotEqual(result.status, "finished")
        self.assertEqual(rt.module_audits[0]["evidence_included"], [])
        self.assertEqual([x["id"] for x in rt.module_audits[0]["evidence_excluded"]], ["r1", "r2"])
        self.assertEqual(result.writes_executed, 0)


if __name__ == "__main__":
    unittest.main()
