"""Pre-authored, action-scoped instruction modules for the #55 offline exhibit.

A model operation (``CALL_LIGHT`` / ``CALL_HEAVY``) is given the manifest's
mandatory blocks for that operation, then the blocks a selector requests for
it, in that order. Selection is deterministic; neither the model nor retrieved
text writes instructions. A selection that does not fit the byte limit is
refused before any model call: no block is ever dropped silently.

The byte limit counts UTF-8 bytes of module texts only. It is NOT the provider
token budget or the full prompt (#16).
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

MANIFEST_PATH = Path(__file__).with_name("instruction_modules.v2.json")
MANIFEST_VERSION = "turnwise.action-modules.v2"
MODEL_OPERATIONS = frozenset(("CALL_LIGHT", "CALL_HEAVY"))
_FIELDS = frozenset(("id", "applies_to", "mandatory", "text", "source"))
_ID = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")


class ModuleSelectionError(ValueError):
    """Fail closed before a model is invoked when the module contract is invalid."""


@dataclass(frozen=True)
class Block:
    id: str
    applies_to: tuple[str, ...]
    mandatory: bool
    text: str
    source: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Manifest:
    version: str
    sha256: str
    blocks: tuple[Block, ...]


@dataclass(frozen=True)
class Selection:
    operation: str
    version: str
    manifest_sha256: str
    included: tuple[Block, ...]
    exclusions: tuple[tuple[str, str], ...]
    module_bytes: int
    module_byte_limit: int

    def audit(self) -> dict:
        """All module decisions, including absences, without model-created instructions."""
        return {
            "operation": self.operation,
            "manifest": self.version,
            "manifest_sha256": self.manifest_sha256,
            "included": [{"id": b.id, "source": b.source, "sha256": b.sha256} for b in self.included],
            "excluded": [{"id": name, "reason": reason} for name, reason in self.exclusions],
            "module_bytes": self.module_bytes,
            "module_byte_limit": self.module_byte_limit,
            "units": "UTF-8 module-text bytes; NOT provider tokens or full-prompt budget",
        }


def load_manifest(path: Path = MANIFEST_PATH) -> Manifest:
    """Read and validate the whole registry before any block is selected."""
    try:
        raw = path.read_bytes()
        data = json.loads(raw)
    except (OSError, ValueError) as exc:
        raise ModuleSelectionError(f"invalid module manifest: {exc}") from exc
    if not isinstance(data, dict) or data.get("version") != MANIFEST_VERSION:
        raise ModuleSelectionError("unsupported manifest version")
    entries = data.get("blocks")
    if not isinstance(entries, list) or not entries:
        raise ModuleSelectionError("manifest requires a nonempty blocks list")
    blocks = []
    for e in entries:
        # Exactly these fields: a block declaring behaviour this selector does not implement is refused.
        if not isinstance(e, dict) or set(e) != _FIELDS:
            raise ModuleSelectionError(f"each block needs exactly the fields {sorted(_FIELDS)}")
        if not isinstance(e["id"], str) or not _ID.fullmatch(e["id"]):
            raise ModuleSelectionError("invalid module id")
        if not all(isinstance(e[k], str) and e[k].strip() for k in ("text", "source")):
            raise ModuleSelectionError(f"{e['id']}: text and source must be non-empty strings")
        ops = e["applies_to"]
        if (not isinstance(ops, list) or not ops
                or not all(isinstance(op, str) and op in MODEL_OPERATIONS for op in ops) or len(set(ops)) != len(ops)):
            raise ModuleSelectionError(f"{e['id']}: applies_to must list distinct model operations")
        if type(e["mandatory"]) is not bool:
            raise ModuleSelectionError(f"{e['id']}: mandatory must be true or false")
        blocks.append(Block(e["id"], tuple(ops), e["mandatory"], e["text"], e["source"]))
    if len({b.id for b in blocks}) != len(blocks):
        raise ModuleSelectionError("duplicate module ids")
    return Manifest(data["version"], hashlib.sha256(raw).hexdigest(), tuple(blocks))


def select_modules(operation: str, *, requested: Iterable[str] = (), module_byte_limit: int = 1024,
                   manifest: Manifest | None = None) -> Selection:
    """The operation's mandatory blocks, then the requested ones in request order; refused if they do not fit."""
    if operation not in MODEL_OPERATIONS:
        raise ModuleSelectionError(f"not a model operation: {operation}")
    if type(module_byte_limit) is not int or module_byte_limit <= 0:
        raise ModuleSelectionError("module_byte_limit must be a positive integer")
    registry = manifest if manifest is not None else load_manifest()
    by_id = {b.id: b for b in registry.blocks}
    requests = tuple(requested)
    if any(not isinstance(name, str) or name not in by_id for name in requests):
        raise ModuleSelectionError("unknown requested module")
    if any(operation not in by_id[name].applies_to for name in requests):
        raise ModuleSelectionError("module requested for an incompatible operation")
    chosen = [b.id for b in registry.blocks if b.mandatory and operation in b.applies_to]
    chosen += [name for name in dict.fromkeys(requests) if name not in chosen]
    included = tuple(by_id[name] for name in chosen)
    used = sum(len(b.text.encode("utf-8")) for b in included)
    if used > module_byte_limit:
        raise ModuleSelectionError(
            f"module selection overflow: {used} > {module_byte_limit} bytes (no model invocation)")
    exclusions = tuple((b.id, "not_requested" if operation in b.applies_to else "different_operation")
                       for b in registry.blocks if b.id not in chosen)
    return Selection(operation, registry.version, registry.sha256, included, exclusions, used, module_byte_limit)
