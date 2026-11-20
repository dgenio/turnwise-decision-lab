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
from unittest import mock

from examples.architecture.action_context_demo import (
    AliasExtractionPolicy, OfflineModelPort, run_case,
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
        self.assertIn({"id": "summarize-status", "reason": "different_operation"}, audit["excluded"])
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
            ("CALL_HEAVY", ("summarize-status",)),
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
        for field, value in (("id", ["host-authority"]), ("id", 7), ("applies_to", "CALL_LIGHT"),
                             ("depends_on", "receipt-grounding"), ("conflicts_with", [1])):
            typed = json.loads(json.dumps(base))
            typed["blocks"][0][field] = value
            variants.append(typed)
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

    def test_light_extraction_of_an_alias_the_host_cannot_resolve_asks_the_user(self):
        # Integration finding (rebased on #64's host evidence gate): "check-out" is not a service the host
        # resolves from the user's words, so a model's extraction of it is a suggestion, not a referent.
        result, runtime, port = run_case("extract", "Is check-out healthy right now?", AliasExtractionPolicy())
        self.assertEqual(result.status, "needs_clarification")
        self.assertEqual(runtime.host.receipts, [])
        self.assertEqual(len(port.packets), 1)
        self.assertEqual([m["id"] for m in port.packets[0][1]["instruction_modules"]],
                         ["host-authority", "receipt-grounding", "extract-arguments"])
        self.assertEqual(runtime.outcomes[0].kind, "tool_proposal")
        self.assertNotIn("checkout", result.answer)  # model-written names are not relayed as the message
        self.assertEqual(result.writes_executed, 0)

    def test_host_refuses_finish_on_a_model_resolved_referent_even_if_a_policy_adopts_it(self):
        class AdoptAnyRead(AliasExtractionPolicy):
            """The pre-integration behaviour: adopt the model's alias resolution."""
            def decide(self, s):
                latest = s.latest
                if isinstance(latest, ModelOutcome) and latest.kind == "tool_proposal" and not s.receipts:
                    return Decision(Op.CALL_TOOL, "adopt the model's alias resolution (permissive test policy)",
                                    target=latest.proposal.tool, arguments=dict(latest.proposal.arguments),
                                    adopted_from=latest.id)
                return super().decide(s)

        result, runtime, port = run_case("permissive", "Is check-out healthy right now?", AdoptAnyRead())
        self.assertEqual([r.status for r in runtime.host.receipts], ["executed"])  # a read is allowed...
        rejected = [row.host for row in runtime.rows if row.host.startswith("REJECTED")]
        self.assertEqual(len(rejected), 1)  # ...but the host will not accept an answer about it
        self.assertEqual([row.short for row in runtime.rows if "rejected" in row.short],
                         ["policy -> FINISH [rejected]"])
        self.assertIn("unresolved service target", rejected[0])
        self.assertNotEqual(result.status, "finished")
        self.assertEqual(result.writes_executed, 0)

    def test_light_extraction_with_a_host_resolved_referent_finishes(self):
        result, runtime, port = run_case("extract", "Is checkout healthy right now?", AliasExtractionPolicy())
        self.assertEqual(result.status, "finished")
        self.assertEqual([(r.tool, r.arguments, r.status) for r in runtime.host.receipts],
                         [("service_health", {"service": "checkout"}, "executed")])
        self.assertEqual([[m["id"] for m in packet["instruction_modules"]] for _, packet in port.packets],
                         [["host-authority", "receipt-grounding", "extract-arguments"],
                          ["host-authority", "receipt-grounding", "summarize-status"]])
        self.assertEqual(runtime.module_audits[0]["evidence_included"], [])
        self.assertEqual(runtime.module_audits[1]["evidence_included"], ["r1"])
        self.assertEqual(result.writes_executed, 0)

    def test_light_status_summary_uses_only_the_summary_module(self):
        result, runtime, port = run_case("status", TASKS["status"], TriagePolicy())
        self.assertEqual(result.status, "finished")
        self.assertEqual(len(port.packets), 1)
        self.assertEqual([m["id"] for m in port.packets[0][1]["instruction_modules"]],
                         ["host-authority", "receipt-grounding", "summarize-status"])

    def test_the_validated_selection_is_the_one_sent_even_if_the_manifest_file_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            path.write_bytes(MANIFEST_PATH.read_bytes())
            pinned = load_manifest(path)
            port = OfflineModelPort()
            rt = ScopedContextRuntime(IncidentHost(TASKS["investigate"]), TriagePolicy(), port, manifest=pinned)
            path.write_text("{}", encoding="utf-8")  # a later edit cannot reach a running runtime
            result = rt.run()
        self.assertEqual(result.status, "finished")
        self.assertEqual({a["manifest_sha256"] for a in rt.module_audits}, {pinned.sha256})
        for _, packet in port.packets:
            self.assertEqual([m["id"] for m in packet["instruction_modules"]],
                             ["host-authority", "receipt-grounding", "investigate-cause"])

    def test_an_invalid_manifest_fails_when_the_runtime_is_built(self):
        with mock.patch("examples.architecture.scoped_runtime.load_manifest",
                        side_effect=ModuleSelectionError("invalid module manifest")):
            with self.assertRaises(ModuleSelectionError):
                ScopedContextRuntime(IncidentHost(TASKS["status"]), TriagePolicy(), OfflineModelPort())

    def test_ambiguous_referent_must_clarify(self):
        result, runtime, port = run_case("unknown", "Is the service healthy right now?",
                                         AliasExtractionPolicy())
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
        rt = ScopedContextRuntime(IncidentHost("Is check-out healthy?"), AliasExtractionPolicy(), port)
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

    def test_cli_renders_all_four_paths_with_exclusions(self):
        import contextlib
        import io
        from examples.architecture.action_context_demo import main

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            main()
        shown = output.getvalue()
        self.assertIn("deterministic host answer: answered_directly", shown)
        self.assertIn("light status summary: finished", shown)
        self.assertIn("light argument extraction, alias the host cannot resolve: needs_clarification", shown)
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
