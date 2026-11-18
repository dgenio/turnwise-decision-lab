"""Download the pinned local models listed in models/local_models.json.

Optional: only needed to *re-run* real local inference. Tests, CI and the
published demo use committed traces and never download weights.

* Files are fetched by commit revision, never by branch name.
* Every file is verified against the sha256 recorded in the manifest.
* Weights go to $TURNWISE_MODEL_DIR (default ~/.cache/turnwise-models),
  outside the repository. Nothing here executes code from a model repository.

    python -m scripts.fetch_models                 # all models (~3.0 GB)
    python -m scripts.fetch_models --only s1-llm-auto-router
"""
from __future__ import annotations

from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "models" / "local_models.json"


def model_dir() -> Path:
    return Path(os.environ.get("TURNWISE_MODEL_DIR", Path.home() / ".cache" / "turnwise-models"))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(entry: dict, dest_root: Path) -> list[Path]:
    out = []
    for f in entry["files"]:
        dest = dest_root / entry["key"] / f["path"]
        if dest.exists() and dest.stat().st_size == f["size"] and (f["sha256"] is None or _sha256(dest) == f["sha256"]):
            out.append(dest)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://huggingface.co/{entry['repo']}/resolve/{entry['revision']}/{f['path']}"
        tmp = dest.with_suffix(dest.suffix + ".part")
        print(f"  downloading {entry['repo']}@{entry['revision'][:8]}/{f['path']} ({f['size'] / 1e6:.1f} MB)", flush=True)
        with urllib.request.urlopen(url, timeout=120) as r, tmp.open("wb") as w:
            shutil.copyfileobj(r, w, 1 << 20)
        if tmp.stat().st_size != f["size"]:
            tmp.unlink()
            raise RuntimeError(f"size mismatch for {f['path']}")
        if f["sha256"] is not None and _sha256(tmp) != f["sha256"]:
            tmp.unlink()
            raise RuntimeError(f"sha256 mismatch for {f['path']}")
        tmp.replace(dest)
        out.append(dest)
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--only", action="append", help="model key(s) to fetch")
    args = p.parse_args()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    root = model_dir()
    for entry in manifest["models"]:
        if args.only and entry["key"] not in args.only:
            continue
        print(f"{entry['key']}: {entry['repo']} @ {entry['revision']} ({entry['license']})", flush=True)
        fetch(entry, root)
    print(f"verified in {root}")


if __name__ == "__main__":
    sys.exit(main())
