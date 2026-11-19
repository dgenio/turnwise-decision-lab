"""Credential-free checks for the one-shot local paid-smoke launcher."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from examples.architecture import secure_live_once as mod


class SecureLiveOnceTests(unittest.TestCase):
    def test_no_execute_is_strictly_free_and_never_prompts_for_a_key(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(mod, "_private_directory", return_value=Path(tmp)), \
             mock.patch.object(mod, "_invoke", return_value=0) as invoke, \
             mock.patch.object(mod.getpass, "getpass") as prompt, \
             mock.patch.dict(os.environ, {"OPENAI_AGENTS_DISABLE_TRACING": "0"}):
            self.assertEqual(mod.main([]), 0)
            self.assertEqual(invoke.call_count, 2)
            self.assertIn("double", invoke.call_args_list[0].args[0])
            self.assertIn("--plan", invoke.call_args_list[1].args[0])
            prompt.assert_not_called()
            self.assertEqual(os.environ["OPENAI_AGENTS_DISABLE_TRACING"], "1")
            self.assertFalse((Path(tmp) / mod.ATTEMPT_NAME).exists())

    def test_rehearsal_failure_prevents_key_access_and_provider_run(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(mod, "_private_directory", return_value=Path(tmp)), \
             mock.patch.object(mod, "_invoke", return_value=3) as invoke, \
             mock.patch.object(mod.getpass, "getpass") as prompt:
            self.assertEqual(mod.main(["--execute"]), 3)
            invoke.assert_called_once()
            prompt.assert_not_called()
            self.assertFalse((Path(tmp) / mod.ATTEMPT_NAME).exists())

    def test_one_attempt_key_lives_only_in_environment_during_paid_call(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(mod, "_private_directory", return_value=Path(tmp)), \
             mock.patch.object(mod.getpass, "getpass", return_value="sk-test-never-print"), \
             mock.patch("builtins.input", return_value="RUN"), \
             mock.patch.dict(os.environ, {}, clear=True):
            calls = []
            def invoke(args):
                calls.append(args)
                if "--provider" in args and args[args.index("--provider") + 1] == "openai" and "--plan" not in args:
                    self.assertEqual(os.environ.get("OPENAI_API_KEY"), "sk-test-never-print")
                    self.assertEqual(os.environ["OPENAI_AGENTS_DISABLE_TRACING"], "1")
                return 0
            with mock.patch.object(mod, "_invoke", side_effect=invoke):
                self.assertEqual(mod.main(["--execute"]), 0)
                self.assertNotIn("OPENAI_API_KEY", os.environ)
                self.assertEqual(len(calls), 3)
                self.assertEqual(calls[-1][calls[-1].index("--authorize-usd") + 1], "2.00")
                self.assertTrue(all("sk-test-never-print" not in " ".join(c) for c in calls))
                marker = Path(tmp) / mod.ATTEMPT_NAME
                self.assertTrue(marker.exists())
                self.assertNotIn("sk-test-never-print", marker.read_text())
                self.assertEqual(json.loads(marker.read_text())["status"], "attempt_started_not_proof_of_success")
                self.assertEqual(mod.main(["--execute"]), 2)
                self.assertEqual(len(calls), 5)  # second attempt repeats only free verification

    def test_declining_confirmation_does_not_consume_the_attempt(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(mod, "_private_directory", return_value=Path(tmp)), \
             mock.patch.object(mod, "_invoke", return_value=0), \
             mock.patch.object(mod.getpass, "getpass", return_value="sk-synthetic"), \
             mock.patch("builtins.input", return_value="NO"):
            self.assertEqual(mod.main(["--execute"]), 2)
            self.assertFalse((Path(tmp) / mod.ATTEMPT_NAME).exists())

    def test_reservation_is_exclusive(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            mod._reserve_one_attempt(d)
            with self.assertRaises(FileExistsError):
                mod._reserve_one_attempt(d)


if __name__ == "__main__":
    unittest.main()
