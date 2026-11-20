# Open-PR consolidation and evidence gates (2026-11-20)

**Status:** engineering decision record, not release approval, model-spend permission, or a new experimental result. The canonical architecture is the framework-neutral `examples/architecture/turnwise_core.py` on `main`. Historical v0.6/v0.7 scores, traces, freezes and graders must not be retroactively altered.

## Immediate disposition

| PR | Disposition | Condition before implementation/merge |
|---|---|---|
| [#57](https://github.com/dgenio/turnwise-decision-lab/pull/57) | Supersede with current documentation | Keep the observed ten HTTP 429 responses and the lack of real model outputs explicit; preserve useful AGENTS guidance |
| [#60](https://github.com/dgenio/turnwise-decision-lab/pull/60) | Hold owner-triggered second smoke | Verify actual API project model entitlement/quota and billing capacity; merge is not dispatch; never bypass existing one-shot tags; one US$2 **estimated** cap per newly authorized attempt |
| [#31](https://github.com/dgenio/turnwise-decision-lab/pull/31) | Extract hard budget invariants | Explicit overflow/unknown counts, exact whole prompt where tokenizer exists, no safety-instruction removal, visible omitted evidence; reconcile native handoff limits from #37 |
| [#37](https://github.com/dgenio/turnwise-decision-lab/pull/37) | Source of P0 safety tests/contracts | One host authority boundary; typed model outcome is an observation, not a tool authorization; capability-preserving escalation; host receipt-grounded action status |
| [#44](https://github.com/dgenio/turnwise-decision-lab/pull/44) | Focused remote-adapter hardening | Atomic reservations and unknown liabilities remain **per process**; do not call it a provider billing cap or close [#17](https://github.com/dgenio/turnwise-decision-lab/issues/17) |
| [#46](https://github.com/dgenio/turnwise-decision-lab/pull/46) | Port unique v0.8 host-boundary cases, not second host | No lexical synthetic write approvals, no assistant/tool-owned target authority, no direct execute bypass; preserve novel tests and Level C pilot specification |
| [#6](https://github.com/dgenio/turnwise-decision-lab/pull/6) | Frozen exploratory v0.6 exhibit, HOLD | Do not merge wholesale or claim efficiency / quality with a capable model |
| [#38](https://github.com/dgenio/turnwise-decision-lab/pull/38) | Frozen exploratory v0.7 exhibit, HOLD | Do not merge wholesale or rescore L56 and other now-seen failures; preserve the four falsified predictions |

## Canonical integration order

1. **Documentation truth:** reconcile the first paid attempt with its observed HTTP 429s; do not overwrite this with the older #57 snapshot.
2. **One host contract:** define the distinction between policy decisions, typed model proposals, validated host actions, approval holds and *executed* actions. Check both normal and direct execution boundaries. No model- or host-inferred write may be presented as a user request.
3. **One budget contract:** explicit model-call, prompt, output and total-run limits; unknown token counts fail closed for paid inference; exact model-specific prompt counts when available; include handoffs and cached tokens in accounting. Independent steps must not produce non-atomic cost reservations.
4. **Extract narrow PRs against `main`:** prefer independently testable changes in `examples/architecture/` over copying the entire experimental `turnwise_lab/agent/` or `v08/` runtimes. Keep old study branches and fixtures untouched.
5. **Tests before claims:** add new, independently authored adversarial requests for wrong-target actions, retractions, compound read/write, direct execution bypass, user-vs-assistant provenance, missing evidence, malformed typed outcomes and unknown model usage; run full offline matrix and unchanged regeneration checks.

## Prospective Level C experiment ([#9](https://github.com/dgenio/turnwise-decision-lab/issues/9))

Pre-register new multi-turn **sessions** and a second domain, not scripts with pasted history only. At minimum compare:
- A: native capable agent with tools and same host-side permission checks;
- A+P: the same agent with a fixed evidence checklist in its system prompt;
- A+G: the same agent with an external exit-contract gate;
- A+P+G: the combined effect;
- R+G: deterministic host/rules plus a capable fallback;
- C: Turnwise Core per-step policy with the same capable fallback.

Treat dynamic predefined context-block selection as a **separate ablation**, including full permitted context and provider-native tool search where supported. Do not attribute schema savings or omitted controller costs to a learned policy.

Freeze a quality/non-inferiority margin, critical safety ceilings, efficiency threshold, model/version, prices, task-author and independent grading procedure **before** the locked run. Use human adjudication for high-severity errors. A brief provider compatibility smoke is not an end-to-end quality, cost or latency benchmark.

## Release and closure gates

- Successful offline CI is necessary but **not** approval of scientific claims.
- New code must not change recorded historical traces, hashes, adjudications or pre-registered predictions.
- Do not label a lexical detector or in-process proposal scope as an authentication/security boundary.
- A paid attempt needs explicit owner authorization for its specific model, cap and dispatch, verification that the provider account can serve the model, and strict stop after the first rate-limit response.
- Close superseded PRs only after checking that their unique tests/invariants and documentation have been preserved or explicitly abandoned with rationale.
- **GO** only with comparable quality and bounded major/critical failures at the pre-agreed thresholds; otherwise **HOLD**, **SHRINK** to an evidenced smaller component, or **STOP**. A negative result is publishable evidence.
