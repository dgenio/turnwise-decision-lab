"""Pre-authored action-scoped instruction modules for the #55 offline exhibit.

This is NOT the token budget or authorization system (#16): the budget here
counts UTF-8 bytes of module texts only, not the complete provider prompt.
Selection is deterministic; neither the model nor retrieved text writes rules.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

MANIFEST_PATH = Path(__file__).with_name("instruction_modules.v1.json")
MODEL_OPERATIONS = frozenset(("CALL_LIGHT", "CALL_HEAVY"))
_ID = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")


class ModuleSelectionError(ValueError):
    """Fail closed before a model is invoked when the module contract is invalid."""


@dataclass(frozen=True)
class Block:
    id: str
    text: str
    source: str
    applies_to: tuple[str, ...]
    mandatory: bool
    priority: int
    depends_on: tuple[str, ...]
    conflicts_with: tuple[str, ...]

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Manifest:
    version: str
    sha256: str
    blocks: tuple[Block, ...]

    def by_id(self) -> dict[str, Block]:
        return {b.id: b for b in self.blocks}


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
    """Validate the whole static registry before selecting any block."""
    raw = path.read_bytes()
    try:
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get("version") != "turnwise.action-modules.v1":
            raise ModuleSelectionError("unsupported manifest version")
        entries = data["blocks"]
        if not isinstance(entries, list) or not entries:
            raise ModuleSelectionError("manifest requires a nonempty blocks list")
        if any(not isinstance(e, dict) or not all(isinstance(e.get(k), list)
                                                  for k in ("applies_to", "depends_on", "conflicts_with"))
               for e in entries):
            raise ModuleSelectionError("each block must be an object with list-valued "
                                       "applies_to, depends_on and conflicts_with")
        blocks = tuple(
            Block(
                id=e["id"], text=e["text"], source=e["source"], applies_to=tuple(e["applies_to"]),
                mandatory=e["mandatory"], priority=e["priority"],
                depends_on=tuple(e["depends_on"]), conflicts_with=tuple(e["conflicts_with"])
            ) for e in entries
        )
    except (OSError, ValueError, TypeError, KeyError) as exc:
        if isinstance(exc, ModuleSelectionError):
            raise
        raise ModuleSelectionError(f"invalid module manifest: {exc}") from exc
    # Type-check every id before hashing it: a non-string id must fail closed, not raise TypeError.
    if any(not isinstance(b.id, str) or not _ID.fullmatch(b.id) for b in blocks):
        raise ModuleSelectionError("invalid module id")
    if any(not all(isinstance(x, str) for x in (*b.applies_to, *b.depends_on, *b.conflicts_with))
           for b in blocks):
        raise ModuleSelectionError("operations, dependencies and conflicts must be lists of strings")
    ids = [b.id for b in blocks]
    if len(ids) != len(set(ids)):
        raise ModuleSelectionError("duplicate module ids")
    by_id = {b.id: b for b in blocks}
    for b in blocks:
        if not isinstance(b.text, str) or not b.text.strip():
            raise ModuleSelectionError(f"{b.id}: empty text")
        if not isinstance(b.source, str) or not b.source.strip():
            raise ModuleSelectionError(f"{b.id}: missing provenance")
        if type(b.mandatory) is not bool or type(b.priority) is not int:
            raise ModuleSelectionError(f"{b.id}: invalid mandatory/priority fields")
        if not b.applies_to or any(op not in MODEL_OPERATIONS for op in b.applies_to):
            raise ModuleSelectionError(f"{b.id}: invalid operations")
        if len(b.applies_to) != len(set(b.applies_to)):
            raise ModuleSelectionError(f"{b.id}: duplicate operation")
        if len(b.depends_on) != len(set(b.depends_on)) or len(b.conflicts_with) != len(set(b.conflicts_with)):
            raise ModuleSelectionError(f"{b.id}: duplicate dependency/conflict")
        for dep in b.depends_on:
            if dep not in by_id or dep == b.id:
                raise ModuleSelectionError(f"{b.id}: unknown/self dependency {dep}")
            if not set(b.applies_to).issubset(by_id[dep].applies_to):
                raise ModuleSelectionError(f"{b.id}: dependency {dep} does not apply to every operation")
        for conflict in b.conflicts_with:
            if conflict not in by_id or conflict == b.id:
                raise ModuleSelectionError(f"{b.id}: unknown/self conflict {conflict}")
            if b.id not in by_id[conflict].conflicts_with:
                raise ModuleSelectionError(f"{b.id}: asymmetric conflict {conflict}")
    visiting, visited = set(), set()

    def visit(name: str) -> None:
        if name in visiting:
            raise ModuleSelectionError(f"dependency cycle involving {name}")
        if name not in visited:
            visiting.add(name)
            for dep in by_id[name].depends_on:
                visit(dep)
            visiting.remove(name)
            visited.add(name)

    for name in by_id:
        visit(name)
    return Manifest(data["version"], hashlib.sha256(raw).hexdigest(), blocks)


def select_modules(
    operation: str, *, requested: Iterable[str] = (), module_byte_limit: int = 1024,
    manifest: Manifest | None = None
) -> Selection:
    """Mandatory closure first, then prioritized requested closures.

    An optional block that would conflict or exceed the byte cap is omitted
    with an explicit reason. An unavailable mandatory block fails closed.
    """
    if operation not in MODEL_OPERATIONS:
        raise ModuleSelectionError(f"not a model operation: {operation}")
    if type(module_byte_limit) is not int or module_byte_limit <= 0:
        raise ModuleSelectionError("module_byte_limit must be a positive integer")
    registry = manifest if manifest is not None else load_manifest()
    by_id = registry.by_id()
    requests = tuple(requested)
    if any(not isinstance(name, str) or name not in by_id for name in requests):
        raise ModuleSelectionError("unknown requested module")
    if any(operation not in by_id[name].applies_to for name in requests):
        raise ModuleSelectionError("module requested for an incompatible operation")

    selected: dict[str, Block] = {}
    reasons: dict[str, str] = {}

    def closure(name: str, pending: dict[str, Block]) -> None:
        if name not in pending:
            for dep in by_id[name].depends_on:
                closure(dep, pending)
            pending[name] = by_id[name]

    def add(name: str, mandatory: bool) -> None:
        pending: dict[str, Block] = {}
        closure(name, pending)
        union = {**selected, **pending}
        conflict = next(
            ((a, other) for a, block in union.items() for other in block.conflicts_with if other in union),
            None
        )
        if conflict:
            if mandatory:
                raise ModuleSelectionError(f"mandatory modules conflict: {conflict}")
            reasons[name] = f"conflict:{conflict[0]}:{conflict[1]}"
            return
        size = sum(len(b.text.encode("utf-8")) for b in union.values())
        if size > module_byte_limit:
            if mandatory:
                raise ModuleSelectionError("mandatory module overflow (no model invocation)")
            reasons[name] = "optional_module_byte_overflow"
            return
        selected.update(pending)

    for b in sorted(registry.blocks, key=lambda x: x.id):
        if b.mandatory and operation in b.applies_to:
            add(b.id, mandatory=True)
    for name in sorted(set(requests), key=lambda k: (-by_id[k].priority, k)):
        add(name, mandatory=False)

    for b in registry.blocks:
        if b.id not in selected and b.id not in reasons:
            reasons[b.id] = ("different_operation" if operation not in b.applies_to else "not_requested")
    used = sum(len(b.text.encode("utf-8")) for b in selected.values())
    return Selection(operation, registry.version, registry.sha256, tuple(selected.values()),
                     tuple((b.id, reasons[b.id]) for b in registry.blocks if b.id in reasons),
                     used, module_byte_limit)
