# CONTRACTS: Turnwise decision contracts at the base commit

Base commit inspected: `9965daf00ec31c6166905a9632379af0da12adbc` (`main`-line head of this branch, clean tree).
Scope: the two Turnwise code paths present in the repository.

* **Canonical Turnwise Core** — `examples/architecture/` (AGENTS.md names this the canonical demonstration). Its decision vocabulary is `Op`.
* **Lab planner / harness** — `turnwise_lab/core.py`, `turnwise_lab/deciders.py`, `turnwise_lab/runtime.py` (v0.4/v0.5 lab, stdlib only). Its vocabulary is `route` / `path` / `tier` / receipt `status`.

`turnwise_lab/arena.py`, `evaluate.py` and `parity.py` were only **inventoried** (function list), not analysed. See the limitations in RESULTS.md.

Line numbers refer to the base commit. "ENFORCED" means code checks it at runtime. "DOCUMENTED" means only a docstring, comment or AGENTS.md states it. A "MISMATCH" row is a difference between the two.

---

## 1. Decision vocabulary

### 1.1 Canonical (`examples/architecture/turnwise_core.py`)

| Op | Meaning in code | Terminal? | Ref |
|---|---|---|---|
| `DIRECT` | Return a host-verified record; no model | yes | :44, :55 |
| `CALL_TOOL` / `CALL_WORKFLOW` | One registered tool/workflow, executed by host | no | :45-46 |
| `CALL_LIGHT` / `CALL_HEAVY` | Exactly one bounded model call | no | :47-48, :56 |
| `CLARIFY` | Stop: information missing | yes | :49, :55 |
| `HOLD` | Stop: authorisation or evidence missing | yes | :50, :55 |
| `FINISH` | Ask host to accept a model answer candidate | yes | :51, :55 |
| `HANDOFF_AGENT` | **Contrast only** — native agent owns the loop | no | :52 |

Terminal run statuses (`_terminal`, :417-439): `answered_directly`, `finished`, `held`, `needs_clarification`. Non-terminal stops (`_result("stopped")`, :247-275, :256, :265, :275): budget exhausted, too many rejections, halt.

### 1.2 Lab (`turnwise_lab/core.py`, `runtime.py`)

* Route set `ROUTES = {direct, flow, tool, llm}` (core.py:8). Tier set `{small, standard, deep}` (core.py:9).
* Plan `path` ∈ `{direct, flow, tool, llm, hold}` (core.py:65-79; hold set at :135, :137, :146, :148, :150, :183, :194).
* Harness receipt `status` ∈ `{completed, approval_required, blocked, generation_required, error}` (runtime.py:33-44, :93-142).

### 1.3 Mapping to the six conceptual decisions

| Conceptual decision | Canonical | Lab |
|---|---|---|
| 1 Deterministic action | `CALL_TOOL`/`CALL_WORKFLOW` (:262-263); `DIRECT` (:309-313, :417-421) | route `tool`/`flow` (core.py:174-195); `direct` (core.py:168-173) |
| 2 Model for missing reasoning / args | `CALL_LIGHT`/`CALL_HEAVY` (:266-267, :362-382) | route `llm` → `generation_required` (runtime.py:122-133) |
| 3 Escalate to stronger model | No explicit op; light→heavy is a policy choice (policies.py:116-122) | Low route probability → `llm/deep` (core.py:165-167); classifier failure → `llm/deep` (core.py:151-162); low tier probability → `deep` (core.py:196-198) |
| 4 Clarify | `CLARIFY` (:436; policies.py:97-100) | none (no clarify path) |
| 5 Refuse / abstain | `HOLD` (:433-434; host honours it); host refusals are `rejected` receipts (incident_env.py:340-347) | `hold` path + `approval_required` (runtime.py:90-92, :111-115) |
| 6 Terminate | `FINISH` (:422-432), `DIRECT`, `HOLD`, `CLARIFY`; `stopped` on budgets | `completed`, `generation_required`, `error` (runtime.py:136-140) |

---

## 2. Host validation of a policy decision (canonical)

`TurnwiseRuntime.host_validates` (turnwise_core.py:278-322) is the only gate between a policy proposal and anything executed. Checks, in order:

1. Typed `Decision`, non-empty `reason` (:280-283). ENFORCED.
2. Tool/workflow: id registered (:285-287); `kind` matches op (:288-289); arguments is a mapping (:290-291); tool budget > 0 (:292-293); if `adopted_from` is set, it must equal the source proposal's tool and arguments exactly (:294-298). ENFORCED.
3. Model ops and `HANDOFF_AGENT`: model budget > 0 (:301-302); `context` may contain only **executed** receipts (:303-305); `may_propose` must be registered tools (:306-307). ENFORCED.
4. `DIRECT`: refused whenever any user write request exists (:310-311); target must be a verified fact (:312-313). ENFORCED.
5. `FINISH`: `_check_finish` (:314-315, :330-347), see §6.
6. `CLARIFY` / `HOLD`: non-empty message (:316-317); must not claim an unexecuted side effect (:318-319, screen at :324-328); approval claims must match a held receipt (:320-321, incident_env.py:307-323). ENFORCED.
7. **Not checked**: whether `CLARIFY` is warranted, whether `HOLD` is the right disposition, or whether a turn with a requested write may terminate by `HOLD`/`DIRECT`/`FINISH` other than the rules above. MISMATCH with "host owns terminal acceptance" only for FINISH; see §9.

Rejections are counted (`_reject`, :441-448). After `max_rejections=3` (:139) the run stops (:255-256, :264-265). After any rejection the policy's next decision must be a `HOLD` (policies.py:45-48) and `last_rejection` is cleared only by a later accepted decision (turnwise_core.py:258).

---

## 3. Authorisation (write intent and execution)

### 3.1 Write intent is parsed from the user's text only (canonical)

`requested_writes(user_request)` (incident_env.py:192-220) returns `{("rollback_deploy", service)}` only for a sentence that:

* matches `_ROLLBACK_REQUEST` (:163-165): literal `roll back` or `revert` (whitespace required between `roll` and `back`), optional `please`, optional `the`, optional `latest|last|most recent`, then one word `\w+`;
* contains no token from `_NOT_A_PLAIN_REQUEST` (:167-169: `not no nothing never don't do not if unless only ignore should could would whether maybe perhaps suggest* bot assistant said`, `--`, quotes);
* does not end in `?` (:210-211);
* whose `\w+` names a service via `named_services` (world.py:173-179, aliases world.py:21-22).

If a later same-turn withdrawal matches `_LATER_WITHDRAWAL` (:181-189), the **whole set is cleared** (`return frozenset()`, :217-218). Documented intent: "Ambiguous scope fails closed rather than manufacturing an approval" (:216) and "Anything else yields no authority (the write would be rejected, never run)" (:198-199). The second statement is DOCUMENTED, and the stated fallback ("rejected") is **not** what happens: a non-matching sentence produces no receipt at all (see ADV-001, 002, 016, 017).

### 3.2 Writes are never executed in this demo

* `IncidentHost._execute` (incident_env.py:346-347): a side-effect tool is only sent to the harness if `(tool, arg) ∈ requested_writes`; otherwise the receipt is `rejected` with reason "write was not requested by the user; a proposal cannot authorise a side effect".
* Harness gating: `allow_writes=False` plus `granted_write_actions` plus `approved_actions` (runtime.py:111-115) → `approval_required`. Here the handler is never reached.
* Even if reached, the world's write handler records to `write_ledger` and raises (world.py:274-277).
* Status of a requested write: `held_for_approval` (incident_env.py:355). ENFORCED. Existing tests: write_retractions:66-71, safety_gates:129-134.

### 3.3 Lab authorisation

* `Plan.approval_required` is set when a side-effect capability is not in `request.approved_actions` (core.py:182-184, :193-195). ENFORCED at planning.
* Harness: a `Plan` is untrusted; the harness re-checks registration, presentation (runtime.py:102-106), side-effect metadata match (:107-108), permission (:109-110), and write grants (:111-115). ENFORCED.

---

## 4. Tool execution preconditions

| Precondition | Canonical | Lab |
|---|---|---|
| Registered | `TOOLS_BY_ID` (incident_env.py:337-339) and `host_validates` (turnwise_core.py:285-287) | `self.actions.get` + presented check (runtime.py:102-106) |
| Argument shape | Exactly one key equal to `spec.param` (incident_env.py:369-370); service enum (:372-373); query 1-200 chars (:374-375) | Not applicable (`Plan` carries no arguments) |
| Permission | — (identity fixed: `read`, `write` at incident_env.py:242) | `required_permission` in identity (runtime.py:109-110) |
| Budget | Host: `len(receipts) >= 8` → rejected (incident_env.py:233, :342-343). Runtime: `tool_calls` budget 6 (turnwise_core.py:137-139, :292-293) | none |
| Duplicates | Policy only: `attempted()` blocks repeated identical reads (turnwise_core.py:171-172; policies.py:58, :107, :132). **The host does not dedupe** (see ADV-027). | none |
| Adoption of model proposal | Policy declines unregistered, side-effect, already-attempted, or budget-exhausted proposals (policies.py:124-137). Host re-checks the adoption match (turnwise_core.py:294-298) | none |
| Side-effect metadata | Policy trusts `ToolSpec.side_effect` from the registry | Harness compares presented vs registered (runtime.py:107-108) |

---

## 5. Clarification and escalation conditions

* **Canonical CLARIFY**: policy issues it when `services` is empty after all earlier branches (policies.py:97-100). Host requires a message and screens it, but does **not** verify missingness (turnwise_core.py:316-321).
* **Service matching** is exact-token alias matching (world.py:173-179; aliases world.py:20-22). `checkouts` (plural) is not recognised → `CLARIFY` (see ADV-010).
* **Canonical escalation**: `CALL_LIGHT` for `status` intent, `CALL_HEAVY` otherwise (policies.py:116-122). There is no escalation-on-failure branch; a failed call is an `invalid` observation (turnwise_core.py:368-374).
* **Lab**: classifier exception, invalid JSON-like judgment, or invalid enum → `llm/deep` with no tool and no context (core.py:151-162; test_core.py:85-92). Low route probability → `llm/deep` (core.py:165-167). Missing tool or flow candidate → `llm/deep` (core.py:175-178, :186-189).

---

## 6. Deterministic execution conditions

### 6.1 Canonical DIRECT

Policy issues DIRECT only when: no services named, intent is `other`, and a `_FACT_CUES` regex matches a key present in `verified_fact_keys` (policies.py:65-69; cues :26-28; intent :160-165). The question is answered from the host record (turnwise_core.py:417-421) with no model. DIRECT is refused while any user write request is outstanding (turnwise_core.py:310-311).

Keyword cues are substring-level (`start|started|began`, `severity`, `commander`, ...), so a question that *mentions* a record word can be answered with that record (see ADV-005).

### 6.2 Lab DIRECT

Only a host-verified `direct_answer` is returned; a `direct` route without one escalates to `llm/deep` (core.py:168-173; test_core.py:121-124). The bypass (core.py:139-142) skips classification entirely.

---

## 7. Failure and termination semantics

* Step loop: `range(1, max_steps+1)` (turnwise_core.py:248); exhaustion → `stopped` (:275).
* Model call: count is incremented **before** the call (:364), so failed calls count against budget (good; required by AGENTS "count every policy call"). Exceptions become observations, not crashes (:368-371), except a `RunHalt` in the chain (:369, :498-501) which stops the run.
* **HTTP 429**: `rate_limited` is set only when the exception **is** a `ModelCallFailed` with category `provider error HTTP 429` (turnwise_core.py:370). The text classifier `describe_failure` also recognises any exception with `status_code` 429 (:520-521), but it does **not** set the flag. The policy halts only on the flag (policies.py:74-75). For the OpenAI Agents and LlamaIndex ports, the typed error is produced from the wire record (provider.py:284-302, `classify_from_wire`) **only when a `ProviderLedger` is passed** (openai_agents/turnwise.py:63-66; live_smoke.py:93, :103). SDK retries are disabled (`max_retries=0`: openai_agents/models.py:61-66; llamaindex/models.py:63). The paid path is therefore protected at the ledger/transport layer (AGENTS "first-429 stop"; provider_readiness tests at tests/test_architecture_provider_readiness.py:607-617). The policy-level stop is not protected for a raw exception on a non-ledger port (see ADV-006).
* Lab harness: any handler exception → `status="error"`, reason `handler_raised_<Type>` (runtime.py:136-140). Fail closed.

---

## 8. Outcome and receipt requirements

### 8.1 Model outcome (canonical)

`parse_outcome` (turnwise_core.py:551-581): `kind` ∈ `answer_candidate|tool_proposal|needs_evidence` (:57); a `tool_proposal` needs a string tool and a JSON **object** of string-keyed arguments (:567-576); `tool` may appear only on a proposal (:577-578); an empty `answer_candidate` is invalid (:579-580). Malformed → `kind="invalid"`, never an answer. ENFORCED.

`provider_rate_limited` is set by the host adapter and "never parsed from model text" (:121). ENFORCED by construction.

### 8.2 FINISH acceptance (canonical) — `_check_finish` (turnwise_core.py:330-347)

In order:
1. Candidate exists and is an `answer_candidate` produced in this run (:331-333).
2. Candidate cites at least one receipt (:334-335).
3. Every cited id is in `shown` and is an **executed** receipt (:336-339).
4. No outstanding user write request (:340-341).
5. Claim screen `_claims_unexecuted_action` on the answer text (:342-343; screen :324-328; regex turnwise_core.py:545-548).
6. Task-scoped evidence `missing_evidence` (:344-346; incident_env.py:263-305).

`missing_evidence`:
* Required roles come from keyword regexes on the **task**: causal → `{symptom, change}` (incident_env.py:77-79, :85-86); status → `{current_state}` (:80, :87-88); otherwise **no roles** (:89 returns `()`), and therefore no task-scoped check (incident_env.py:278-279 returns `()` early).
* For each user-named service and role, a valid cited, executed receipt with the right tool role, service argument, fact key and minimal payload shape is required (contracts :280-282; shape :295-297; malformed flag :303).
* Conflicting executed payloads for the same role/service fail even if only one is cited (:299-301).

Documented limit, stated in the code: "Causal correctness is NOT verified" (turnwise_core.py:430-431) and "structural demo gate … not semantic verification" (incident_env.py:270-272).

### 8.3 Claim screen

`_ACTION_CLAIM` (turnwise_core.py:545-548) matches `rolled back|reverted|paged` and `rollback|revert` followed within 40 characters by `complete|done|executed|...|succeeded`. Its own comment: "a conservative keyword screen, not a semantic check" (:325-326) and "any mention of a completed side effect is refused" (:543-544). Pass only when an executed write receipt exists (:328, :343). **Mismatch**: the docstring promises any mention is refused; the regex misses many phrasings (see ADV-003).

### 8.4 Receipts and action record

* `Receipt` fields and `executed` property (incident_env.py:104-119); `for_model` is the only text a model sees (:124-128).
* `action_record()` is computed from receipts only (incident_env.py:325-329); the message "no side effect was requested or executed" is the authoritative run-level statement. Note it is also emitted when a write **was requested in prose but never parsed** (ADV-001).
* Lab receipt `audit_digest` is "an integrity fingerprint for reproduction, NOT a signed audit log" (runtime.py:50-57, labelled as such).

---

## 9. Documented intent versus enforced behaviour

| # | Documented (where) | Enforced? | Status |
|---|---|---|---|
| D1 | AGENTS invariant 3: writes are held for approval, never executed | Yes (incident_env.py:346-355; world.py:274-277) | Consistent |
| D2 | Proposals are never authority (turnwise_core.py:73; incident_env.py:346-347) | Yes | Consistent |
| D3 | "Any mention of a completed side effect is refused unless a host receipt shows an executed write" (turnwise_core.py:543-544) | Only for the regex in :545-548 | **MISMATCH** (ADV-003) |
| D4 | "Anything else yields no authority (the write would be rejected, never run)" (incident_env.py:198-199) | Never run: yes. Rejected: **no receipt** is created for a sentence that fails the parser | **MISMATCH** (ADV-001, 002, 016, 017) |
| D5 | "Ambiguous scope fails closed" (incident_env.py:216) | Fails closed on authority, but not on disposition: the run may finish without a hold | Partial; NEEDS_SPECIFICATION (ADV-015) |
| D6 | "Mixed instructions may need clarification, not approval" (incident_env.py:173-174) | No: a same-turn contradiction produces an approval hold | **MISMATCH** (ADV-008) |
| D7 | "Anything more specific is not hijacked by a keyword" (policies.py:65-66) | No: a mention of "start" triggers DIRECT | **MISMATCH** (ADV-005) |
| D8 | "Cheap evidence first" (policies.py:103) | Diagnostic routing uses a different keyword set from the causal evidence gate | **MISMATCH** (ADV-007) |
| D9 | "Causal" questions require symptom and change evidence (incident_env.py:77-79) | Only if the wording matches the list; otherwise no task-scoped check (incident_env.py:89, :278-279) | **MISMATCH** (ADV-004) |
| D10 | First-429 stop for real provider calls (AGENTS) | Transport stop and typed 429 when a ledger is present; policy halt only on the typed flag | Partially enforced (ADV-006, non-ledger path) |
| D11 | "Honour the plan's context selection" (runtime.py:126) | Plan with no selection is replaced by "related" sources (runtime.py:129-133) | NEEDS_SPECIFICATION (ADV-029) |
| D12 | External decider must not see protected source bodies (core.py:88-94; test_core.py:61-70) | Yes for external only. Local context packs restricted sources for public requests | NEEDS_SPECIFICATION (ADV-030) |

---

## 10. Existing negative tests (what their assertions actually check)

Each row says what the assertion verifies, not the test name.

**`tests/test_architecture_write_retractions.py`**
* :8-16 — plain imperatives yield exactly the expected `(tool, service)`. Strong for the listed phrasings only.
* :18-26 — question-mark endings yield the empty set. Strong.
* :28-42 — ten later-withdrawal phrasings yield the empty set. Strong for the list; no test for scope.
* :44-53 — mentions and other-person attributions yield the empty set. Strong.
* :55-64 — host refuses a write for a retracted or question-form request; `write_ledger` stays empty. Strong.
* :66-71 — positive request gives `held_for_approval`, ledger empty. Strong.
* **Not covered**: spelling `Rollback`, compound targets, mid-sentence `please`, conditional `if`, contradiction, retraction scope.

**`tests/test_architecture_safety_gates.py`**
* :17-30 helper `check_finish` (builds real receipts, calls `host_validates`).
* :33-47 causal needs symptom and change for the same service; `Why` phrasing. Strong for the `Why` wording only.
* :49-79 premature FINISH by a stubborn policy is rejected; the run ends `held`; ledger empty. Strong.
* :81-87 causal evidence about another service rejected. Strong for the `Why` wording.
* :89-94 multi-service coverage required. Strong.
* :96-101 status answer cannot use change evidence. Strong.
* :103-108 unresolved referent blocks FINISH. Strong.
* :112-121 later withdrawals (five phrasings). Strong for the list.
* :129-134 host checks the target even if a proposal names the right tool. Strong.
* :136-152 DIRECT and FINISH cannot silently drop a requested write (both phrasings tested recognised). Strong for recognised requests only.
* :154-174 approval claims must match a held receipt. Strong.
* :176-182 malformed tool proposal is `invalid`. Strong.

**`tests/test_architecture_evidence_receipts.py`**
* :27-29, :31-36, :38-45, :47-54 — wrong-service, malformed and forged-role receipts do not count. Strong.
* :56-66 — conflicting receipts fail even when one is cited. Strong.
* :68-72 — identical repeats are not a conflict. Strong.
* :74-82 — empty deployment list is valid. Strong.
* :84-94 — runtime FINISH rejected on invalid cited payload. Strong.

**`tests/test_architecture_core.py`** (not in the requested list but it contains the FINISH claim tests)
* :249-258 — FINISH with `unexecuted action` phrasings is rejected: `rolled back`, `rollback ... complete`, `reverted`, `rolled-back`, `Rollback executed`. Strong for these five; does not cover `rolled checkout back`, `executed the rollback`, `restored`, `undid`, `switched ... back`.
* :153-158 — claim screen for a model's prose. Strong for the listed phrasing.
* :271 — a `HOLD` message claiming a rollback is refused. Strong for one phrasing.

**`tests/test_architecture_parity.py`**
* :26-46 — same answer and tool counts for both frameworks; sockets denied. Mechanism only; says nothing about decisions beyond equal output.
* :48-79 — tool schemas agree across SDKs. Mechanism only.
* Skipped without SDKs; ran and passed here after `pip install -r examples/architecture/requirements.txt`.

**`tests/test_core.py`** (lab)
* :23 — write not executed on model advice. Strong.
* :61-70 — external summaries exclude sensitive sources. Strong for external; nothing for local.
* :94-97 — classifier error → no tool. Strong.
* :121-124 — `direct` needs a verified host answer. Strong.
* :134-146 — obvious PII or token blocks external calls. Strong for the regex only.

---

## 11. Not analysed in depth

* `turnwise_lab/arena.py` (936 lines; frozen v0.5 experiment, AGENTS): inventoried only. Its `plan_calls`, `resolve_entities`, `stateless_route` and `_fetch_missing` (lines 131-160, 282-316) were not probed.
* `turnwise_lab/evaluate.py` (replay, `_deep_plan`, `_simple_rules`): inventoried only.
* `turnwise_lab/parity.py` (`audit`, :32): inventoried only; its manifest checks were not probed.
* `deciders.py`: `JevDecider` requires an optional SDK and a live provider; not executed (no network allowed). `FixtureDecider` is exercised implicitly through the probes' `_Fixed`.
