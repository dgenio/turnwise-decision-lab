"""Freeze the v0.7 study before the locked run.

    python -m turnwise_lab.v07.freeze            # writes docs/v07-freeze.json
    python -m turnwise_lab.v07.freeze --check    # exits non-zero if any frozen file changed

The manifest holds the sha256 of every file that can change an outcome on the
locked set: the locked tasks, the scorer, the gate, the controllers, the v0.6
code they wrap, the decision head, the model manifest, the predictions and the
pre-registration. ``bench --set locked`` refuses to run unless it matches. The
report and the demo page are not frozen: they only read traces.
"""
from __future__ import annotations

from datetime import datetime, timezone
import argparse
import json
import subprocess

from .bench import FREEZE, ROOT
from .tasks import sha256

FROZEN = ["fixtures/v07_locked.json", "fixtures/v07_dev.json", "docs/preregistration-v0.7.md", "docs/v07-task-authoring-spec.md",
          "docs/v06-adjudication-rubric.md", "models/turnwise-dm-head.json", "models/local_models.json",
          *[f"turnwise_lab/v07/{m}.py" for m in ("evidence", "gate", "controllers", "bench", "tasks", "world", "predictions", "adjudication")],
          "turnwise_lab/core.py", "turnwise_lab/deciders.py",
          *[f"turnwise_lab/agent/{m}.py" for m in ("heavy_agent", "host", "loop", "providers", "context", "render", "bench", "contracts",
                                                    "world", "dm_features", "audit")],
          "turnwise_lab/local_models.py", "turnwise_lab/runtime.py", "turnwise_lab/world.py"]


def manifest() -> dict:
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    return {"frozen_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "parent_commit": head,
            "note": "The commit that adds this file is the freeze commit. Nothing listed here may change before the locked run.",
            "sha256": {rel: sha256(ROOT / rel) for rel in FROZEN}}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--check", action="store_true")
    args = p.parse_args()
    if args.check:
        if not FREEZE.exists():
            locked = ROOT / "reports" / "v07" / "traces" / "locked"
            if locked.exists() and any(locked.iterdir()):
                raise SystemExit("locked traces exist but docs/v07-freeze.json does not")
            print("not frozen yet: no manifest and no locked traces")
            return
        m = json.loads(FREEZE.read_text())
        changed = [rel for rel, d in m["sha256"].items() if sha256(ROOT / rel) != d]
        if changed:
            raise SystemExit("changed since the freeze: " + ", ".join(changed))
        print(f"{len(m['sha256'])} frozen files unchanged")
        return
    FREEZE.write_text(json.dumps(manifest(), indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {FREEZE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
