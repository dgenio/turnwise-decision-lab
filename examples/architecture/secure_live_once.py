"""Run one approved Turnwise real-provider smoke test without storing the API key.

    python -m examples.architecture.secure_live_once             # free rehearsal / plan
    python -m examples.architecture.secure_live_once --execute   # one real run

The paid run asks for a project API key without echoing it, turns off the
Agents SDK's separate tracing exporter, stores results outside the repository
and creates an exclusive one-attempt marker before any provider request.
A second paid attempt requires a fresh owner decision.

This is a *client-side estimated spend guard*, not a provider billing limit.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

MODEL = "gpt-6.1-sol"
MAX_USD = "2.00"
COMMON = ["--model", MODEL, "--reasoning-effort", "low", "--max-output-tokens", "2000", "--timeout", "60"]
PRICES = ["--input-usd-per-mtok", "2.50", "--output-usd-per-mtok", "10.00"]
ATTEMPT_NAME = "single-gpt-6.1-sol-attempt.json"


def _private_directory() -> Path:
    """Keep the result and single-attempt marker outside any Git checkout."""
    folder = Path.home() / ".turnwise-decision-lab"
    if folder.is_symlink():
        raise RuntimeError("refusing a symlinked results directory")
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "posix":
        folder.chmod(0o700)
    return folder


def _invoke(args: list[str]) -> int:
    from . import live_smoke
    return live_smoke.main(args)


def _reserve_one_attempt(folder: Path) -> Path:
    """Exclusive creation, even if two launcher processes start together.

    An interrupted or failed provider request still consumes this one-shot
    permission; the owner must explicitly authorize any new attempt.
    """
    path = folder / ATTEMPT_NAME
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"model": MODEL, "maximum_authorized_usd": MAX_USD,
                   "status": "attempt_started_not_proof_of_success",
                   "created_at": datetime.now(timezone.utc).isoformat()}, f)
        f.write("\n")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true",
                        help="after the free rehearsal, prompt securely and make ONE paid attempt")
    options = parser.parse_args(argv)
    # The Agents SDK default tracing provider can export a separate HTTP call
    # outside the provider ledger. Disable it BEFORE importing the SDK.
    os.environ["OPENAI_AGENTS_DISABLE_TRACING"] = "1"

    folder = _private_directory()
    print("Free rehearsal: real SDK/provider classes, simulated HTTP responses; no API key.")
    replay = _invoke(["--provider", "double", *COMMON,
                      "--out", str(folder / "rehearsal-gpt-6.1-sol.json")])
    if replay != 0:
        print("Offline rehearsal failed; paid run blocked.", file=sys.stderr)
        return replay
    print("Free pricing/limit plan (no provider requests):")
    planned = _invoke(["--plan", "--provider", "openai", *COMMON, *PRICES])
    if planned != 0:
        print("Planning failed; paid run blocked.", file=sys.stderr)
        return planned

    if not options.execute:
        print("\nNo real inference was performed. To make the ONE authorized paid attempt, "
              "rerun with --execute on your own computer.")
        return 0

    marker = folder / ATTEMPT_NAME
    if marker.exists():
        print(f"One paid attempt is already recorded in {marker}; not running again. "
              "A new owner authorization is required for any repeat.", file=sys.stderr)
        return 2

    key = getpass.getpass("OpenAI PROJECT API key (hidden, used only in this process): ").strip()
    if not key or any(ch.isspace() for ch in key):
        print("No usable key supplied. Nothing sent.", file=sys.stderr)
        return 2
    confirmation = input("Type RUN to attempt exactly one paid 4-way smoke test (estimated cap US$2): ").strip()
    if confirmation != "RUN":
        print("Cancelled before any paid requests.", file=sys.stderr)
        return 2

    try:
        _reserve_one_attempt(folder)
    except FileExistsError:
        print("Another process has already reserved the single attempt. Stopping.", file=sys.stderr)
        return 2

    args = ["--provider", "openai", *COMMON, *PRICES, "--authorize-usd", MAX_USD,
            "--out", str(folder / "paid-gpt-6.1-sol.json")]
    os.environ["OPENAI_API_KEY"] = key
    try:
        print(f"Attempt reserved. Results: {folder / 'paid-gpt-6.1-sol.json'}")
        return _invoke(args)
    finally:
        os.environ.pop("OPENAI_API_KEY", None)
        key = ""


if __name__ == "__main__":
    raise SystemExit(main())
