"""Repository integrity: frozen research inputs are pinned, and no weights or secrets are committed (#22, #23).

CI already regenerates every *derived* report and page and requires byte-identical
output. These tests cover what regeneration cannot: the frozen *inputs* and the
historical evidence records themselves. Changing a pinned file is allowed only as
a deliberate, reviewed act: update the hash here in the same PR and say why.
"""
from __future__ import annotations

import hashlib
import os
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Immutable inputs and historical records (see AGENTS.md "Frozen evidence").
FROZEN = {
    "docs/preregistration-v0.5.md": "8ebeea35d314d430c360ddb3203bfc51c6bcb8d9269d76921890859fb4a75f0c",
    "fixtures/sessions.json": "6cc1377592627d2e811108c02c5437d6eda4c685a87327048023b8e6e585a625",
    "fixtures/scenarios.json": "0f0cacfe8047620963e5d68ec4562ae98216dc3b7f86eedfb88ac75b9842fe2e",
    "fixtures/route_train.jsonl": "121c22365d00ec9d7e8fb895cc4ec133ec62be10d83faa088b826696898a870d",
    "fixtures/route_test.jsonl": "be72dd7f506cfdbd1db40eba46e309904d145cbc31fba9100143f74793acfc07",
    "turnwise_lab/world.py": "be62292baf56c04ef87304d9e6165e70811b17eb2371e3abebc4fcd7b9c60f8a",
    "reports/live-smoke-44520205372.md": "4d175437a8e014427c448f664843b3206260f3178defd35adf435ded7723837e",
}

WEIGHT_SUFFIXES = {".onnx", ".gguf", ".safetensors", ".pt", ".pth", ".ckpt", ".pkl", ".bin", ".h5"}
SECRET_FILES = {".env", "id_rsa", "id_ed25519", "credentials.json"}
# Real provider keys mix case and digits; obvious test placeholders ("sk-not-used-...") do not.
SECRET_TEXT = re.compile(r"\bsk-(?:proj-)?(?=[\w-]*\d)(?=[\w-]*[A-Z])[A-Za-z0-9_-]{32,}"
                         r"|-----BEGIN [A-Z ]*PRIVATE KEY-----|\bghp_[A-Za-z0-9]{30,}")
SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules"}


def repository_files():
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            yield Path(base) / name


class FrozenEvidence(unittest.TestCase):
    def test_frozen_inputs_and_historical_records_are_unchanged(self):
        for rel, expected in FROZEN.items():
            with self.subTest(file=rel):
                digest = hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()
                self.assertEqual(digest, expected, f"{rel} changed: frozen evidence must not change silently")


class Hygiene(unittest.TestCase):
    def test_no_model_weights_or_credential_files(self):
        found = [str(p.relative_to(ROOT)) for p in repository_files()
                 if p.suffix.lower() in WEIGHT_SUFFIXES or p.name in SECRET_FILES]
        self.assertEqual(found, [])

    def test_no_secret_shaped_strings(self):
        offenders = []
        for path in repository_files():
            if path.stat().st_size > 5_000_000:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if SECRET_TEXT.search(text):
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
