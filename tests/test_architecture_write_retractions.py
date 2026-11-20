"""Canonical Turnwise Core write-intent regressions (not benchmark evidence)."""
import unittest

from examples.architecture.incident_env import IncidentHost, requested_writes


class CurrentTurnActionAuthorityTests(unittest.TestCase):
    def test_plain_current_user_imperatives_remain_eligible_for_hold(self):
        for message, target in (
            ("Roll back checkout.", "checkout"),
            ("Please roll back the latest checkout deployment.", "checkout"),
            ("Revert auth.", "auth"),
            ("Cancel that. Roll back checkout.", "checkout"),
        ):
            with self.subTest(message=message):
                self.assertEqual(requested_writes(message), {("rollback_deploy", target)})

    def test_question_ending_is_not_an_imperative(self):
        for message in (
            "Roll back checkout?",
            "Please roll back checkout?",
            "Revert auth? I am asking, not authorizing.",
            "Roll back checkout? No.",
        ):
            with self.subTest(message=message):
                self.assertEqual(requested_writes(message), frozenset())

    def test_later_retraction_overrides_earlier_positive_request(self):
        for message in (
            "Roll back checkout. Actually, no.",
            "Roll back checkout. Actually don't.",
            "Please roll back checkout; cancel that.",
            "Revert auth. Never mind.",
            "Roll back checkout. Scratch that.",
            "Roll back checkout. Forget it.",
            "Roll back checkout. Wait, don't.",
            "Roll back checkout. On second thought, let's investigate first.",
            "Roll back checkout. I changed my mind.",
            "Roll back checkout. Cancel the request.",
        ):
            with self.subTest(message=message):
                self.assertEqual(requested_writes(message), frozenset())

    def test_mere_mentions_and_other_people_do_not_authorize(self):
        for message in (
            "The assistant said roll back checkout.",
            "Should we roll back checkout?",
            "Don't roll back checkout.",
            'The runbook says: "Roll back checkout."',
            "Roll back inventory, and tell me about checkout.",
        ):
            with self.subTest(message=message):
                self.assertEqual(requested_writes(message), frozenset())

    def test_direct_host_execution_still_checks_bound_original_request(self):
        for message in ("Roll back checkout?", "Roll back checkout. Actually, no.",
                        "Is checkout healthy?"):
            with self.subTest(message=message):
                host = IncidentHost(message)
                receipt = host.execute("rollback_deploy", {"service": "checkout"},
                                       proposed_by="native_agent")
                self.assertEqual(receipt.status, "rejected")
                self.assertEqual(host.write_ledger, [])
                self.assertIn("not requested", receipt.reason)

    def test_positive_request_creates_hold_not_execution(self):
        host = IncidentHost("Please roll back checkout.")
        receipt = host.execute("rollback_deploy", {"service": "checkout"},
                               proposed_by="turnwise_policy")
        self.assertEqual(receipt.status, "held_for_approval")
        self.assertEqual(host.write_ledger, [])


if __name__ == "__main__":
    unittest.main()
