"""Offline, stdlib-only contract tests for the frozen A+P prompt null (#43)."""
from __future__ import annotations

import unittest

from examples.architecture.checklist_null import (
    CHECKLIST_SHA256, CHECKLIST_TEXT, CHECKLIST_VERSION,
    checklist_hash_valid, native_instructions,
)
from examples.architecture.incident_env import AGENT_INSTRUCTIONS


class FrozenChecklistNullTests(unittest.TestCase):
    def test_unmodified_native_baseline_is_byte_identical(self):
        self.assertEqual(native_instructions(), AGENT_INSTRUCTIONS)
        self.assertEqual(native_instructions(checklist=False), AGENT_INSTRUCTIONS)

    def test_opt_in_is_a_fixed_append_not_an_authority_change(self):
        prompted = native_instructions(checklist=True)
        self.assertEqual(
            prompted,
            AGENT_INSTRUCTIONS + "\n\nEvidence checklist (A+P, " + CHECKLIST_VERSION
            + "; prompt guidance only):\n" + CHECKLIST_TEXT,
        )
        self.assertIn("A prompt is not authorization", prompted)
        self.assertIn("host tool receipt", prompted)

    def test_hash_is_pinned_for_pre_registered_comparator(self):
        self.assertEqual(len(CHECKLIST_SHA256), 64)
        self.assertTrue(checklist_hash_valid(), "v1 prompt changed; version and preregistration must be revisited")


if __name__ == "__main__":
    unittest.main()
