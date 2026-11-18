"""The exit gate: the host checks a turn at its exit, not at every step.

A controller (rules, a learned head, an LLM agent, anything) may propose to end
the turn: show verified data, generate an answer, ask a clarifying question.
Before that happens the gate asks three questions of trusted state only:

1. **Sufficiency.** Does the evidence contract for this kind of request hold?
   If not, the gate names the exact missing calls. The host runs them without
   asking any model, and the controller gets the turn back.
2. **Action latch.** Did the user ask for a side effect that has not become an
   approval request? Then the turn cannot end as an answer.
3. **Grounding** (after generation). Does the reply state a value that appears
   in no receipt, or claim a side effect was performed? Then the generated text
   is withheld and the host's findings are returned instead, with a notice.

The gate never authorises anything and never reads a gold label. It is bounded:
at most ``max_interventions`` rounds per turn, after which it lets the turn end
and says so in the trace.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re

from ..agent.render import render_facts
from .evidence import (CHANGE, GENERAL, ROLE_OF, SYMPTOM, Claim, Contract, Requirement, compile_contract, derive, missing, receipts,
                       render_findings, revise, services_in, type_claim)

ALLOW, ACQUIRE, HOLD, CLARIFY = "allow", "acquire", "hold", "clarify"
TERMINALS = ("finish", "answer", "clarify", "abstain")

ANSWER_CAUSAL = r"\b(?:caus\w+|because of|due to|result(?:ed)? (?:of|from)|led to|culprit|responsible for|root cause|triggered by|explains? the)\b"
SIDE_EFFECT_CLAIM = re.compile(
    r"\b(?:i(?:'ve| have)?|we(?:'ve| have)?|has been|have been|had been|was|were|is now|are now|been|successfully|already)\s+"
    r"(?:successfully |now |just |already )?(?:rolled back|reverted|paged|posted|published|restored)\b|"
    r"\b(?:rollback|page|status (?:update|post))\s+(?:was |has been |is |been )?(?:completed|complete|performed|executed|done|initiated|sent|successful|live)\b")
NEGATED_CLAIM = re.compile(r"\b(?:not|never|no|nothing|hasn't|haven't|wasn't|weren't|isn't|cannot|can't|won't|without)\b[^.;!?\n]{0,40}$")
VALUE_PATTERNS = (("deploy id", r"\bd-\d+\b"), ("time", r"\b\d{1,2}:\d{2}\b"), ("percentage", r"\b\d+(?:\.\d+)?\s?%"),
                  ("duration", r"\b\d+(?:\.\d+)?\s?ms\b"), ("identifier", r"\b[a-z]+-(?:captain|primary|duty)-?\d*\b"))


@dataclass
class Verdict:
    action: str
    calls: list[tuple[str, dict]] = field(default_factory=list)
    reason: str = ""
    contract: dict = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    unavailable: list[str] = field(default_factory=list)
    source: str = "request"  # request | answer | none

    def as_json(self) -> dict:
        return {"action": self.action, "calls": [{"target": c, "arguments": a} for c, a in self.calls], "reason": self.reason,
                "missing": self.missing, "unavailable": self.unavailable, "contract": self.contract, "source": self.source}


def values_in(text: str) -> set[tuple[str, str]]:
    out = set()
    for label, pat in VALUE_PATTERNS:
        for m in re.findall(pat, text.lower()):
            out.add((label, re.sub(r"\s+", "", m).lstrip("0") if label == "time" else re.sub(r"\s+", "", m)))
    return out


def side_effect_claims(text: str) -> list[str]:
    out = []
    for m in SIDE_EFFECT_CLAIM.finditer(text.lower()):
        before = text.lower()[max(0, m.start() - 60):m.start()]
        if NEGATED_CLAIM.search(before) or re.search(r"\b(?:if|once|after|before|until|when|should|would|could|to be|needs? to be|must be|can be)\b[^.;!?\n]{0,30}$", before):
            continue
        out.append(m.group(0))
    return out


class ExitGate:
    name = "exit-gate-v0.7"

    def __init__(self, *, sufficiency: bool = True, latch: bool = True, grounding: bool = True, override_clarify: bool = True,
                 max_interventions: int = 3, max_retries: int = 1):
        self.sufficiency, self.latch, self.grounding, self.override_clarify = sufficiency, latch, grounding, override_clarify
        self.max_interventions, self.max_retries = max_interventions, max_retries

    # ---------------------------------------------------------------- contract
    def contract(self, message: str, conversation: list[dict], observations) -> Contract:
        return revise(compile_contract(type_claim(message, conversation), message), observations)

    def _answer_contract(self, text: str, message: str, conversation, observations, claim: Claim) -> Contract | None:
        """For a request the lexicon could not type: derive the contract from what the reply itself claims."""
        have = receipts(observations)
        if claim.entity_source == "message" and len(claim.entities) == 1 and not any(k.endswith(":" + claim.entities[0]) for k in have) \
                and not re.search(GENERAL, message.lower()):
            e = claim.entities[0]
            return Contract(Claim("untyped", [e], "message", cues=["a reply about a named service with no receipt about it"]),
                            [Requirement("health", e, "a reply about a named service must rest on at least one receipt about that service")])
        if not re.search(ANSWER_CAUSAL, text.lower()):
            return None
        ents = [k.split(":", 1)[1] for k in have if not k.startswith("doc:")]
        named = [e for e in services_in(text) if e in ents] or ents
        if not named:
            return None
        e = max(set(named), key=named.count)
        roles = {ROLE_OF.get(k.split(":")[0]) for k in have if k.endswith(":" + e)}
        k = Contract(Claim("causal", [e], "answer", cues=["the reply attributes a cause"]))
        if SYMPTOM not in roles:
            k.requirements.append(Requirement("errors", e, "the reply attributes a cause but no symptom was observed (two-sided rule)"))
        if CHANGE not in roles:
            k.requirements.append(Requirement("deploys", e, "the reply attributes a cause but no change record was read (two-sided rule)"))
        return k if k.requirements else None

    # ------------------------------------------------------------------ review
    def review(self, *, message: str, conversation: list[dict], observations, terminal: str, text: str | None = None,
               interventions: int = 0) -> Verdict:
        """Decide whether a proposed exit may happen. ``terminal`` is finish | answer | clarify | abstain."""
        k = self.contract(message, conversation, observations)
        cj = k.as_json()
        if interventions >= self.max_interventions:
            return Verdict(ALLOW, reason="intervention budget spent; exit allowed and recorded", contract=cj)
        approvals = [o for o in observations if o.status == "approval_required"]
        if k.clarify:
            if terminal == "clarify":
                return Verdict(ALLOW, reason="clarification is the contract's own outcome", contract=cj)
            if self.latch and k.claim.action and not approvals:
                return Verdict(CLARIFY, reason=f"action request without a resolvable target ({k.clarify})", contract=cj)
            if self.sufficiency and terminal in ("answer", "finish") and not receipts(observations):
                return Verdict(CLARIFY, reason=f"reply without evidence to a request the host cannot resolve ({k.clarify})", contract=cj)
            return Verdict(ALLOW, reason="request not resolvable by the host; the controller gathered evidence, its exit stands",
                           contract=cj, source="none")
        if terminal == "clarify" and k.claim.type in ("untyped", "smalltalk", "record"):
            return Verdict(ALLOW, reason="no contract; controller's clarification stands", contract=cj, source="none")
        if terminal == "clarify" and not self.override_clarify:
            return Verdict(ALLOW, reason="clarify override disabled", contract=cj)
        todo, unavailable = missing(k, observations, message, self.max_retries) if self.sufficiency else ([], [])
        if terminal == "abstain":  # the turn is ending anyway (step limit, malformed call): only the latch can still act
            todo = []
        if not todo and self.sufficiency and text and k.claim.type == "untyped":
            ak = self._answer_contract(text, message, conversation, observations, k.claim)
            if ak is not None:
                t2, u2 = missing(ak, observations, message, self.max_retries)
                if t2:
                    return Verdict(ACQUIRE, [r.call(message, receipts(observations)) for r in t2], t2[0].why,
                                   ak.as_json(), [r.key for r in t2], [r.key for r in u2], "answer")
        if todo:
            return Verdict(ACQUIRE, [r.call(message, receipts(observations)) for r in todo],
                           f"{terminal} blocked: contract for a {k.claim.type} reply is not met", cj,
                           [r.key for r in todo], [r.key for r in unavailable])
        if self.latch and k.hold and not approvals:
            return Verdict(HOLD, [k.hold], "the user asked for a side effect; the turn cannot end without an approval request", cj,
                           unavailable=[r.key for r in unavailable])
        return Verdict(ALLOW, reason="contract met" if k.requirements or k.hold else "no contract applies", contract=cj,
                       unavailable=[r.key for r in unavailable], source="request" if (k.requirements or k.hold) else "none")

    # --------------------------------------------------------------- grounding
    def ground(self, text: str, *, message: str, conversation: list[dict], observations, host_facts: dict) -> dict:
        """Check a generated reply against receipts. Returns what was found; ``replacement`` is set when the text is withheld."""
        k = self.contract(message, conversation, observations)
        if not self.grounding:
            return {"checked": False, "ok": True, "violations": []}
        violations = [{"kind": "claims_side_effect", "text": c} for c in side_effect_claims(text)]
        have = receipts(observations)
        evidence_bearing = bool(have) and k.claim.type in ("lookup", "causal", "verification", "action", "untyped")
        if evidence_bearing:
            allowed_text = " ".join([render_facts(have), " ".join(d["text"] for d in derive(observations, k.claim)), message,
                                     " ".join(m.get("content", "") for m in conversation or []),
                                     " ".join(f"{a} {b}" for a, b in host_facts.items())])
            allowed = values_in(allowed_text) | {("time", v[11:16].lstrip("0")) for v in host_facts.values() if re.match(r"\d{4}-\d\d-\d\dT", str(v))}
            for label, value in sorted(values_in(text) - allowed):
                violations.append({"kind": "ungrounded_value", "text": f"{label} {value}"})
        out = {"checked": True, "ok": not violations, "violations": violations, "evidence_bearing": evidence_bearing}
        if violations:
            _, unavailable = missing(k, observations, message, self.max_retries)
            shown = "; ".join(v["text"] for v in violations[:4])
            notice = (f"[The generated summary was withheld by the host: it "
                      f"{'claimed a side effect that was not executed' if any(v['kind'] == 'claims_side_effect' for v in violations) else 'stated values that are in no tool receipt'}"
                      f" ({shown}).]")
            body = render_findings(k.claim, derive(observations, k.claim), unavailable) if have else \
                "No evidence was gathered for this request, so there is nothing verified to report."
            out["replacement"] = f"{notice}\n{body}"
        return out
