"""Public Actions summary. Emit only static labels, enumerations and validated numbers."""
import json
import math
import sys
from collections import Counter
from pathlib import Path

from .live_smoke import CONFIGS, HOST_TERMINALS
from .provider import REAL_SOURCE
from .incident_env import TOOLS_BY_ID


def number(value):
    return value if type(value) in (float, int) and math.isfinite(value) and value >= 0 else None


def choice(value, allowed):
    return value if value in allowed else "unknown"


def summarize(report):
    if report["source"] != REAL_SOURCE:
        raise ValueError("Expected a real-provider ledger")
    rows = []
    for framework, architecture in CONFIGS:
        row = {"framework": framework, "architecture": architecture, "verdict": "INCONCLUSIVE"}
        rows.append(row)
        rec = next((r for r in report["configs"] if (r["framework"], r["architecture"]) ==
                    (framework, architecture)), None)
        if rec is None:
            continue
        requests = rec["provider_requests"]
        outcomes = rec.get("typed_outcomes", [])
        proposals = [o for o in outcomes if o["kind"] == "tool_proposal"]
        observed = rec.get("policy_observed_outcome_ids", [])
        adopted = rec.get("adopted_proposal_ids", [])
        usage = [r["usage"] for r in requests if r["usage"]]
        status = rec.get("termination", {}).get("status")
        tool_receipts = [(choice(t["tool"], TOOLS_BY_ID),
                          choice(t["status"], ("executed", "rejected", "held_for_approval", "error")))
                         for t in rec.get("tool_calls", [])]
        error = rec.get("error") or ""
        categories = ("refusal", "timeout", "connection error", "invalid structured output",
                      "incomplete response", "model behavior error", "framework step limit reached",
                      "provider error", "unclassified failure", "run halted", "interrupted")
        row.update(
            verdict=choice(rec["verdict"], ("PASS", "FAIL", "INCONCLUSIVE"))
            if rec["verdict"] != "INTERRUPTED" else "INCONCLUSIVE",
            admitted_requests=len(requests),
            http_status=[number(r["status"]) for r in requests],
            responses_with_output=sum(bool(r["response"].get("output")) for r in requests),
            usage_records=len(usage),
            reported_tokens={k: sum(number(u[k]) for u in usage if k in u)
                             for k in ("input_tokens", "output_tokens")} if usage else None,
            estimated_usd=number(rec.get("reported_cost_usd")) if usage else None,
            reserved_usd=number(rec.get("spend_bound_usd")),
            termination=choice(status, HOST_TERMINALS | {"completed (SDK final_output)",
                               "completed (FunctionAgent response)", "error"}),
            failure=next((c for c in categories if error.startswith(c)), "other" if error else None),
            writes_executed=number(rec.get("writes_executed")),
            host_receipts=tool_receipts,
            outcomes=dict(Counter(choice(o["kind"], ("answer_candidate", "tool_proposal",
                                  "needs_evidence", "invalid")) for o in outcomes)),
            outcomes_seen_by_policy=sum(o["id"] in observed for o in outcomes),
            proposals_adopted=sum(o["id"] in adopted for o in proposals),
            proposals_seen_but_unadopted=sum(o["id"] in observed and o["id"] not in adopted for o in proposals),
            failed_or_inconclusive_checks=[i for i, c in enumerate(rec.get("checks", []), 1)
                                           if c["result"] in ("fail", "inconclusive")],
        )
    return rows


if __name__ == "__main__":
    print("```json")
    print(json.dumps(summarize(json.loads(Path(sys.argv[1]).read_text())), indent=2))
    print("```")
