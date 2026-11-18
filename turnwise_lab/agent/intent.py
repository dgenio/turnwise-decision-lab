"""Host-owned user write intent (#12/#13): mentioning a service is not requesting a write.

An approval hold asks a person to authorise a side effect. The host creates one only
for an action that the *user* positively requested in the current turn. Model output,
tool output, controller hints and assistant turns never count as a request. Earlier
user turns can only supply the referent of a pronoun ("roll it back").

Scope and limits, stated plainly:

* Bounded and lexical. It covers this synthetic world's three write capabilities
  in English. It is not general language understanding.
* Fail-closed precision. Negation, retraction, advice, hypotheticals, conditions,
  drafting, questions, quotations, statements, ambiguous referents and unknown
  wording never produce a hold. A conditional or ambiguous request is recorded as
  ``needs_clarification`` and the host asks; it does not guess.
* Limited recall. A request phrased in a way these patterns do not recognise is
  not held. The proposal is rejected and recorded, so it is visible in the trace,
  but the user is not asked about it.
* Contamination note. The indirect phrasings ("put checkout back to how it was",
  "get someone ... on the line") were written after reading the frozen v0.6 cases
  H18/H19. Passing those cases is regression evidence only. Recall on new wording
  is a #9 measurement.

Nothing here reads benchmark gold, expected routes or recorded traces.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Sequence

SCHEMA = "turnwise.write-intent/1"
WRITE_CAPABILITIES = ("rollback_deployment", "page_oncall", "post_status_update")

# Initial statuses the host assigns from the user's words. Lifecycle statuses
# (held_for_approval, needs_confirmation, not_attempted) are set later by the
# host from its own receipts. ``executed`` is unreachable in this host.
REQUESTED, NEEDS_CLARIFICATION, DECLINED = "requested", "needs_clarification", "declined_by_user"

_F = re.I
# Phrases that name a write capability. Matching one is necessary for a request,
# never sufficient: the clause's form decides (see _classify).
CUES = {
    "rollback_deployment": [
        r"\broll(?:s|ed|ing)?\s+(?:\S+\s+){0,3}?back\b",
        r"\brollbacks?\b",
        r"\brevert(?:s|ed|ing)?\b",
        r"\bundo\b",
        r"\bput\s+(?:\S+\s+){0,2}?back\s+(?:to|the\s+way|how|as)\b",
        r"\b(?:restore|bring\s+back|go\s+back\s+to|return\s+to)\b[^.;!?]{0,40}\b(?:previous|prior|earlier|last\s+good|old)\b",
        r"\bmake\b[^.;!?]{0,30}\b(?:previous|prior|old)\b[^.;!?]{0,30}\b(?:live|active|current)\b",
    ],
    "page_oncall": [
        r"\bpag(?:e|ing)\s+(?:the|an?|our|their|someone|somebody|anyone|anybody|them|him|her|on.?call|checkout|payments?|search|auth)\b",
        r"\b(?:get|grab|bring)\s+(?:someone|somebody|an?\s+engineer|the\s+on.?call)\b[^.;!?]{0,40}"
        r"\b(?:on\s+(?:the\s+)?(?:line|call|phone|bridge)|involved|in\s+here)\b",
        r"\b(?:wake\s+up|call\s+out|ping|alert|escalate\s+to|get\s+hold\s+of)\b[^.;!?]{0,20}"
        r"\b(?:on.?call|engineer|someone|somebody)\b",
    ],
    "post_status_update": [
        r"\b(?:post|publish|announce|put\s+up|push)\b[^.;!?:]{0,40}\bstatus\b",
        r"\bupdate\s+(?:the\s+)?(?:public\s+)?status\s+page\b",
        r"\b(?:tell|inform|let)\s+(?:the\s+)?(?:customers|users|public)\b",
    ],
}
_CUE_RE = {cap: [re.compile(p, _F) for p in pats] for cap, pats in CUES.items()}

NEGATION = re.compile(r"\b(?:don'?t|dont|do\s+not|does\s+not|doesn'?t|never|no|not|without|instead\s+of|rather\s+than|"
                      r"hold\s+off|stop|avoid|refrain|cancel|shouldn'?t|mustn'?t|won'?t|can'?t|cannot)\b", _F)
# Asking about, planning or describing an action is not asking for it.
INFO_OR_ADVICE = re.compile(r"\b(?:whether|should\s+(?:we|i)|shall\s+(?:we|i)|would\s+it|is\s+it\s+(?:safe|ok|okay|wise|possible)|"
                            r"what\s+if|tell\s+me|explain|describe|show\s+me|want\s+to\s+know|wondering|policy|procedure|"
                            r"runbook|playbook|steps?\s+(?:to|for)|plan\s+(?:to|for)|risks?|consequences?|"
                            r"thinking\s+(?:of|about)|consider(?:ing)?|recommend\w*|suggest\w*|advice|advise)\b", _F)
QUESTION_START = re.compile(r"^\W*(?:why|what|how|when|where|which|who|whose|is|are|was|were|does|did|do|has|have|had|"
                            r"should|shall|would|might|may|will\s+it|can\s+i|could\s+it)\b", _F)
POLITE_REQUEST = re.compile(r"\b(?:can|could|would|will)\s+(?:you|u|ya)\b|\bplease\b|\bpls\b|\bplz\b", _F)
# Only an imperative (base) verb form can ask for an action: "Rolling back checkout is off the table" or
# "we already reverted checkout" describe or discuss it. "rollback" is a noun unless it takes a direct object.
NOT_IMPERATIVE = re.compile(r"^(?:rolling|rolled|rolls|reverting|reverted|reverts|undoing|undid|undone|restoring|restored|"
                            r"paging|paged|pages|posting|posted|posts|publishing|published|announcing|announced|"
                            r"escalating|escalated|waking|woke|alerting|alerted|pinging|pinged|telling|told|"
                            r"updating|updated|putting|bringing|brought|making|made|going|went|returning|returned)$", _F)
ROLLBACK_OBJECT = re.compile(r"^\s*(?:it|that|this|them|the|a|everything|to|d-\d+|now|please|checkout|payments?|search|auth|"
                             r"login|authentication)\b", _F)
# A sentence that opens with a prohibition governs every action in it ("Do not, under any circumstances, ...").
SENTENCE_NEGATION = re.compile(r"^\W*(?:please\s+)?(?:don'?t|dont|do\s+not|never|under\s+no\s+circumstances)\b", _F)
CAN_WE = re.compile(r"\b(?:can|could)\s+we\b", _F)
CONDITIONAL = re.compile(r"\b(?:if|unless|in\s+case|once|as\s+soon\s+as|provided|assuming|only\s+when)\b", _F)
DRAFTING = re.compile(r"\b(?:draft\w*|write\s+up|prepare|compose|word(?:ing)?\s+for)\b", _F)
DIRECTIVE = re.compile(r"\b(?:i\s+(?:want|need|would\s+like)\s+(?:you\s+)?to|i'?d\s+like\s+(?:you\s+)?to|we\s+(?:need|have)\s+to|"
                       r"let'?s|go\s+ahead|you\s+(?:need|have|should)\s+to|make\s+sure\s+(?:to|you))\b", _F)
FILLER = re.compile(r"^(?:\W*\b(?:ok(?:ay)?|so|now|then|please|pls|plz|just|also|and|go\s+ahead\s+and|right|yes|yeah|hey|"
                    r"quickly|asap|urgently|immediately|alright)\b)*\W*$", _F)
RETRACTION = re.compile(r"^\W*(?:actually|wait|no\b|nope|hold\s+on|scratch\s+that|never\s*mind|nvm|cancel\s+(?:that|it)|"
                        r"forget\s+(?:it|that)|on\s+second\s+thought)", _F)
RETRACTION_NEGATIVE = re.compile(r"\b(?:don'?t|do\s+not|never\s*mind|nvm|cancel\s+(?:that|it)|scratch\s+that|"
                                 r"forget\s+(?:it|that)|hold\s+off|no\s+need)\b", _F)
PRONOUN = re.compile(r"\b(?:it|that|this|them|those|same|the\s+service)\b", _F)
EXCLUDE_BEFORE = re.compile(r"\b(?:not|except|but\s+not|other\s+than|leave|keep|besides)\s*$", _F)
ELLIPSIS_FILLER = re.compile(r"^(?:\W*\b(?:too|as\s+well|also|and|plus|the\s+same\s+for|same\s+for)\b)*\W*$", _F)
CLAUSE_SPLIT = re.compile(r"\s*,?\s*\b(?:and\s+then|and|then|but|also|plus)\b\s*", _F)
SENTENCE_SPLIT = re.compile(r"(?<=[.!?;])\s+|\n+")
QUOTED = re.compile(r"\"[^\"]*\"|“[^”]*”|'[^']{3,}'")


def _services(text: str) -> list[str]:
    from .providers import named_services  # lazy: providers imports the host, which imports this module
    return named_services(text)


def _normalise_body(text: str) -> str:
    text = " ".join(text.split())
    for a, b in (('"', '"'), ("“", "”"), ("'", "'")):
        if len(text) >= 2 and text.startswith(a) and text.endswith(b):
            text = text[1:-1].strip()
    return text


def literal_status_body(message: str) -> tuple[str | None, int | None]:
    """The literal status-page text the user supplied, and where it starts.

    After a post cue, text following a colon is literal data through the end of the
    request; otherwise a quoted string after the cue is. Literal data is never parsed
    for further intents (``post status: rolling back checkout`` requests one post).
    """
    for pat in _CUE_RE["post_status_update"]:
        m = pat.search(message)
        if not m:
            continue
        rest = message[m.end():]
        sentence_end = re.search(r"[.!?;\n]", rest)
        colon = rest.find(":")
        if colon >= 0 and (sentence_end is None or colon < sentence_end.start()):
            start = m.end() + colon + 1
            return _normalise_body(message[start:]) or None, start
        q = QUOTED.search(rest)
        if q and (sentence_end is None or q.start() < sentence_end.start() + 1):
            return _normalise_body(q.group(0)) or None, m.end() + q.start()
    return None, None


@dataclass(frozen=True)
class _Cue:
    capability: str
    sentence: int
    clause: int
    start: int  # offset inside the clause
    end: int


def _cues_in(text: str) -> list[tuple[str, int, int]]:
    found = []
    for cap, pats in _CUE_RE.items():
        for pat in pats:
            for m in pat.finditer(text):
                if not any(c == cap and s <= m.start() < e for c, s, e in found):
                    found.append((cap, m.start(), m.end()))
    return sorted(found, key=lambda x: x[1])


def _within_quotes(text: str, pos: int) -> bool:
    return any(q.start() < pos < q.end() for q in QUOTED.finditer(text))


def _classify(sentence: str, clause: str, cue_start: int, cue_end: int, sentence_cue_start: int,
              first_cue: bool) -> tuple[str, str]:
    """(status, basis) for one cue occurrence. Order matters: the most conservative reading wins."""
    first_word = (re.findall(r"[a-z]+", clause[cue_start:cue_end].lower()) or [""])[0]
    before_in_sentence = re.sub(r"\b(?:if|whether)\s+not\b", " ", sentence[:sentence_cue_start], flags=_F)
    # A negation governs the cue when nothing but a few words separate them inside one clause
    # ("do not roll back", "under no circumstances should checkout be rolled back").
    scope = re.split(r"[,;:]|\b(?:and|but|then)\b", before_in_sentence, flags=_F)[-1]
    if NEGATION.search(" ".join(scope.split()[-6:])) or (first_cue and SENTENCE_NEGATION.search(before_in_sentence)):
        return DECLINED, "negated"
    if _within_quotes(clause, cue_start):
        return "not_requested", "quoted"
    if NOT_IMPERATIVE.match(first_word):
        return "not_requested", "not_imperative_form"
    if first_word in ("rollback", "rollbacks") and not ROLLBACK_OBJECT.match(clause[cue_end:]):
        return "not_requested", "noun_mention"
    if DRAFTING.search(clause):
        return "not_requested", "drafting"
    if CAN_WE.search(clause[:cue_start]) and not INFO_OR_ADVICE.search(clause):
        return NEEDS_CLARIFICATION, "ambiguous_can_we"
    if INFO_OR_ADVICE.search(clause) or (QUESTION_START.search(clause) and not POLITE_REQUEST.search(clause)):
        return "not_requested", "question_or_advice"
    # The form of the request is read from the last boundary before the action ("checkout is on fire, roll it back";
    # "IC approved already: roll back checkout").
    prefix = re.split(r"[,:;]|\s[-\u2013\u2014]\s|\)", clause[:cue_start])[-1]
    if sentence.rstrip().endswith("?") and not POLITE_REQUEST.search(clause) and not FILLER.match(prefix):
        return "not_requested", "question_or_advice"
    if NEGATION.search(before_in_sentence):
        return NEEDS_CLARIFICATION, "negation_elsewhere_in_sentence"
    if CONDITIONAL.search(clause):
        return NEEDS_CLARIFICATION, "conditional"
    if FILLER.match(prefix) or POLITE_REQUEST.search(prefix) or DIRECTIVE.search(prefix):
        if sentence.rstrip().endswith("?") and not POLITE_REQUEST.search(clause):
            return NEEDS_CLARIFICATION, "bare_question_form"
        return REQUESTED, "polite_request" if POLITE_REQUEST.search(prefix) else "directive"
    return "not_requested", "statement"


def analyse(message: str, conversation: Sequence[dict] = ()) -> dict:
    """Write intents the user expressed in ``message`` (host-owned, gold-free, deterministic).

    Returns ``{"schema", "intents": [...], "mentions": [...]}``. ``intents`` holds
    requested, needs-clarification and declined actions. ``mentions`` records action
    words that were not requests (questions, advice, statements...), for audit only.
    """
    message = message or ""
    body, body_start = literal_status_body(message)
    scan = message if body_start is None else message[:body_start]
    sentences = [s for s in SENTENCE_SPLIT.split(scan) if s.strip()]
    earlier_user = [str(m.get("content", "")) for m in conversation or () if m.get("role") == "user"]

    intents: list[dict] = []
    mentions: list[dict] = []
    services_seen: list[list[str]] = []  # per clause, in order, for in-message referents
    last_cue_sentence = -1

    def referent(clause_text: str) -> tuple[list[str] | None, str]:
        named, excluded = [], []
        for s in _services(clause_text):
            idx = clause_text.lower().find(s)
            (excluded if idx >= 0 and EXCLUDE_BEFORE.search(clause_text[:idx]) else named).append(s)
        if named:
            return named, "named_in_request"
        if excluded:  # "everything except payments": never fall back to an earlier referent
            return None, "excluded_referent"
        for prior in reversed(services_seen):
            if prior:
                return (prior if len(prior) == 1 else None), ("earlier_in_message" if len(prior) == 1 else "ambiguous_in_message")
        for turn in reversed(earlier_user):
            found = _services(turn)
            if found:
                return (found if len(found) == 1 else None), ("earlier_user_turn" if len(found) == 1 else "ambiguous_earlier_user_turn")
        return None, "unresolved"

    for si, sentence in enumerate(sentences):
        clauses = [c for c in CLAUSE_SPLIT.split(sentence) if c is not None]
        sentence_cues = _cues_in(sentence)
        if not sentence_cues and last_cue_sentence >= 0 and RETRACTION.search(sentence):
            negative = bool(RETRACTION_NEGATIVE.search(sentence))
            for e in intents:
                if e["status"] in (REQUESTED, NEEDS_CLARIFICATION):
                    e["status"], e["basis"] = (DECLINED, "retracted") if negative else (NEEDS_CLARIFICATION, "retraction_ambiguous")
        offset = 0
        previous: dict | None = None  # cue state of the previous clause, for ellipsis ("roll back auth and checkout")
        for ci, clause in enumerate(clauses):
            pos = sentence.find(clause, offset)
            pos = offset if pos < 0 else pos
            offset = pos + len(clause)
            cues = _cues_in(clause)
            if not cues and previous and _services(clause) and ELLIPSIS_FILLER.match(re.sub(
                    r"\b(?:" + "|".join(map(re.escape, _services(clause))) + r")\b", "", clause, flags=_F)):
                cues_for_clause = [(previous["capability"], previous["status"], previous["basis"], 0, len(clause))]
            else:
                cues_for_clause = []
                for cap, start, end in cues:
                    first = not any(s0 < pos + start for _, s0, _ in sentence_cues)
                    status, basis = _classify(sentence, clause, start, end, pos + start, first)
                    cues_for_clause.append((cap, status, basis, start, end))
            for cap, status, basis, start, end in cues_for_clause:
                last_cue_sentence = si
                evidence = clause.strip()[:160]
                if status == "not_requested":
                    mentions.append({"capability": cap, "status": "not_requested", "basis": basis, "evidence": evidence})
                    previous = {"capability": cap, "status": status, "basis": basis}
                    continue
                if cap == "post_status_update":
                    args = {"message": body} if body else {"message": None}
                    entry_status, entry_basis = status, basis
                    if body and len(body) > 300:
                        entry_status, entry_basis = NEEDS_CLARIFICATION if status == REQUESTED else status, "status_text_too_long"
                    entry = {"capability": cap, "arguments": args, "status": entry_status, "basis": entry_basis,
                             "referent": "user_literal_text" if body else "to_be_drafted", "evidence": evidence}
                    if entry not in intents:
                        intents.append(entry)
                else:
                    targets, how = referent(clause)
                    if not targets:
                        entry = {"capability": cap, "arguments": None,
                                 "status": DECLINED if status == DECLINED else NEEDS_CLARIFICATION,
                                 "basis": basis if status == DECLINED else how, "referent": how, "evidence": evidence}
                        if entry not in intents:
                            intents.append(entry)
                    for svc in targets or []:
                        entry = {"capability": cap, "arguments": {"service": svc}, "status": status, "basis": basis,
                                 "referent": how, "evidence": evidence}
                        if entry not in intents:
                            intents.append(entry)
                previous = {"capability": cap, "status": status, "basis": basis}
            if not cues_for_clause:
                previous = None
            services_seen.append(_services(clause))
    for e in intents:
        e["source"] = "user_message"
    return {"schema": SCHEMA, "intents": intents, "mentions": mentions}


def _args_match(entry: dict, arguments: dict) -> bool:
    want = entry["arguments"]
    if want is None:
        return False
    if "service" in want:
        return arguments == want
    if "message" in want:
        got = arguments.get("message")
        if not isinstance(got, str) or not 0 < len(got) <= 300:
            return False
        return want["message"] is None or _normalise_body(got) == want["message"]
    return False


def resolve_write(capability: str, arguments: dict, analysis: dict) -> dict:
    """Does a proposed write match an action the user requested? Never grants anything else."""
    entries = [(i, e) for i, e in enumerate(analysis["intents"]) if e["capability"] == capability]
    for i, e in entries:
        if e["status"] == REQUESTED and _args_match(e, arguments):
            drafted = "message" in e["arguments"] and e["arguments"]["message"] is None
            return {"ok": True, "code": "requested", "intent_index": i,
                    "reason": f"the user requested {capability} ({e['basis']}; referent: {e['referent']})",
                    **({"message_source": "drafted_by_proposer"} if drafted else {})}
    proposed_service = arguments.get("service")
    for i, e in entries:
        if e["status"] == DECLINED and (e["arguments"] is None or "message" in (e["arguments"] or {})
                                       or e["arguments"].get("service") == proposed_service):
            return {"ok": False, "code": "declined_by_user", "intent_index": i,
                    "reason": f"the user asked not to do this ({e['basis']}: {e['evidence']!r})"}
    for i, e in entries:
        if e["status"] == REQUESTED:
            code = "message_mismatch" if "message" in e["arguments"] else "referent_mismatch"
            return {"ok": False, "code": code, "intent_index": i,
                    "reason": f"the user requested {capability} with {e['arguments']}, not {arguments}"}
    for i, e in entries:
        if e["status"] == NEEDS_CLARIFICATION:
            return {"ok": False, "code": "unverified_request", "intent_index": i,
                    "reason": f"the host cannot verify this request ({e['basis']}); the user will be asked"}
    mentioned = [m for m in analysis["mentions"] if m["capability"] == capability]
    if mentioned:
        return {"ok": False, "code": "not_requested", "intent_index": None,
                "reason": f"the action was mentioned but not requested ({mentioned[0]['basis']})"}
    return {"ok": False, "code": "not_requested", "intent_index": None,
            "reason": "the user did not ask for this action in this turn; mentioning a service is not a request"}


# ----------------------------------------------------------------------------- generated-answer claims
# A generated reply must not say that a write happened: this host has no path that
# executes one, so any such claim is unsupported by a receipt (#13, the H10 mechanism).
CLAIMS = {
    "rollback_deployment": [
        r"\b(?:rolled|rolling)\s+(?:\S+\s+){0,3}?back\b", r"\breverted\b", r"\bundid\b|\bundone\b",
        r"\brollback\b[^.;!?]{0,60}\b(?:initiated|started|triggered|executed|performed|completed?|done|succeeded|"
        r"successful|underway|in\s+progress|finished|applied|carried\s+out)\b",
        r"\b(?:initiated|started|triggered|executed|performed|completed|kicked\s+off|carried\s+out|applied)\b"
        r"[^.;!?]{0,40}\b(?:rollback|roll\s*back|revert)\b",
        r"\brestored\b[^.;!?]{0,30}\b(?:previous|prior|earlier|last)\b",
    ],
    "page_oncall": [
        r"\bpaged\b",
        r"\b(?:notified|alerted|contacted|woke\s+up|called\s+out|escalated\s+to)\s+(?:the\s+)?(?:\S+\s+)?"
        r"(?:on.?call|engineer|team|owner)\b",
        r"\b(?:on.?call|engineer|team|owner)\b[^.;!?]{0,30}\b(?:has|have|had|was|were)\s+been\s+(?:notified|alerted|contacted|paged)\b",
    ],
    "post_status_update": [
        r"\b(?:posted|published|announced)\b",
        r"\bstatus\s+(?:page|update)\b[^.;!?]{0,40}\b(?:updated|is\s+now\s+live|went\s+out)\b",
        r"\bupdated\s+the\s+(?:public\s+)?status\s+page\b",
    ],
}
_CLAIM_RE = {cap: [re.compile(p, _F) for p in pats] for cap, pats in CLAIMS.items()}
_NOT_A_CLAIM = re.compile(r"(?:\b(?:not|no|never|nothing|without|neither|nor|will|would|could|can|should|may|might|once|if|"
                          r"after|until|pending|awaiting|requested|request|requesting|approval|approve[sd]?|needs?|"
                          r"unless|before|whether|to\s+be|recommend\w*|suggest\w*|consider\w*|propos\w*|options?|"
                          r"advis\w*|plan\w*|want|prefer|avoid|risk\w*|ask\w*|question\w*|wonder\w*)\b|n't\b)", _F)


def completion_claims(text: str) -> list[dict]:
    """Claims in generated text that a write-capability action happened or is under way.

    Lexical, so paraphrases outside these patterns are missed (stated, not hidden).
    Negated, future, conditional and approval-request phrasings are not claims.
    """
    out = []
    for cap, pats in _CLAIM_RE.items():
        for pat in pats:
            for m in pat.finditer(text or ""):
                window = " ".join((text[:m.start()]).split()[-5:]) + " " + m.group(0)
                if _NOT_A_CLAIM.search(window):
                    continue
                snippet = text[max(0, m.start() - 40):m.end() + 20].replace("\n", " ").strip()
                if not any(c["capability"] == cap and c["snippet"] == snippet for c in out):
                    out.append({"capability": cap, "snippet": snippet})
    return out
