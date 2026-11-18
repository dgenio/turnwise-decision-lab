"""Host-side resolution of the actions the *user* asked for (#12; shared vocabulary with #13).

An approval request is a prompt to a human on the user's behalf, so it needs positive evidence that the
user asked for that action. This resolver is the host's independent gate for that evidence. It is
deliberately conservative and lexical: English, this world's three write capabilities, user-authored text
only (never model output, tool data or benchmark gold).

Each detected action gets one status:

* ``requested``     explicit wording for the action, not negated, advice-seeking, hypothetical, drafting or
                    reporting, with its target named in the current message;
* ``unverified``    action wording whose target is ambiguous, missing or only in an earlier turn: clarify;
* ``not_requested`` negated, advice-seeking, hypothetical, drafting or reporting wording: no action.

Indirect phrasings with no action verb are not detected (a recall limit). That limit is to be measured on
new, independently written cases (#9), not tuned on held-out wording.
"""
from __future__ import annotations

import re

from .providers import SERVICE_ALIASES, named_services

VERBS = {
    "rollback_deployment": re.compile(r"\broll(?:\s+\w+){0,2}\s+back\b|\brollback\b|\brevert\b|"
                                      r"\bundo\s+the\s+(?:deploy\w*|release|change)\b", re.I),
    # "page" as a verb only: not "status page", "web page", "the page", "this page", "a page".
    "page_oncall": re.compile(r"(?<!status )(?<!web )(?<!the )(?<!this )(?<!a )\bpage\b|\bwake\s+up\b", re.I),
    "post_status_update": re.compile(r"\b(?:post|publish|announce)\b.*\bstatus\b|\bupdate\s+the\s+status\s+page\b", re.I),
}
GUARDS = (
    ("negated", re.compile(r"\b(?:don'?t|do\s+not|never|without|no\s+need|not\s+yet|hold\s+off|stop|avoid|instead\s+of)\b", re.I)),
    ("advice", re.compile(r"\b(?:should|shall|ought|would\s+it|is\s+it|do\s+you\s+think|whether|worth|recommend\w*|"
                          r"what\s+if|how\s+(?:do|would|to|can|should))\b", re.I)),
    ("hypothetical", re.compile(r"\b(?:if|unless|in\s+case|when(?:ever)?|once|may|might|later|eventually|tomorrow)\b", re.I)),
    ("drafting", re.compile(r"\b(?:draft|write|compose|prepare|suggest|propose|wording|template|example)\b", re.I)),
    ("reporting", re.compile(r"\b(?:did|was|were|has|have|had|who|why)\b", re.I)),
)
_POST_BODY = re.compile(r"\b(?:post|publish|announce)\b[^:]*\bstatus\b[^:]*:\s*(?P<body>.+)$", re.I | re.S)
_SPLIT = re.compile(r"[.;!?\n]+|\b(?:and|then|also|but)\b", re.I)
_FILLER = re.compile(r"\b(?:" + "|".join(map(re.escape, SERVICE_ALIASES)) +
                     r"|too|as\s+well|please|the|on.?call|team|teams)\b", re.I)


def normalise_message(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip().strip("\"'“”").strip().rstrip(".").casefold()


def _earlier_target(conversation) -> list[str]:
    for m in reversed(list(conversation or ())):
        if m.get("role") == "user":
            found = named_services(str(m.get("content", "")))
            if found:
                return found
    return []


def resolve_user_actions(message: str, conversation=()) -> list[dict]:
    """Actions the user's own words ask for. Entries: capability, arguments, status, reason, evidence."""
    text, body = message, None
    m = _POST_BODY.search(message)
    if m:  # a literal status-post body is data: keep it whole and out of clause analysis
        body = m.group("body").strip().strip("\"'“”").strip()
        text = message[: m.start("body")]
    in_message = named_services(text)
    out: list[dict] = []
    shared = None  # (capability, status) a service-only clause may inherit: "page search and checkout"
    for clause in (c.strip() for c in _SPLIT.split(text)):
        if not clause:
            continue
        found = [cap for cap, rx in VERBS.items() if rx.search(clause)]
        services = named_services(clause)
        if not found:
            if shared and services and not re.search(r"\w", _FILLER.sub("", clause)):
                found = [shared[0]]
            else:
                shared = None
                continue
        guard = next((name for name, rx in GUARDS if rx.search(clause)), None)
        for cap in found:
            entry = {"capability": cap, "arguments": {}, "evidence": clause[:160]}
            if guard:
                entry.update(status="not_requested", reason=guard)
            elif cap == "post_status_update":
                if body and 0 < len(body) <= 300:
                    entry["arguments"] = {"message": body}
                entry.update(status="requested", reason="explicit request")
            elif len(services) == 1 or (not services and len(in_message) == 1):
                entry.update(arguments={"service": (services or in_message)[0]}, status="requested", reason="explicit request")
            elif services or in_message:
                entry.update(status="unverified", reason="more than one service named")
            else:
                earlier = _earlier_target(conversation)
                if len(earlier) == 1:
                    entry["arguments"] = {"service": earlier[0]}
                entry.update(status="unverified", reason="target only in an earlier turn" if earlier else "no target named")
            if entry not in out:
                out.append(entry)
        shared = (found[0], None) if len(found) == 1 and found[0] != "post_status_update" else None
    return out
