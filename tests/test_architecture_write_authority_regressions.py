"""Write-authority regressions ported from experimental PRs #37 and #46 onto the canonical host.

#37 (v0.6 P0 host contract) and #46 (v0.8 intent-bound host) were closed without merging: their
runtimes are not Turnwise Core on ``main``. Their *adversarial requests* are kept here, adapted to the
canonical ``IncidentHost`` and its only write (``rollback_deploy``), so the invariants they tested stay
pinned:

* questions, advice, hypotheticals, negations, quotes, attributions and retractions never authorise a
  write (from #37 ``test_write_intent.py``);
* a write's target comes from the user's own action clause, never from another clause or an unknown
  name (the L56 wrong-target class, from #46 ``test_v08_host_boundary_45.py``);
* a direct ``execute`` call cannot bypass validation, and nothing is ever executed (from #46).

These are developer-authored mechanism regressions, written after reading the original failures; they
are not held-out evidence and do not show that the lexical parser generalises. Rollback mentions the
parser does not accept as a plain request (a rollback clause after a read clause, a second service in one
clause) are never held; since #72 the host action record lists them as NOT REQUESTED, which
``test_architecture_action_integrity.py`` covers. Whether to hold them instead is open in issue #12.
"""
from __future__ import annotations

import unittest

from examples.architecture.incident_env import IncidentHost, requested_writes

ROLLBACK = "rollback_deploy"

NOT_A_REQUEST = (
    # questions and advice
    "Should we roll back checkout?",
    "Can we roll back checkout?",
    "roll back checkout?",
    "Is it safe to roll back checkout?",
    "What would happen if we rolled back checkout?",
    "Tell me the rollback procedure for checkout.",
    # negations
    "Do not roll back checkout.",
    "Do not, under any circumstances, roll back checkout.",
    "Under no circumstances should checkout be rolled back.",
    "don't roll anything back yet. just tell me which deploy hit checkout",
    "Rolling back checkout is off the table.",
    # conditions and hedges
    "Is checkout healthy? If not, roll it back.",
    "Roll back checkout, or maybe not.",
    # quotes and attributions
    'the runbook says "roll back checkout if errors exceed 5%"',
    "The assistant said: roll back payments.",
    # retractions later in the same turn
    "Roll back checkout. Actually no, wait, don't.",
    "roll back checkout. Never mind.",
    "Roll back checkout. Forget it.",
    # no resolvable target
    "roll it back",
    "roll back inventory service, and check checkout health",
)

EXACT_REQUESTS = (
    ("Please roll back checkout.", {"checkout"}),
    ("Revert payments now", {"payments"}),
    ("Roll back the latest checkout deployment.", {"checkout"}),
    # compound action + read: only the action clause names the target (L56 class)
    ("Roll back checkout and check search health", {"checkout"}),
    ("roll back checkout, then check payments health", {"checkout"}),
    ("Check payments health. Roll back checkout.", {"checkout"}),
)


class WriteIntentRegressions(unittest.TestCase):
    def test_mentions_questions_negations_quotes_and_retractions_never_authorise(self):
        for text in NOT_A_REQUEST:
            with self.subTest(text=text):
                self.assertEqual(requested_writes(text), frozenset())

    def test_the_target_comes_from_the_users_own_action_clause(self):
        for text, services in EXACT_REQUESTS:
            with self.subTest(text=text):
                self.assertEqual(requested_writes(text), frozenset((ROLLBACK, s) for s in services))


class DirectExecutionBoundary(unittest.TestCase):
    """Authority lives in ``IncidentHost.execute`` itself, so no caller can skip a separate validate step."""

    def test_unrequested_write_is_rejected_whoever_calls_execute(self):
        for proposer in ("llm", "turnwise_policy", "native_agent"):
            with self.subTest(proposer=proposer):
                host = IncidentHost("Is checkout healthy right now?")
                receipt = host.execute(ROLLBACK, {"service": "checkout"}, proposed_by=proposer)
                self.assertEqual(receipt.status, "rejected")
                self.assertEqual(host.write_ledger, [])

    def test_wrong_target_is_rejected_and_the_requested_one_is_only_held(self):
        host = IncidentHost("Roll back checkout and check search health")
        wrong = host.execute(ROLLBACK, {"service": "search"}, proposed_by="llm")
        right = host.execute(ROLLBACK, {"service": "checkout"}, proposed_by="llm")
        self.assertEqual((wrong.status, right.status), ("rejected", "held_for_approval"))
        self.assertEqual(host.write_ledger, [])
        self.assertIn("HELD", host.action_record())

    def test_malformed_write_arguments_are_rejected_before_any_handler(self):
        host = IncidentHost("Please roll back checkout.")
        for arguments in ({}, {"service": "checkout", "force": True}, {"service": "Checkout"}, "checkout", None):
            with self.subTest(arguments=arguments):
                self.assertEqual(host.execute(ROLLBACK, arguments, proposed_by="llm").status, "rejected")
        self.assertEqual(host.write_ledger, [])


if __name__ == "__main__":
    unittest.main()
