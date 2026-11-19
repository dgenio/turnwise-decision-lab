"""Host-owned final action status for opt-in v0.8 results.

The model's text may be shown for read-only tasks, but it is *never* the
authority for whether an action was requested, approved or executed.
This is a prospective adapter; frozen v0.7 traces are not rewritten.
"""
from __future__ import annotations

from ..agent.host import CATALOG_BY_ID
from ..v07.evidence import type_claim
from .guard import user_history


def finalize(trace: dict, message: str, conversation: list[dict] | None) -> dict:
    """Return the trace with a receipt-backed action status.

    For action-bearing turns, replace all generated action prose with a host
    status; do not attempt brittle verb-based completion detection. Read-only
    model text is not an action receipt either; denied model writes are visible.
    """
    claim = type_claim(message, user_history(conversation))
    observations = trace.get("observations") or []
    write_obs = [o for o in observations if (CATALOG_BY_ID.get(o.get("target") or "") or None)
                 and CATALOG_BY_ID[o["target"]].side_effect]
    approved = [o for o in write_obs if o.get("status") == "approval_required"]
    denied = [o for o in write_obs if o.get("status") == "rejected"]
    executed = trace.get("totals", {}).get("writes_executed", 0)
    final = dict(trace.get("final") or {})
    final["action_receipts"] = [{
        "target": o["target"], "arguments": o.get("arguments") or {},
        "status": o.get("status"), "reason": o.get("reason", "")
    } for o in write_obs]
    if executed:
        # Should be unreachable with the synthetic host. Never hide it.
        final.update(kind="abstain", action_status="executed_requires_audit",
                     text="A write execution receipt was observed. Independent host audit is required.",
                     by="v08 host", reason="unexpected write execution")
    elif approved:
        statuses = "; ".join(
            f"{o['target']}({', '.join(f'{k}={v}' for k, v in sorted(o.get('arguments', {}).items()))})"
            for o in approved
        )
        final.update(kind="approval_required", action_status="held_for_approval",
                     text=f"Human approval is required for: {statuses}. Nothing was executed.",
                     by="v08 host receipts", reason="typed agent action approved for human review only")
    elif claim.action:
        final.update(kind="clarify", action_status="requested_but_not_approved",
                     text="No action was executed or submitted for approval. The requested action or target could not "
                          "be independently validated; please clarify the target or retry.",
                     by="v08 host receipts", reason="requested action has no matching host approval receipt")
    elif denied:
        final.update(kind="abstain", action_status="unrequested_write_rejected",
                     text="The model proposed a write action that the host rejected. No write was executed. "
                          "The generated reply was withheld for independent review.",
                     by="v08 host receipts", reason="unrequested write proposal rejected")
    else:
        final.setdefault("action_status", "not_requested")
    trace["final"] = final
    return trace
