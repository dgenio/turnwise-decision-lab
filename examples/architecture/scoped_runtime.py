"""Opt-in #55 context assembly on the existing Turnwise host/policy loop.

No changes to the canonical example's default packets or to historical studies.
The same host still validates tools, referents, approvals and terminal outcomes.
Instruction blocks are sent as packet data (not privileged system messages).
"""
from __future__ import annotations

from collections.abc import Callable

from .context_modules import Manifest, ModuleSelectionError, Selection, load_manifest, select_modules
from .turnwise_core import Decision, MODEL_OPS, Op, TurnwiseRuntime


def default_requested_modules(d: Decision) -> tuple[str, ...]:
    """Use the NEXT model operation, not the conversation's broad topic."""
    if d.op is Op.CALL_HEAVY:
        return ("investigate-cause",)
    if d.op is Op.CALL_LIGHT and d.may_propose:
        return ("extract-arguments",)
    if d.op is Op.CALL_LIGHT:
        return ("summarize-evidence",)
    return ()


class ScopedContextRuntime(TurnwiseRuntime):
    """Narrow research adapter; not a replacement agent framework."""

    def __init__(self, *args, module_byte_limit: int = 1024,
                 requested_modules: Callable[[Decision], tuple[str, ...]] = default_requested_modules,
                 manifest: Manifest | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        # Loaded and validated once: validation and packet assembly see the same registry.
        self.manifest = manifest if manifest is not None else load_manifest()
        self.module_byte_limit = module_byte_limit
        self.requested_modules = requested_modules
        self.module_audits: list[dict] = []

    def _select(self, d: Decision) -> Selection:
        return select_modules(
            d.op.value, requested=self.requested_modules(d), module_byte_limit=self.module_byte_limit,
            manifest=self.manifest)

    def host_validates(self, d, step: int) -> tuple[bool, str]:
        ok, reason = super().host_validates(d, step)
        if ok and isinstance(d, Decision) and d.op in MODEL_OPS:
            try:
                self._select(d)
            except ModuleSelectionError as exc:
                return False, f"pre-authored module selection rejected: {exc}"
        return ok, reason

    def _packet(self, d: Decision, tier: str) -> dict:
        packet = super()._packet(d, tier)
        selection = self._select(d)
        packet["instruction_modules"] = [
            {"id": b.id, "text": b.text, "sha256": b.sha256} for b in selection.included
        ]
        audit = selection.audit()
        included_receipts = set(d.context)
        included_tools = set(d.may_propose)
        audit["evidence_included"] = sorted(included_receipts)
        audit["evidence_excluded"] = [
            {"id": r.id, "reason": "not_selected_by_policy"}
            for r in self.host.receipts if r.executed and r.id not in included_receipts
        ]
        audit["tools_visible_for_proposal"] = sorted(included_tools)
        audit["tools_not_visible_for_proposal"] = [
            {"id": t.id, "reason": "not_selected_for_next_operation"}
            for t in self.host.tools if t.id not in included_tools
        ]
        self.module_audits.append(audit)
        return packet
