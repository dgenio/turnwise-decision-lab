# Issue #55 — action-scoped modules: opt-in offline exhibit and study design

**Status: developer implementation for review, NOT an adopted architecture, performance finding, production guard, or authorization to run a provider.** Owner's hypothesis and boundaries: [#55](https://github.com/dgenio/turnwise-decision-lab/issues/55). Existing control exhibit: [#49](https://github.com/dgenio/turnwise-decision-lab/issues/49) / merged [PR #51](https://github.com/dgenio/turnwise-decision-lab/pull/51).

## What is actually new

- Pre-authored JSON manifest at `examples/architecture/instruction_modules.v1.json`, version `turnwise.action-modules.v1`. Each module has an ID, explicit operation applicability, fixed instruction text, dependency IDs, conflict IDs, mandatory flag and deterministic priority. The complete manifest bytes and each included block's text are SHA-256 hashed in the audit. Only the checked-in manifest supplies instruction text.
- `context_modules.py` validates references, cycles, conflicting declarations and operations, then compiles mandatory dependency closures first. **Mandatory overflow is rejected; it never silently drops required blocks.** Requested optional modules are selected by priority, with conflicting/oversized omissions explicitly recorded.
- `scoped_runtime.py` is an *opt-in subclass* of the already merged `TurnwiseRuntime`. It checks module selection via the **existing host validation step before a model call**, then adds selected blocks to the next operation's *model input packet*. Its audit records both loaded and excluded instruction blocks, evidence receipts and tool proposal visibility.
- Existing host action authorization, approval holds, step limits, response receipts and `FINISH` citation checks stay where they are. The policy still gets control after every model observation. The module selector cannot execute tools or authorize side effects.
- Default native SDK and Turnwise paths, plus historical frozen files, are **unchanged**. This is a prospective probe, not an additional general agent framework.

### Important limitations

The byte budget is **only UTF-8 bytes of instruction-module texts**. It does **not** cover the system prompt, JSON packet, tool schemas, selected evidence, user text, provider chat templates or model tokenization. It must never be represented as a hard provider token limit or a cost saving. Full prompt/token budget and mandatory context overflow remain [#16](https://github.com/dgenio/turnwise-decision-lab/issues/16). The pre-authored blocks are passed as *packet data*, not privileged system instructions: a strong model is not guaranteed to comply. Host authority stays independent.

The default selector uses the **next model operation**, plus whether that step proposes a tool: `CALL_HEAVY` → `investigate-cause`; `CALL_LIGHT` with proposal scope → `extract-arguments`; other `CALL_LIGHT` → `summarize-status`. The manifest also supports multiple requested modules (e.g., investigation **and** a user update) and conflicting modules, but **no claim is made that this selector chooses well**. No task-family semantic classifier is included.

## Three runnable traces

```bash
python -m examples.architecture.action_context_demo
python -m unittest discover -s tests -p 'test_architecture_context_modules.py'
```

All use the existing **synthetic incident host** and a framework-free, **scripted** model double. They perform no inference, no network operations and no writes.

| Path | Host/policy control | Model | Instruction modules | Expected outcome |
| --- | --- | --- | --- | --- |
| Verified incident severity | `DIRECT` from authoritative host record | **Zero calls** | None | `answered_directly` |
| `check-out` alias health | Light structured `tool_proposal` → policy binds explicit alias → host validates `service_health(checkout)` → light response with receipt | Scripted *light* calls | `extract-arguments`, then `summarize-status`; mandatory modules on both | `finished` |
| Checkout deployment investigation | Host symptom/change reads → strong-tier typed model proposal → host checks `validate_config` → strong-tier candidate → host-checked `FINISH` | Scripted *heavy-tier* calls | `investigate-cause` plus mandatory modules | `finished` |

The alias case is deliberately small: `check-out` appears explicitly in the original user request. An ungrounded service name yields `CLARIFY`; a model-proposed service must not become authority merely because it parses. The light-extraction example does **not** show that extraction was necessary or economically sensible; for an explicit exact ID, deterministic extraction should win. The strong-tier label refers to the *chosen operation*, not proof of real capable-model reasoning.

Developer regressions cover mandatory overflow, optional overflow, dependencies, conflicts, multi-label selection, manifest cycles, unknown names, no-model execution, missing referent, silent evidence omission, preserved default packet, and the continued host write gate. Their outcomes are development feedback, **not held-out research evidence**.

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
- Keep the issue open until comparators and prospective results exist; do not declare victory or merge other experimental branches implicitly.
