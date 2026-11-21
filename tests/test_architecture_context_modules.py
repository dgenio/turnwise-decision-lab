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


class ManifestContractTests(unittest.TestCase):
    def test_manifest_is_versioned_and_has_provenance(self):
        registry = load_manifest()
        self.assertEqual(registry.version, "turnwise.action-modules.v1")
        self.assertEqual(len(registry.sha256), 64)
        self.assertEqual(len(registry.blocks), len({b.id for b in registry.blocks}))

    def test_mandatory_and_requested_dependencies_are_loaded(self):
        s = select_modules("CALL_HEAVY", requested=("investigate-cause",))
        self.assertEqual([b.id for b in s.included],
                         ["host-authority", "receipt-grounding", "investigate-cause"])
        audit = s.audit()
        self.assertEqual(len(audit["included"]), 3)
        self.assertIn({"id": "summarize-evidence", "reason": "different_operation"}, audit["excluded"])
        self.assertIn({"id": "prepare-user-update", "reason": "not_requested"}, audit["excluded"])
        self.assertIn("NOT provider tokens", audit["units"])

    def test_multilabel_module_composition(self):
        s = select_modules("CALL_HEAVY", requested=("investigate-cause", "prepare-user-update"))
        self.assertEqual(set(b.id for b in s.included),
                         {"host-authority", "receipt-grounding", "investigate-cause", "prepare-user-update"})

    def test_conflicting_options_have_explicit_exclusion(self):
        s = select_modules("CALL_HEAVY", requested=("expanded-mode", "concise-mode"))
        self.assertIn("concise-mode", [b.id for b in s.included])
        self.assertNotIn("expanded-mode", [b.id for b in s.included])
        self.assertIn("conflict", dict(s.exclusions)["expanded-mode"])

    def test_mandatory_overflow_fails_closed(self):
        with self.assertRaisesRegex(ModuleSelectionError, "mandatory module overflow"):
            select_modules("CALL_LIGHT", module_byte_limit=1)

    def test_optional_overflow_records_omission(self):
        minimal = select_modules("CALL_LIGHT")
        mandatory_bytes = sum(len(b.text.encode("utf-8")) for b in minimal.included)
        limited = select_modules("CALL_LIGHT", requested=("extract-arguments",),
                                 module_byte_limit=mandatory_bytes)
        self.assertEqual({b.id for b in limited.included}, {"host-authority", "receipt-grounding"})
        self.assertEqual(dict(limited.exclusions)["extract-arguments"], "optional_module_byte_overflow")

    def test_invalid_requests_rejected(self):
        for op, requested in (
            ("CALL_HEAVY", ("summarize-evidence",)),
            ("CALL_LIGHT", ("made-up-instructions",)),
            ("CALL_TOOL", ()),
        ):
            with self.subTest(op=op, requested=requested), self.assertRaises(ModuleSelectionError):
                select_modules(op, requested=requested)
        for limit in (0, -1, 1.5, True):
            with self.subTest(limit=limit), self.assertRaises(ModuleSelectionError):
                select_modules("CALL_LIGHT", module_byte_limit=limit)

    def test_missing_dependency_and_cycle_are_rejected(self):
        base = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        variants = []
        missing = json.loads(json.dumps(base))
        next(b for b in missing["blocks"] if b["id"] == "investigate-cause")["depends_on"] = ["absent"]
        variants.append(missing)
        cycle = json.loads(json.dumps(base))
        next(b for b in cycle["blocks"] if b["id"] == "host-authority")["depends_on"] = ["receipt-grounding"]
        next(b for b in cycle["blocks"] if b["id"] == "receipt-grounding")["depends_on"] = ["host-authority"]
        variants.append(cycle)
        asymmetric = json.loads(json.dumps(base))
        next(b for b in asymmetric["blocks"] if b["id"] == "expanded-mode")["conflicts_with"] = []
        variants.append(asymmetric)
        for variant in variants:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "manifest.json"
                path.write_text(json.dumps(variant), encoding="utf-8")
                with self.assertRaises(ModuleSelectionError):
                    load_manifest(path)


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
            return ("investigate-cause",) if len(calls) == 1 else ("prepare-user-update",)

        port = OfflineModelPort()
        rt = ScopedContextRuntime(IncidentHost(TASKS["investigate"]), TriagePolicy(), port,
                                  requested_modules=drifting)
        rt.run()
        first = [m["id"] for m in port.packets[0][1]["instruction_modules"]]
        self.assertIn("investigate-cause", first)
        self.assertNotIn("prepare-user-update", first)

    def test_malformed_manifest_types_fail_closed_not_with_type_errors(self):
        base = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        unhashable = json.loads(json.dumps(base))
        unhashable["blocks"][0]["id"] = ["host-authority"]
        stringly = json.loads(json.dumps(base))
        stringly["blocks"][0]["applies_to"] = "CALL_HEAVY"
        numeric = json.loads(json.dumps(base))
        numeric["blocks"][2]["depends_on"] = [7]
        for variant in (unhashable, stringly, numeric):
            with self.subTest(variant=variant["blocks"][0]["id"]), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "manifest.json"
                path.write_text(json.dumps(variant), encoding="utf-8")
                with self.assertRaises(ModuleSelectionError):
                    load_manifest(path)

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

    def test_host_rejects_mandatory_overflow_before_model_invocation(self):
        port = OfflineModelPort()
        rt = ScopedContextRuntime(IncidentHost(TASKS["status"]), TriagePolicy(), port,
                                  module_byte_limit=1)
        result = rt.run()
        self.assertEqual(result.status, "held")
        self.assertEqual(port.packets, [])
        self.assertTrue(any("mandatory module overflow" in row.host for row in rt.rows))

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
