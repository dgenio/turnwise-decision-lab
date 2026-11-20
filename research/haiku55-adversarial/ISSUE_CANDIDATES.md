# ISSUE_CANDIDATES

Proposals only. **No GitHub issue has been created** (another session owns backlog creation). Base commit: `9965daf00ec31c6166905a9632379af0da12adbc`. Reproduce with:

```bash
cd <repo root at 9965daf>
python3 research/haiku55-adversarial/test_adversarial_decisions.py -v     # FAIL cases named below
python3 research/haiku55-adversarial/test_adversarial_decisions.py --observe
```

Ranked by suggested priority. The first two are the strongest evidence.

---

## 1. FINISH accepts completed-side-effect claims that avoid the keyword screen

**Priority:** High (terminal status can report success for an action that never happened).

**Problem.** `_ACTION_CLAIM` is documented as refusing "any mention of a completed side effect" unless a write receipt exists (`examples/architecture/turnwise_core.py:543-544`). Its regex matches only `rolled back|reverted|paged` and `rollback|revert` near `done|executed|…` (`turnwise_core.py:545-548`). Paraphrases pass, and the run finishes with an action record that says no side effect occurred.

**Reproduction.** Probe `ChallengeProbes.test_adv003_finish_rejects_completed_side_effect_claims_however_worded` (5 of 5 non-control phrasings fail). Inputs for the question "Is checkout healthy right now?", citing a valid `service_health` receipt:
- "I rolled checkout back to d-141, and it is healthy now."
- "I have executed the rollback of checkout; it is healthy now."
- "Checkout was restored to d-141 and is healthy now."
- "I undid the checkout deploy; it is healthy now."
- "I switched checkout back to build d-141; it is healthy."

Control "I rolled back checkout; it is healthy now." is correctly rejected.

**Expected.** `host_validates(FINISH)` returns False for each phrasing. The answer asserts a completed side effect; `host.action_record()` shows no executed write.

**Actual.** All five return True. Action record: "no side effect was requested or executed".

**Relevant source.** `examples/architecture/turnwise_core.py:324-328` (`_claims_unexecuted_action`), `:330-347` (`_check_finish`), `:543-548` (`_ACTION_CLAIM`).

**Impact.** A FINISH is the host's assertion that an answer is acceptable. A user reading `finished` can believe a rollback happened. No write was executed (the write ledger is empty), so the harm is to honesty of terminal status, not to system state. Documented in the code as "a conservative keyword screen", so the team knows it is a screen; the gap is that the advertised rule is broader than the regex.

**Minimum acceptance criteria.**
1. All five phrasings above are rejected by `host_validates(FINISH)` with a message naming the unexecuted side effect.
2. The screen is either semantic (e.g. a deterministic check that the answer asserts an action verb about a registered write tool) or its documented claim is narrowed to the exact regex, with the narrower claim stated in `turnwise_core.py:543-544` and the release note.
3. `test_architecture_core` FINISH claim test gains these phrasings.
4. Existing claim-screen tests (`test_architecture_core.py:252-256`, `:271`) still pass.

---

## 2. A user-requested write can disappear silently instead of being held, clarified, or refused

**Priority:** High (a requested action leaves no receipt, hold, or clarification, and the run can finish with "no side effect was requested").

**Problem.** `requested_writes()` (`examples/architecture/incident_env.py:192-220`) turns a sentence into a write request only if it matches `roll back|revert <service>` exactly, with no negation, condition, or hedging token. Anything else yields an empty set. The code's own comment says such text "would be rejected, never run" (`incident_env.py:198-199`), but a non-matching sentence produces **no receipt at all**. The run then proceeds as if no action were requested.

Four forms lose the request in this pass:
- Single-word spelling `Rollback` (ADV-001): the run finishes with action record "no side effect was requested". The spelling `Roll back` gives a held receipt. Opposite terminal outcomes for the same intent.
- Compound target `Roll back checkout and payments.` (ADV-002): only `checkout` is requested; `payments` is discarded (`re.search` returns the first match per clause).
- Conditional `Is checkout healthy? If it is still down, roll back checkout.` (ADV-016): request set is empty; the run finishes "finished" (OBS-A).
- Interjection `Roll back, please, checkout.` (ADV-017): request set is empty.

**Reproduction.**
```bash
python3 research/haiku55-adversarial/test_adversarial_decisions.py ChallengeProbes.test_adv001_rollback_spelling_gets_the_same_disposition_as_roll_back
python3 research/haiku55-adversarial/test_adversarial_decisions.py ChallengeProbes.test_adv002_compound_rollback_keeps_every_named_target
python3 research/haiku55-adversarial/test_adversarial_decisions.py --observe   # OBS-A, OBS-E
```

**Expected.** Either (a) the request is held for approval, or (b) the run stops with a clarification or a visible "not handled" disposition. In no case should a sentence that asks for a rollback end `finished` with "no side effect was requested". For the compound case, every named target needs the same treatment as a split request.

**Actual.** ADV-001: `finished` and "no side effect was requested"; `Roll back` gives `held`. ADV-002: `{checkout}` vs split `{checkout, payments}`. ADV-016 and ADV-017: empty set, no disposition.

**Relevant source.** `examples/architecture/incident_env.py:163-169` (`_ROLLBACK_REQUEST`, `_NOT_A_PLAIN_REQUEST`), `:192-220` (`requested_writes`), `:325-329` (`action_record`); `examples/architecture/turnwise_core.py:340-341` (`_check_finish` checks only the parsed set); `examples/architecture/policies.py:55-63`.

**Impact.** No write runs (writes are never executed in this demo), so the harm is to disposition and reporting. The request is silently lost and the run's own record denies that it existed. For an incident-response tool, a dropped rollback request is operationally significant even though the system stays safe.

**Minimum acceptance criteria.**
1. Probes ADV-001 and ADV-002 pass as written, **or** the owners record in the spec that the parser vocabulary is 'roll back' and 'revert' only. In that case the test names change and the silent-finish subtests (ADV-001 subtests 2 and 3) still must pass.
2. Any sentence that names a registered write tool with a service, and is not a clear non-request (question, quotation, third-party attribution), produces either a receipt, a `HOLD` for that target, or a `CLARIFY`. A run may not end `finished` while such a sentence exists.
3. `action_record()` lists every write the user named, including those not parsed, or states that some user text was unparsed.
4. Add ADV-016 and ADV-017 as probes once the disposition for conditional requests is specified (currently NEEDS_SPECIFICATION).

---

## 3. A self-contradicting same-turn instruction is turned into an approval request

**Priority:** Medium (held, not executed, but it asks a human to approve an action the user contradicted in the same message).

**Problem.** `incident_env.py:173-174` says: "Conservative: mixed instructions may need clarification, not approval." The withdrawal list (`:181-189`) covers only phrases like "actually no", "never mind", "cancel that". A negated imperative, "Never roll back checkout.", is not on the list, so the positive sentence still produces a request.

**Reproduction.**
```bash
python3 research/haiku55-adversarial/test_adversarial_decisions.py ChallengeProbes.test_adv008_mixed_same_turn_instruction_is_not_turned_into_an_approval_request
```
Input: `Roll back checkout. Never roll back checkout.` Observed `requested_writes` = `{('rollback_deploy','checkout')}`.

**Expected.** No approval request for a turn that contradicts itself (the code's own stated rule). Clarification is acceptable.

**Actual.** An approval hold for `rollback_deploy(checkout)` is produced.

**Relevant source.** `examples/architecture/incident_env.py:173-174` (comment), `:181-189` (`_LATER_WITHDRAWAL`), `:205-220`.

**Impact.** The approval queue receives a request the user retracted in the same message. A reviewer would likely reject it, but the system asked for the approval.

**Minimum acceptance criteria.**
1. `requested_writes("Roll back checkout. Never roll back checkout.")` returns the empty set, or the turn is routed to clarification.
2. A same-turn contradiction for the same target is covered by a test in `test_architecture_write_retractions.py`.
3. Existing withdrawal tests still pass.
4. Scoped retraction ('never mind about payments' cancelling 'checkout', ADV-015) is decided and documented in the same change (currently NEEDS_SPECIFICATION).

---

## 4. Evidence requirements and tool routing use different keyword vocabularies

**Priority:** Medium (safety-neutral for writes; affects whether a checkout answer is checked against checkout evidence and whether a model is called before any evidence is read).

**Problem.** Three keyword lists decide related things and disagree:
- `_CAUSAL_QUESTION` (`incident_env.py:77-79`) decides whether `missing_evidence` requires symptom and change roles. Anything outside it gets no task-scoped check (`:89`, `:278-279`).
- `_DIAGNOSTIC` (`policies.py:23`) decides whether the policy reads evidence first.
- `_STATUS` (`policies.py:24`) and `_STATUS_QUESTION` (`incident_env.py:80`) are separately maintained.

Result (a), the evidence gate (ADV-004): "Why did the checkout deployment increase error rates?" is rejected when cited only against payments; "Did the checkout deployment increase error rates?" is accepted on the same citation. Result (b), the routing (ADV-007): "Did the checkout deploy cause the errors?" reads `error_trend` first; "Did the checkout deployment increase error rates?" calls the heavy model with no evidence.

**Reproduction.**
```bash
python3 research/haiku55-adversarial/test_adversarial_decisions.py ChallengeProbes.test_adv004_causal_paraphrases_get_the_same_evidence_verdict
python3 research/haiku55-adversarial/test_adversarial_decisions.py ChallengeProbes.test_adv007_paraphrases_of_one_diagnostic_question_get_the_same_first_decision
```

**Expected.** Paraphrases of one question get the same evidence requirement and the same first decision. A checkout-specific answer cannot be accepted against payments-only evidence, under any wording the system treats as diagnostic.

**Actual.** As above.

**Relevant source.** `examples/architecture/incident_env.py:77-89`, `:263-305`; `examples/architecture/policies.py:23-24, 40, 103-122, 160-165`.

**Impact.** Wrong-service evidence can support a wrong-service answer; the model is called without evidence for some wordings. Both are quality and cost issues rather than write-safety issues, and the demonstration policy is explicitly "not tuned or evaluated" (`policies.py:12-14`).

**Minimum acceptance criteria.**
1. One shared definition of "diagnostic or causal" used by both the evidence gate and the policy, with a test that paraphrases agree.
2. ADV-004 and ADV-007 pass.
3. A service-specific answer with no role match is not accepted against other-service citations (the `_check_finish` message's own "task-scoped" requirement).
4. Existing evidence-gate tests (`test_architecture_safety_gates.py:33-108`) still pass.

---

## 5. A DIRECT answer can be given to a comparative question that the record does not answer

**Priority:** Medium-low (the answer is a verified value, but it is for a different question; no action is taken).

**Problem.** `policies.py:65-69` returns `DIRECT` whenever no service is named, the intent is `other`, and a `_FACT_CUES` regex matches (`:26-28`). The word `start` is matched without regard to the rest of the question. The policy's comment says "Anything more specific is not hijacked by a keyword" (`:65-66`), which is not what happens.

**Reproduction.**
```bash
python3 research/haiku55-adversarial/test_adversarial_decisions.py ChallengeProbes.test_adv005_non_record_question_is_not_answered_by_a_keyword_matched_record
```
Inputs: `Did the incident start before the deploy?` and `Was the incident started by a deploy?` Both → `DIRECT incident_start`.

**Expected.** Not DIRECT. The question compares the incident start with a deploy time, which the verified record does not contain; the run should clarify or read deploy evidence.

**Actual.** The run ends `answered_directly` with the incident start timestamp.

**Relevant source.** `examples/architecture/policies.py:23, 26-28, 65-69, 160-170`; `turnwise_core.py:309-313, 417-421`.

**Impact.** A question about a deploy is answered with a timestamp and reported as an answered question. No write or model call is involved.

**Minimum acceptance criteria.**
1. DIRECT is only issued when the whole question maps to one verified key (for example, a restricted cue set or an exact match), or when an explicit comparative or causal term is absent.
2. Both ADV-005 inputs produce a non-DIRECT decision.
3. `When did the incident start?` (control ADV-021) still produces DIRECT.

---

## Considered and not proposed

* **Raw HTTP 429 retried by the policy on a non-ledger port (ADV-006).** Reproduced, but the paid path wraps 429 through `ProviderLedger` and `classify_from_wire` (`examples/architecture/provider.py:284-302`) and the transport stop is tested (`tests/test_architecture_provider_readiness.py:607-617`). The gap is confined to non-ledger ports, which are not used for paid calls. Recommend a low-priority hardening note rather than an issue, unless the owners want the policy to stop on any 429 regardless of the port.
* **Lab context `none` overridden and restricted sources in public-request context (ADV-029, ADV-030), and single-action planning in the lab (ADV-031).** These are NEEDS_SPECIFICATION: the owners must first decide what the sensitivity labels and the `none` context mode mean on the local path. Proposing an issue before that decision would encode an assumption.
