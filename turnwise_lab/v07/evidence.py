"""Evidence contracts: what a reply of a given kind must rest on.

A *claim* is the kind of reply a request asks for (a lookup, a causal
attribution, a verification, an action, small talk). A *contract* is the set
of evidence classes that kind of reply requires for a given entity, plus any
approval the request implies. Everything here is deterministic host code over
trusted inputs: the user's text, the conversation, tool receipts. It never sees
a gold label, and it calls no model.

The one rule that is not specific to this world is the **two-sided rule**: a
reply that attributes a cause needs at least one receipt of a *symptom*
(something observed about the entity) and one of a *change* (a candidate
cause) for the same entity. Which tool supplies which side is declared as
metadata on the capability (``EVIDENCE``), the way a framework would annotate
a tool.

Claim typing is a small lexicon, deliberately. When it cannot type a request
it says ``untyped`` and the turn goes to a tool-capable agent. It is built to
prefer ``untyped`` over a guess, but it is a lexicon: it can still type a
request wrongly, and the study counts how often (prediction C3).
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re

from ..agent.host import CATALOG_BY_ID
from ..agent.world import SERVICES

# ------------------------------------------------------------- tool metadata
SYMPTOM, CHANGE, OWNERSHIP, REFERENCE, COMPOSITE = "symptom", "change", "ownership", "reference", "composite"


@dataclass(frozen=True)
class EvidenceSpec:
    capability: str
    kind: str  # fact-key prefix produced by the capability
    role: str


EVIDENCE: tuple[EvidenceSpec, ...] = (
    EvidenceSpec("get_service_health", "health", SYMPTOM),
    EvidenceSpec("get_error_metrics", "errors", SYMPTOM),
    EvidenceSpec("get_deployment_history", "deploys", CHANGE),
    EvidenceSpec("get_config_diff", "config", CHANGE),
    EvidenceSpec("get_service_owner", "owner", OWNERSHIP),
    EvidenceSpec("search_runbooks", "doc", REFERENCE),
    EvidenceSpec("run_smoke_checks", "smoke", COMPOSITE),
)
BY_KIND = {e.kind: e for e in EVIDENCE}
ROLE_OF = {e.kind: e.role for e in EVIDENCE}

# ------------------------------------------------------------------ lexicon
ALIASES = {"checkout": "checkout", "payments": "payments", "payment": "payments", "search": "search",
           "auth": "auth", "authentication": "auth", "login": "auth"}
_UNKNOWN_SERVICE = re.compile(r"\b([a-z][a-z0-9]*)[- ](?:svc|service)\b")
_NOT_A_NAME = {"the", "this", "that", "a", "an", "which", "what", "our", "your", "any", "some", "every", "each", "no", "another", "other", "one",
               "whose", "their", "its", "my", "micro", "web", "same", "whole", "entire", "wrong", "right", "affected", "upstream", "downstream"}
EVERY_SERVICE = r"\b(?:any|all|every|each|which) (?:service|services|of them|of the services)\b|\beverything\b|\banything\b|\ball four\b"

# A side effect is requested only inside a *request frame*. An action word on its own is not a request:
# "is it safe to roll back?", "who approved the rollback?", "cancel the rollback", "the login page" are not.
ACTION_CUES = (
    ("post_status_update", r"\b(?:post|publish|announce|put|push|update)\b[^.?!]*\bstatus ?page\b|\bstatus ?page\b[^.?!]*\b(?:post|publish|update)\b"),
    ("rollback_deployment", r"\broll(?:ing)?[- ]?back\b|\broll (?:it|that|this|them|\w+) back\b|\brollback\b|\brevert\w*\b|"
                            r"\bback (?:it|that|this|d-\d+) out\b|\bback out\b|\bundo (?:the|that|this|it)\b|\bput \w+ back\b|"
                            r"\bprevious (?:build|version|release)\b|\bgo back to\b"),
    ("page_oncall", r"\bpag(?:e|ing|ed)\b|\bwake\b|\bcall ?out\b|\bon the (?:line|phone|call|bridge)\b|\bping (?:the )?(?:on.?call|team)\b|"
                    r"\bescalate to (?:the )?on.?call\b"),
)
_PAGE_NOUN_BEFORE = {"status", "login", "landing", "home", "web", "the", "a", "this", "that", "error", "front", "product", "each", "every", "per", "wiki", "docs"}
_PAGE_NOUN_AFTER = {"is", "was", "has", "load", "loads", "size", "shows", "says", "throws", "throwing", "returns", "keeps", "itself", "and", "or"}
REQUEST_MARK = (r"\b(?:please|pls|plz|kindly|can (?:you|u|we)|could (?:you|u|we)|would (?:you|u)|will (?:you|u)|go ahead|let'?s|need (?:you )?to|needs to|"
                r"have to|got to|gotta|time to|want (?:you )?to|just|now|asap|immediately|already)\b")
TRIGGER_VERB = r"\b(?:do|queue|execute|start|kick off|trigger|run|initiate|perform|proceed with|request|file|raise|get|want|need)\b"
FILLER = r"^(?:\s|,|ok(?:ay)?|k|kk|so|then|and|and then|yes|yeah|yep|right|alright|argh|well|hey|hi|fine|cool|great|sure)*"
SELF_DOING = r"(?:\bi'?m going to|\bi am going to|\bi will|\bi'?ll|\bi already|\bwe already|\bi just|\bi can|\bi could|\bwe will|\bwe'?ll)\s+(?:\w+\s+){0,2}$"
QUESTION_START = r"^(?:is|are|was|were|did|does|do|has|have|had|who|what|when|where|why|how|should|shall|whether|if|any)\b"
POLITE = r"\b(?:please|pls|plz|kindly|can (?:you|u|we)|could (?:you|u|we)|would (?:you|u)|will (?:you|u))\b"
NEGATION = (r"\b(?:don'?t|do not|dont|never|without|hold off|not yet|no need to|instead of|cancel|abort|no|not|"
            r"before (?:we|i|you) (?:even )?(?:think|consider))\b")
READ_VERBS = r"\b(?:pull|show|check|fetch|look at|look up|tell me|give me|grab|get me|what(?:'?s| is| are| has)|how(?:'?s| is| are))\b"
GENERAL = r"\b(?:people|in general|generally|usually|typically|what does .{1,30} (?:mean|stand for)|what is an?|what's an?|difference between|instead of|versus|vs)\b"
CORRECTION = r"\b(?:i meant|meant|wrong (?:svc|service|one)|not \w+,? (?:but )?|sorry,?|correction|typo)\b"
MAX_LOOKUP_WORDS = 16  # a longer non-causal message usually carries a claim or a second request the lexicon cannot see
BARE_REFERENT = r"\b(?:it|that|this|them|those)\b"
CAUSAL = (r"\b(?:why|caus\w*|because|due to|culprit|responsible|behind|blame\w*|to blame|related|connected|linked|led to|root ?cause|"
          r"trigger\w*|red herring|explain\w*|what(?:'s| has)? changed|wh?at changed|any chance|did that|do(?:es|ing)? this|is it the|was it the|"
          r"fault|bad (?:deploy|release|push|config|change)|pointing fingers|set (?:it |this |that )?off|how come|reason|suspect\w*|"
          r"line[sd]? up|timing)\b")
VERIFY = (r"\b(?:verify|confirm|is it true|is that true|actually|really|back that up|back(?:s|ed)? (?:it|that|this) up|check (?:whether|if)|"
          r"does the data|sanity.?check|double.?check|fact.?check|claim\w*|saying|says|told me|heard)\b")
SYMPTOM_KINDS = (("errors", r"\berror\w*|\b5xx\b|\b50[0-4]s?\b|\bfail\w*|\berroring\b"),
                 ("health", r"\bp95\b|\bp99\b|\blatenc\w*|\bslow\w*|\bsluggish\b|\blag\w*|\btaking forever\b|\bhealth\w*|\bdegraded\b|"
                            r"\bstatus\b(?! ?page)|\bdown\b|\bholding up\b"))
WEAK_HEALTH = r"\bhow bad\b|\bnumbers\b|\bhow(?:'s| is| are)\b|\bdoing\b"  # only when nothing more specific matched
CHANGE_KINDS = (("deploys", r"\bdeploy\w*|\breleas\w*|\brollout\b|\bshipp?ed\b|\bpush(?:ed)?\b|\bbuild\b|\breindex\w*|\bbump\w*|\bd-\d+\b|"
                            r"\bchange[ds]?\b|\bsigned off\b|\bapproved\b"),
                ("config", r"\bconfig\w*|\bcfg\b|\bsettings?\b|\bbaseline\b|\bdrift\w*|\brate.?limit\w*|\bpool\b|\bshards?\b"))
LOOKUP_KINDS = (("owner", r"\bown\w*|\bteam\b|\bon.?call\b|\bwho (?:do|should|can) (?:i|we) (?:bug|ask|ping|contact|talk)\b|\bloop in\b|\bwhose\b|\brotation\b"),
                ("smoke", r"\bsmoke\b"),
                ("doc", r"\brunbooks?\b|\bpolic(?:y|ies)\b|\bprocedures?\b|\bplaybooks?\b"))
RECORD = r"\bsev(?:erity)?\b|\bincident (?:commander|id|start\w*)\b|\bcommander\b|\b(?:who'?s|who is) (?:running|leading|the ic)\b|\bic\b|\bstatus ?page (?:say|state|show)\w*"
SMALLTALK = r"^\s*(?:hi|hello|hey|yo|morning|good (?:morning|afternoon|evening)|thanks|thank you|thx|ty|cheers|perfect|great|nice|ok(?:ay)?|cool)\b"
ASKING = r"\b(?:who|what|which|when|where|why|whose|can (?:you|u)|could (?:you|u)|pls|please)\b"
RECORD_FIELDS = (("severity", r"\bsev\w*"), ("incident_commander", r"\bcommander\b|\bic\b|\brunning\b|\bleading\b"),
                 ("incident_id", r"\bincident (?:id|number)\b|\bwhich incident\b"), ("incident_start", r"\bstart\w*\b|\bbegan\b|\bsince when\b"),
                 ("status_page", r"\bstatus ?page\b"))


def services_in(text: str) -> list[str]:
    out = []
    for w in re.findall(r"[a-z]+", text.lower()):
        s = ALIASES.get(w)
        if s and s not in out:
            out.append(s)
    return out


def unknown_services(text: str) -> list[str]:
    return [m for m in _UNKNOWN_SERVICE.findall(text.lower()) if m not in ALIASES and m not in _NOT_A_NAME]


def strip_quoted(text: str) -> str:
    """The user's own words only. Quoted or pasted text is content: it can never make a request.

    Everything between the first and the last quote mark of a kind is removed (so nested quotes cannot leak), an
    unbalanced quote removes the rest of the message, and blockquote lines are dropped. Deliberately conservative.
    """
    t = "\n".join(line for line in text.split("\n") if not line.lstrip().startswith(">"))
    for opening, closing in (('"', '"'), ("“", "”"), ("«", "»"), ("`", "`")):
        i, j = t.find(opening), t.rfind(closing)
        if i != -1:
            t = t[:i] + " " + (t[j + 1:] if j > i else "")
    opens = [m.start() for m in re.finditer(r"(?:(?<=\s)|^|(?<=[(:,]))'(?=\S)", t)]
    closes = [m.end() for m in re.finditer(r"(?<=\S)'(?=\s|$|[.,;:!?)])", t)]
    if opens and closes and closes[-1] > opens[0]:
        t = t[:opens[0]] + " " + t[closes[-1]:]
    return t


def quoted_content(text: str) -> str | None:
    for opening, closing in (('"', '"'), ("“", "”"), ("«", "»")):
        i, j = text.find(opening), text.rfind(closing)
        if i != -1 and j > i + 1:
            return text[i + 1:j].strip()
    return None


def focus_entity(message: str, conversation: list[dict]) -> tuple[list[str], str]:
    """Entities the request is about, and where they came from.

    Named in the message wins. Otherwise the most recent message that names a service decides, and only if it names
    exactly one; if it names several, the user's own most recent mention decides, and failing that the reference is
    ambiguous and every candidate is returned. v0.5 and v0.6 took the first service in the joined history, which is
    how a follow-up ended up on the wrong service.
    """
    named = services_in(message)
    if named:
        return named, "message"
    for m in reversed(conversation or []):
        found = services_in(m.get("content", ""))
        if not found:
            continue
        if len(found) == 1:
            return found, "conversation"
        for u in reversed(conversation):
            mine = services_in(u.get("content", "")) if u.get("role") == "user" else []
            if mine:
                return (mine, "conversation") if len(mine) == 1 else (found, "conversation")
        return found, "conversation"
    return [], "none"


# -------------------------------------------------------------------- claims
@dataclass
class Claim:
    type: str  # lookup | record | causal | verification | action | smalltalk | ambiguous | untyped
    entities: list[str] = field(default_factory=list)
    entity_source: str = "none"
    symptoms: list[str] = field(default_factory=list)  # evidence kinds
    changes: list[str] = field(default_factory=list)
    lookups: list[str] = field(default_factory=list)
    action: str | None = None  # write capability the user asked for
    declined_action: str | None = None  # write capability the user explicitly declined
    record_fields: list[str] = field(default_factory=list)
    cues: list[str] = field(default_factory=list)
    status_text: str | None = None

    def as_json(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v not in (None, [], "none")}


def _kinds(table, text) -> list[str]:
    return [kind for kind, pat in table if re.search(pat, text)]


def _is_page_verb(clause: str, m: re.Match) -> bool:
    if not m.group(0).startswith("pag"):
        return True
    before = re.findall(r"[a-z']+", clause[:m.start()])[-1:] or [""]
    after = re.findall(r"[a-z']+", clause[m.end():])[:1] or [""]
    if m.group(0) == "paged":
        return bool(re.search(r"\bget\b|\bhave\b|\bneed\b|\bwant\b", clause[:m.start()]))
    return before[0] not in _PAGE_NOUN_BEFORE and after[0] not in _PAGE_NOUN_AFTER and after[0] != ""


def detect_action(text: str) -> tuple[str | None, str | None]:
    """(requested write, explicitly declined write), from the user's own words (``strip_quoted`` first).

    Requested needs a request frame in the same clause: an imperative ("roll back checkout"), a polite or urgent
    marker ("could you", "pls", "just", "now"), or a trigger verb before a noun ("queue up the rollback"). A question
    about an action, a report of one, or the user saying they will do it themselves is neither requested nor declined.
    """
    t = strip_quoted(text).lower()
    requested = declined = None
    for clause in re.split(r"[.;!\n]|\?", t):
        raw = clause
        clause = clause.strip()
        if not clause:
            continue
        ends_question = raw + "?" in t and t[t.find(raw) + len(raw):t.find(raw) + len(raw) + 1] == "?"
        for cap, pat in ACTION_CUES:
            for m in re.finditer(pat, clause):
                if cap == "page_oncall" and not _is_page_verb(clause, m):
                    continue
                pre = clause[:m.start()]
                if re.search(NEGATION, pre):
                    declined = declined or cap
                    continue
                if re.search(SELF_DOING, pre):
                    continue
                polite = bool(re.search(POLITE, clause))
                if (ends_question or re.search(QUESTION_START, clause)) and re.search(QUESTION_START, clause) and not polite:
                    continue  # a question about the action ("is it safe to roll back?", "who approved the rollback?")
                imperative = re.sub(FILLER, "", pre).strip() == "" or bool(re.search(r"(?:\band|\bthen|,)\s*(?:just |also |please )?$", pre))
                framed = imperative or polite or bool(re.search(REQUEST_MARK, clause)) or bool(re.search(TRIGGER_VERB, pre))
                if framed:
                    requested = requested or cap
    return requested, declined


def _evidence_kinds(text: str, claim: "Claim") -> None:
    claim.symptoms, claim.changes, claim.lookups = _kinds(SYMPTOM_KINDS, text), _kinds(CHANGE_KINDS, text), _kinds(LOOKUP_KINDS, text)
    if not claim.symptoms and not claim.changes and not claim.lookups and re.search(WEAK_HEALTH, text):
        claim.symptoms = ["health"]
    if "smoke" in claim.lookups:  # an explicit composite check is the whole request ("which checks fail" is not an error-rate question)
        claim.symptoms, claim.changes = [], []


def type_claim(message: str, conversation: list[dict] | None = None) -> Claim:
    """Deterministic claim typing from the request and the conversation only."""
    conversation = conversation or []
    full = message.lower()
    text = strip_quoted(message).lower()  # quoted text is content: it can never request an action or count as the user's own cue
    entities, source = focus_entity(strip_quoted(message), conversation)
    if not entities and services_in(full) and source == "none" and re.search(VERIFY + "|" + CAUSAL, text):
        entities, source = services_in(full), "quoted"  # ...but when the user asks to check a quoted claim, it says what the claim is about
    c = Claim("untyped", entities, source)
    unknown = unknown_services(text)
    if unknown and not services_in(text):
        c.type, c.cues = "ambiguous", [f"unknown service {unknown[0]!r}"]
        return c
    c.action, c.declined_action = detect_action(message)
    stripped = text
    for _, pat in ACTION_CUES:  # the words of an action are not an evidence request ("roll back the deploy" is not about deploys)
        stripped = re.sub(pat, " ", stripped)
    if c.action:
        stripped = re.sub(r"\bd-\d+\b", " ", stripped)  # a deploy id next to an action is the action's object, not a read request
    evidence_text = stripped if (c.action or c.declined_action) else (full if source == "quoted" else text)
    _evidence_kinds(evidence_text, c)
    causal, verify = bool(re.search(CAUSAL, text)), bool(re.search(VERIFY, text))
    if re.search(SMALLTALK, text) and len(text) < 80 and not services_in(text) and not c.action and not c.symptoms and not c.changes \
            and "?" not in re.sub(r"how are (?:you|u)\??|how's it going\??", " ", text) \
            and not re.search(ASKING, re.sub(r"how are (?:you|u)|how's it going", " ", text)):
        c.type = "smalltalk"
        return c
    asks_document = "doc" in c.lookups and not c.symptoms
    if asks_document:  # "is there a policy on posting to the status page?" asks what a document says; it requests nothing
        c.type, c.action, c.changes, c.lookups = "lookup", None, [], ["doc"]
        c.cues.append("asks what a document says")
        return c
    if c.action:
        c.cues.append(f"action:{c.action}")
        if not re.search(READ_VERBS, stripped):
            c.symptoms, c.changes, c.lookups = [], [], []
        if c.action == "post_status_update":
            after = re.search(r"(?::|\bsaying\b|\bthat says\b|\bto say\b)\s*(\S.{8,})$", strip_quoted(message), re.S)
            c.status_text = quoted_content(message) or (after.group(1).strip() if after else None)
            if not c.status_text:
                c.type = "ambiguous"
                c.cues.append("status update requested without the text to post")
                return c
        elif len(entities) != 1:
            c.type = "ambiguous"
            c.cues.append("action without exactly one identifiable service")
            return c
        c.type = "action"
        return c
    if not entities and re.search(EVERY_SERVICE, text) and (c.symptoms or c.changes or c.lookups) and not (causal or verify):
        c.entities, c.entity_source = list(SERVICES), "every service"
        entities = c.entities
    if (causal or verify) and (c.symptoms or c.changes or entities):
        if not entities and re.search(GENERAL, text):
            c.cues.append("general-knowledge phrasing; not a claim about this incident")
            return c
        if len(entities) > 1:
            c.cues.append("a claim that relates more than one service: not typed, left to the agent")
            return c
        c.type = "causal" if causal else "verification"
        c.cues.append("causal language" if causal else "verification language")
        if len(entities) != 1:
            c.type = "ambiguous"
            c.cues.append("claim about no identifiable service")
        return c
    if c.symptoms or c.changes or c.lookups:
        if not entities and re.search(GENERAL, text):
            c.cues.append("general-knowledge phrasing; not a lookup")
            return c
        if not entities or (source == "conversation" and len(entities) > 1):
            c.type = "ambiguous"
            c.cues.append("lookup without one identifiable service")
            return c
        if c.symptoms and c.changes and len(entities) == 1:
            c.type = "verification"  # a symptom and a change named together: their relation is the question
            c.cues.append("symptom and change named together")
            return c
        if len(text.split()) > MAX_LOOKUP_WORDS:
            c.cues.append(f"evidence words found, but the message is longer than {MAX_LOOKUP_WORDS} words with no causal or action cue: not typed")
            return c
        c.type = "lookup"
        return c
    if re.search(RECORD, text):
        c.type = "record"
        c.record_fields = [f for f, pat in RECORD_FIELDS if re.search(pat, text)] or ["severity", "incident_commander"]
        return c
    if conversation and len(entities) == 1 and len(text) < 60:
        prev = next((m["content"] for m in reversed(conversation) if m["role"] == "user"), "")
        p = type_claim(prev, [])
        if p.action and source == "message" and re.search(CORRECTION, text):
            c.cues.append("correction: the previous action request now names this service")
            c.type, c.action, c.status_text = "action", p.action, p.status_text
            return c
        if p.type in ("lookup", "causal", "verification") and not p.action and not c.declined_action:
            c.cues.append("short follow-up: the previous kind of request carried over to this entity")
            c.type, c.symptoms, c.changes, c.lookups = p.type, p.symptoms, p.changes, p.lookups
            return c
    if not entities and not conversation and len(text) < 60 and re.search(BARE_REFERENT, text):
        c.type = "ambiguous"
        c.cues.append("refers to something ('it', 'that') that nothing identifies")
    return c


# ------------------------------------------------------------------ contract
DRIFT_DOC = "a configuration drift may be a documented, planned change"


@dataclass(frozen=True)
class Requirement:
    kind: str
    entity: str | None  # None for a document search
    why: str

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.entity}" if self.entity else self.kind

    def call(self, message: str, have: dict | None = None) -> tuple[str, dict]:
        cap = BY_KIND[self.kind].capability
        if "service" in CATALOG_BY_ID[cap].params:
            return cap, {"service": self.entity}
        query = message[:300]
        if self.why == DRIFT_DOC:  # search for the documented reason of the drift itself, not for the user's wording
            drifted = [(k, v) for k, v in (have or {}).items() if k.startswith("config:") and not v.get("matches_baseline")]
            if drifted:
                key, cfg = drifted[0]
                query = f"{key.split(':', 1)[1]} " + " ".join(name.replace("_", " ") for name in cfg["drifted"])
        return cap, {"query": query}


@dataclass
class Contract:
    claim: Claim
    requirements: list[Requirement] = field(default_factory=list)
    hold: tuple[str, dict] | None = None  # (write capability, arguments) the request implies
    clarify: str | None = None
    revisions: list[str] = field(default_factory=list)

    def as_json(self) -> dict:
        return {"claim": self.claim.as_json(), "requirements": [{"need": r.key, "why": r.why} for r in self.requirements],
                "hold": {"target": self.hold[0], "arguments": self.hold[1]} if self.hold else None,
                "clarify": self.clarify, "revisions": list(self.revisions)}


def compile_contract(claim: Claim, message: str) -> Contract:
    k = Contract(claim)
    if claim.type == "ambiguous":
        k.clarify = "; ".join(claim.cues) or "no identifiable service"
        return k
    ents = claim.entities
    if claim.type in ("causal", "verification"):
        e = ents[0]
        symptoms = claim.symptoms or ["errors", "health"]  # no symptom named: read both symptom tools
        for s in symptoms:
            k.requirements.append(Requirement(s, e, "symptom side of the claim"))
        if claim.type == "causal":
            for ch in (claim.changes or ["deploys", "config"]):
                k.requirements.append(Requirement(ch, e, "candidate-cause side of the claim (two-sided rule)"))
        else:
            for ch in claim.changes:
                k.requirements.append(Requirement(ch, e, "the claim to verify names this change"))
        if "config" in [r.kind for r in k.requirements]:
            k.requirements.append(Requirement("doc", None, DRIFT_DOC))
    elif claim.type == "lookup":
        for kind in claim.symptoms + claim.changes + [x for x in claim.lookups if x != "doc"]:
            for e in ents:
                k.requirements.append(Requirement(kind, e, "the request asks for this"))
        if "doc" in claim.lookups:
            k.requirements.append(Requirement("doc", None, "the request asks what a document says"))
    elif claim.type == "action":
        cap = claim.action
        k.hold = (cap, {"message": (claim.status_text or "")[:300]} if cap == "post_status_update" else {"service": ents[0]})
        if len(ents) == 1:
            for kind in claim.symptoms + claim.changes + [x for x in claim.lookups if x != "doc"]:
                k.requirements.append(Requirement(kind, ents[0], "the request also asks for this before the action"))
    seen, uniq = set(), []
    for r in k.requirements:
        if r.key not in seen:
            seen.add(r.key)
            uniq.append(r)
    k.requirements = uniq
    return k


# ------------------------------------------------------------------ receipts
def receipts(observations) -> dict[str, dict]:
    """fact key -> value, from successful tool executions only (the provenance the gate trusts)."""
    out = {}
    for o in observations:
        if o.status == "ok":
            out.update(o.facts)
    return out


def _attempts(observations, cap: str, args: dict) -> tuple[int, int]:
    ok = sum(1 for o in observations if o.target == cap and o.arguments == args and o.status == "ok")
    err = sum(1 for o in observations if o.target == cap and o.arguments == args and o.status == "error")
    return ok, err


def revise(contract: Contract, observations) -> Contract:
    """Observation-driven revision. Two rules, both about what the receipts already show."""
    have = receipts(observations)
    claim = contract.claim
    if claim.type in ("causal", "verification") and claim.entities:
        e = claim.entities[0]
        cfg = have.get(f"config:{e}")
        if cfg is not None and cfg.get("matches_baseline") and any(r.why == DRIFT_DOC for r in contract.requirements) \
                and not any(k.startswith("doc:") for k in have):
            contract.requirements = [r for r in contract.requirements if r.why != DRIFT_DOC]
            contract.revisions.append("configuration matches baseline: there is no drift to look up a documented reason for")
        errs = have.get(f"errors:{e}")
        only_errors = claim.symptoms == ["errors"]  # the request names an error rise and nothing else as the symptom
        if errs is not None and errs.get("change_point") is None and only_errors:
            dropped = [r for r in contract.requirements if ROLE_OF.get(r.kind) in (CHANGE, REFERENCE) and r.key not in have
                       and not (r.kind == "doc" and any(k.startswith("doc:") for k in have))]
            if dropped and claim.type == "causal" and "premise not observed" not in " ".join(contract.revisions):
                contract.requirements = [r for r in contract.requirements if r not in dropped]
                contract.revisions.append("premise not observed: errors did not rise, so no candidate cause is required ("
                                          + ", ".join(r.key for r in dropped) + " dropped)")
        dep = have.get(f"deploys:{e}")
        kinds = [r.kind for r in contract.requirements]
        if dep is not None and not dep.get("deploys") and "config" not in kinds and claim.type == "causal":
            contract.requirements.append(Requirement("config", e, "no deploy on record: widen to the other change record"))
            contract.requirements.append(Requirement("doc", None, DRIFT_DOC))
            contract.revisions.append("no deploy on record: configuration diff and its documentation are now required")
    return contract


def missing(contract: Contract, observations, message: str, max_retries: int = 1) -> tuple[list[Requirement], list[Requirement]]:
    """(requirements still to acquire, requirements that failed and are out of retries)."""
    have = receipts(observations)
    todo, unavailable = [], []
    config_pending = any(r.kind == "config" and r.key not in have for r in contract.requirements)
    for r in contract.requirements:
        if r.kind == "doc":
            if r.why == DRIFT_DOC and config_pending:
                continue  # deferred: the query is built from the drift, which has not been read yet
            cap, args = r.call(message, have)
            ok, err = _attempts(observations, cap, args)
            if ok or any(k.startswith("doc:") for k in have):
                continue
        else:
            if r.key in have:
                continue
            cap, args = r.call(message)
            ok, err = _attempts(observations, cap, args)
        (unavailable if err > max_retries else todo).append(r)
    return todo, unavailable


# ------------------------------------------------------------ derived facts
def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def derive(observations, claim: Claim | None = None) -> list[dict]:
    """Facts the host computes from receipts: orderings, differences, absences.

    Arithmetic and timestamp comparison are deterministic work, so they are not
    left to a language model. Every derived fact names the receipts it uses.
    """
    have = receipts(observations)
    out = []
    ents = sorted({k.split(":", 1)[1] for k in have if not k.startswith("doc:")})
    if claim and claim.entities:
        ents = [e for e in claim.entities if e in ents] + [e for e in ents if e not in claim.entities]
    for e in ents:
        errs, dep, cfg, health = have.get(f"errors:{e}"), have.get(f"deploys:{e}"), have.get(f"config:{e}"), have.get(f"health:{e}")
        cp = errs.get("change_point") if errs else None
        if errs:
            if cp:
                out.append({"id": f"rise:{e}", "uses": [f"errors:{e}"], "relation": "rise",
                            "text": f"{e} error rate rose from {errs['before_pct']}% to {errs['after_pct']}% starting at {cp} (window {errs['window']})."})
            else:
                out.append({"id": f"flat:{e}", "uses": [f"errors:{e}"], "relation": "flat",
                            "text": f"{e} error rate did not rise: {errs['before_pct']}% -> {errs['after_pct']}% over {errs['window']}, no change point."})
        if dep is not None:
            if not dep["deploys"]:
                out.append({"id": f"no_deploy:{e}", "uses": [f"deploys:{e}"], "relation": "no_deploy",
                            "text": f"{e} has no deployment in the {dep['window']}, so a deployment cannot explain a change in that period."})
            for d in dep["deploys"]:
                at = d["at"][11:16]
                base = f"deploy {d['id']} of {e} at {at} (approved by {d['approved_by']}): {d['change']}."
                if cp:
                    delta = _minutes(cp) - _minutes(at)
                    if delta >= 0:
                        out.append({"id": f"before:{d['id']}", "uses": [f"errors:{e}", f"deploys:{e}"], "relation": "precedes", "minutes": delta,
                                    "text": f"{base} It landed {delta} min BEFORE the error rise at {cp}: the timing is consistent with it being a cause (correlation, not proof)."})
                    else:
                        out.append({"id": f"after:{d['id']}", "uses": [f"errors:{e}", f"deploys:{e}"], "relation": "follows", "minutes": -delta,
                                    "text": f"{base} It landed {-delta} min AFTER the error rise at {cp}, so it cannot have caused that rise."})
                else:
                    out.append({"id": f"deploy:{d['id']}", "uses": [f"deploys:{e}"], "relation": "deploy", "text": base})
            if cp and len(dep["deploys"]) > 1:
                prior = [(d, _minutes(cp) - _minutes(d["at"][11:16])) for d in dep["deploys"] if _minutes(cp) >= _minutes(d["at"][11:16])]
                if prior:
                    d, delta = min(prior, key=lambda x: x[1])
                    out.append({"id": f"closest:{e}", "uses": [f"errors:{e}", f"deploys:{e}"], "relation": "closest",
                                "text": f"Of {len(dep['deploys'])} deployments, {d['id']} is the closest one before the rise ({delta} min)."})
        if cfg is not None:
            if cfg["matches_baseline"]:
                out.append({"id": f"config_ok:{e}", "uses": [f"config:{e}"], "relation": "config_ok",
                            "text": f"{e} configuration matches the approved baseline."})
            else:
                drift = "; ".join(f"{k} is {v['current']} (baseline {v['baseline']})" for k, v in cfg["drifted"].items())
                extra = ""
                if dep is not None and not dep["deploys"]:
                    extra = " There is no deployment on record, so this drift is an out-of-band change and a candidate cause."
                out.append({"id": f"drift:{e}", "uses": [f"config:{e}"] + ([f"deploys:{e}"] if extra else []), "relation": "drift",
                            "text": f"{e} configuration has drifted from baseline: {drift}.{extra}"})
        if health:
            out.append({"id": f"health:{e}", "uses": [f"health:{e}"], "relation": "health",
                        "text": (f"{e} is {health['status']} now: error rate {health['error_rate_pct']}%, p95 {health['p95_ms']} ms. "
                                 "This is a current snapshot; no latency time series is available, so when latency changed cannot be verified.")})
        owner, smoke = have.get(f"owner:{e}"), have.get(f"smoke:{e}")
        if owner:
            out.append({"id": f"owner:{e}", "uses": [f"owner:{e}"], "relation": "owner",
                        "text": f"{e} is owned by team {owner['team']}; on-call rotation {owner['oncall']}."})
        if smoke:
            out.append({"id": f"smoke:{e}", "uses": [f"smoke:{e}"], "relation": "smoke",
                        "text": f"{e} smoke checks failed: {', '.join(smoke['failed']) or 'none'}."})
    for k, v in have.items():
        if k.startswith("doc:"):
            out.append({"id": k, "uses": [k], "relation": "doc", "text": f"{v['title']}: {v['body']}"})
    return out


def verdict(claim: Claim, derived: list[dict], unavailable: list[Requirement] = ()) -> str:
    """One host-written sentence stating what the receipts do and do not support. Never stronger than the evidence."""
    rel = {}
    for d in derived:
        rel.setdefault(d["relation"], []).append(d)
    if unavailable:
        gap = ", ".join(r.key for r in unavailable)
        return f"Conclusion: incomplete. Evidence could not be retrieved ({gap}), so no conclusion about a cause is drawn."
    if claim.type not in ("causal", "verification"):
        return ""
    e = claim.entities[0] if claim.entities else "the service"
    if "flat" in rel and "rise" not in rel and "health" not in [k for k in claim.symptoms]:
        return f"Conclusion: the premise is not supported. {e} errors did not rise in the window, so there is nothing for a change to explain."
    if "rise" in rel:
        pre, post = rel.get("precedes", []), rel.get("follows", [])
        if pre:
            best = min(pre, key=lambda d: d["minutes"])
            return (f"Conclusion: the evidence is consistent with {best['id'].split(':')[1]} as the cause of the {e} error rise "
                    f"(it landed {best['minutes']} min before). This is a timing correlation, not proof.")
        if post:
            return f"Conclusion: the deployment is ruled out by timing. It landed after the {e} error rise, so it did not cause it."
        if "no_deploy" in rel:
            if "drift" in rel:
                return (f"Conclusion: no deployment can explain the {e} error rise. The configuration has drifted with no deployment on record; "
                        "that out-of-band change is the candidate cause, but when it happened is not recorded.")
            if "config_ok" in rel:
                return f"Conclusion: neither a deployment nor a configuration drift explains the {e} error rise. The cause is unknown from this evidence."
            return f"Conclusion: no deployment can explain the {e} error rise."
        if "drift" in rel:
            return f"Conclusion: {e} errors rose and its configuration has drifted; whether the drift caused the rise is not established (no time for the drift)."
        return f"Conclusion: {e} errors rose; no candidate cause has been examined."
    if "health" in rel:
        changes = rel.get("deploy", []) + rel.get("drift", [])
        doc = rel.get("doc", [])
        if "no_deploy" in rel and not rel.get("drift"):
            return f"Conclusion: {e} has no recorded change that could explain its current state."
        if changes:
            return (f"Conclusion: {e}'s current state and the recorded change are shown above. The change is a plausible candidate, "
                    "but there is no latency time series, so the timing cannot be confirmed from this evidence"
                    + ("; see the reference text above for the documented mechanism." if doc else "."))
    if "drift" in rel and "flat" in rel:
        return (f"Conclusion: {e} configuration has drifted, but its error rate did not rise, so the drift is not shown to be causing errors"
                + ("; see the reference text above for the documented reason." if rel.get("doc") else "."))
    return "Conclusion: the evidence above is what is on record; it does not establish a cause."


def render_findings(claim: Claim, derived: list[dict], unavailable: list[Requirement] = ()) -> str:
    lines = ["Findings (computed by the host from tool receipts; no model wrote this):"]
    lines += [f"- {d['text']}" for d in derived]
    for r in unavailable:
        lines.append(f"- UNAVAILABLE: {r.key} could not be retrieved after a retry.")
    v = verdict(claim, derived, unavailable)
    if v:
        lines.append(v)
    return "\n".join(lines)
