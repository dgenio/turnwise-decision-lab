# Issue #55 — action-scoped modules: opt-in offline exhibit and study design

**Status: developer implementation for review, NOT an adopted architecture, performance finding, production guard, or authorization to run a provider.** Owner's hypothesis and boundaries: [#55](https://github.com/dgenio/turnwise-decision-lab/issues/55). Existing control exhibit: [#49](https://github.com/dgenio/turnwise-decision-lab/issues/49) / merged [PR #51](https://github.com/dgenio/turnwise-decision-lab/pull/51).

## What is actually new

- Pre-authored JSON manifest at `examples/architecture/instruction_modules.v2.json`, version `turnwise.action-modules.v2`. Each module has exactly an ID, the model operations it applies to, a mandatory flag, fixed instruction text and its provenance. The complete manifest bytes and each included block's text are SHA-256 hashed in the audit. Only the checked-in manifest supplies instruction text.
- `context_modules.py` validates the manifest, refusing unknown fields, and gives a model operation its mandatory blocks, then the requested ones in request order. **A selection that does not fit the byte limit is refused before any model call; no block is ever dropped silently.** Every block left out is recorded with its reason (`not_requested` or `different_operation`).
- `scoped_runtime.py` is an *opt-in subclass* of the already merged `TurnwiseRuntime`. It checks module selection via the **existing host validation step before a model call**, then adds selected blocks to the next operation's *model input packet*. Its audit records both loaded and excluded instruction blocks, evidence receipts and tool proposal visibility.
- Existing host action authorization, approval holds, step limits, response receipts and `FINISH` citation checks stay where they are. The policy still gets control after every model observation. The module selector cannot execute tools or authorize side effects.
- Default native SDK and Turnwise paths, plus historical frozen files, are **unchanged**. This is a prospective probe, not an additional general agent framework.

### Important limitations

The byte budget is **only UTF-8 bytes of instruction-module texts**. It does **not** cover the system prompt, JSON packet, tool schemas, selected evidence, user text, provider chat templates or model tokenization. It must never be represented as a hard provider token limit or a cost saving. Full prompt/token budget and mandatory context overflow remain [#16](https://github.com/dgenio/turnwise-decision-lab/issues/16). The pre-authored blocks are passed as *packet data*, not privileged system instructions: a strong model is not guaranteed to comply. Host authority stays independent.

The default selector uses the **next model operation**, plus whether that step proposes a tool: `CALL_HEAVY` → `investigate-cause`; `CALL_LIGHT` with proposal scope → `extract-arguments`; other `CALL_LIGHT` → `summarize-evidence`. A selector may request several blocks, but none in this exhibit does, and **no claim is made that this selector chooses well**. No task-family semantic classifier is included.

### Simplified on 2026-11-24 (manifest v2)

The v1 manifest also declared block dependencies, mutual conflicts and priorities, and three blocks (`prepare-user-update`, `concise-mode`, `expanded-mode`) to exercise them. No path ever reached that machinery. Every dependency pointed at a block that was already mandatory, the three extra blocks were never requested, and the largest real selection (657 bytes, on the light extraction path) stayed below the 1024-byte limit. Dependency closure, cycle detection, conflict resolution, priority ordering and "drop an optional block on overflow" therefore ran only under their own tests. They were removed, with the three blocks. The five blocks that are used kept byte-identical text, and every model packet on the demo paths is unchanged, including each block's SHA-256; in the audit, only the manifest version and hash differ, and the excluded list no longer names the three removed blocks. Overflow now has one rule: refuse before the model call. The v1 manifest and selector are in git history (last at commit `e86eb43`). If a future study needs composition, add it with the first path that uses it.

## Three runnable traces

```bash
python -m examples.architecture.action_context_demo
python -m unittest discover -s tests -p 'test_architecture_context_modules.py'
```

All use the existing **synthetic incident host** and a framework-free, **scripted** model double. They perform no inference, no network operations and no writes.

| Path | Host/policy control | Model | Instruction modules | Expected outcome |
| --- | --- | --- | --- | --- |
| Verified incident severity | `DIRECT` from authoritative host record | **Zero calls** | None | `answered_directly` |
| Runbook lookup ("What do our runbooks say about checkout errors?") | Light structured `tool_proposal` of a free-text `search_docs` query → policy adopts only a query-parameter read → host validates and executes it → light response citing the receipt | Scripted *light* calls | `extract-arguments`, then `summarize-evidence`; mandatory modules on both | `finished` |
| Checkout deployment investigation | Host symptom/change reads → strong-tier typed model proposal → host checks `validate_config` → strong-tier candidate → host-checked `FINISH` | Scripted *heavy-tier* calls | `investigate-cause` plus mandatory modules | `finished` |

The light path lets a model formulate exactly one free-text argument (a search query). It may **not** resolve a service referent: service targets are parsed by the host from the user's own words, and the host's `FINISH` evidence gate relies on that. An earlier version of this exhibit mapped the alias `check-out` to `checkout` via the model; once merged with the host evidence gate from PR #64 the host correctly refused to accept that answer ("unresolved service target"), and a regression now pins that a model-resolved alias ends in `CLARIFY`. A request with nothing to look up yields `CLARIFY`. The example does **not** show that a model was necessary or economically sensible for the query; a deterministic query template might do as well. The strong-tier label refers to the *chosen operation*, not proof of real capable-model reasoning.

Developer regressions cover overflow, request order and duplicates, malformed or unsupported manifests, unknown or incompatible names, sending only the host-validated selection, no-model execution, missing referent, silent evidence omission, preserved default packet, and the continued host write gate. Their outcomes are development feedback, **not held-out research evidence**.

### Minimal step-by-step mechanism traces (scripted, not measured)

```text
DIRECT (verified incident severity):
  policy DIRECT severity -> host verified record -> answered_directly
  model calls: 0 | loaded/omitted modules: none needed

LIGHT (runbook lookup; model formulates one free-text query):
  policy CALL_LIGHT [host-authority, receipt-grounding, extract-arguments]
     proposal tools: search_docs only
  scripted model -> typed search_docs(query="checkout error rate runbook") proposal
  policy CALL_TOOL (adopts the proposal) -> host executes read r1
  policy CALL_LIGHT [host-authority, receipt-grounding, summarize-evidence]
     evidence: r1; proposal tools: none
  scripted model -> answer_candidate cites r1 -> policy FINISH
  excluded each time: the other light task's instructions (not_requested)
     and the heavy-only module (different_operation)

HEAVY (deployment diagnosis):
  policy CALL_TOOL error_trend -> host r1
  policy CALL_TOOL recent_deploys -> host r2
  policy CALL_HEAVY [host-authority, receipt-grounding, investigate-cause]
     evidence: r1, r2; both light-only modules excluded (different_operation)
  scripted model -> typed validate_config proposal
  policy CALL_WORKFLOW -> host executes registered read r3
  policy CALL_HEAVY with same modules + evidence r1/r2/r3
  scripted model -> answer_candidate cites executed receipts -> FINISH
```

These sequences are developer-authored predictions enforced by the offline tests, not behavioral measurements from a hosted model. Audit data records all non-included module IDs and reasons; it does **not** establish that the chosen subset contained every fact a real model needed.

## Prospective 2 × 2 ablation (not executed)

| | Fixed instruction/evidence/tool context | Action-scoped pre-authored context |
| --- | --- | --- |
| **Native capable agent** | A: native framework baseline | B: native + scoped context |
| **Typed per-step controller** | C: Turnwise Core, standard context | D: Turnwise Core + scoped context |

This adapter only probes the D *mechanism*. A working B (dynamic context applied fairly to the same native framework), full-context tool-schema parity and evaluations **do not exist yet**. Crucial nulls: native agent + short frozen checklist prompt (A+P, [#43](https://github.com/dgenio/turnwise-decision-lab/issues/43)), native context/tool search and minimal host rules + same capable fallback. A simple host-rule competitor that matches D is a valid negative result.

**Before executing new locked tasks:** use [#9](https://github.com/dgenio/turnwise-decision-lab/issues/9) as the only prospective benchmark gate. Independently author/adjudicate new multi-turn tasks; preserve frozen v0.5/v0.6/v0.7 studies. Pre-register versions/hashes, same underlying capable model and permission principal, tool/schema/evidence inventories, step/cost ceilings, full measured tokens (decisions, retrieval, generation and tool outputs), critical-path wall clock, variance/caching, referent and action-intent loss, semantic quality rubrics, critical failure thresholds, non-inferiority margin/power and stop rules. Include ambiguity, stale evidence, long-range evidence, multi-intent, hostile tool text, approval and fallback preserving tool capability. Report exclusion reasons on every operation.

**Primary decision:** end-to-end correct *authorized* completion, critical errors and action-intent preservation. If quality parity is unproven, do not infer efficiency advantages. Separate treatment effects of control, context and interaction; report null/negative results and full costs, not just call counts. Any live model execution requires its **own** explicit owner approval, independently of earlier consumed smoke authorization or the proposed PR #60.

## Review and merge boundary

- Run `python -m unittest discover -s tests` plus the existing CI architecture jobs; skipped framework tests must still satisfy the existing job contract.
- Confirm default `TurnwiseRuntime` packets and sample outputs remain byte-identical; no historical evidence touched.
- Review the pre-authored text for safe provenance and the side-effect permission boundary. Module scope does not upgrade model instructions into host authority.
- The mechanism is merged as an opt-in exhibit. Whether action-scoped context helps is **not** established: the 2 × 2 ablation above is an arm of the prospective study in [#9](https://github.com/dgenio/turnwise-decision-lab/issues/9). Do not declare victory or merge other experimental branches implicitly.
