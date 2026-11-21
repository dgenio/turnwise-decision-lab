# Documentation index

Start with the [README](../README.md). For what is current, held or historical, see [release status](release-status.md). Contributors and coding agents: [AGENTS.md](../AGENTS.md).

**Status labels** used across this repository: **Implemented and tested** · **Demonstrated with simulated inference** · **Experimentally measured** · **Proposed** · **Not tested** · **Held / inconclusive** · **Rejected / falsified** · **Historical** (accurate for its date, superseded since).

## The idea

| Document | Status | Read it for |
|---|---|---|
| [per-step-execution-hypothesis.md](per-step-execution-hypothesis.md) | Proposed (canonical research question) | The hypothesis, candidate contract, competing mechanisms, null and kill criteria |
| [why-this-exists.md](why-this-exists.md) | Proposed | Motivation, what would be publishable, what would falsify it |
| [comparators.md](comparators.md) | Snapshot 2026-11-18 | Prior art, routers and native features, name collision |
| [adaptive-agent-execution-pattern.md](adaptive-agent-execution-pattern.md) | Proposed (related, earlier framing) | Framework-neutral "AAE" pattern; the per-step hypothesis is now the primary research object |
| [architecture-fit-audit-2026-11-18.md](architecture-fit-audit-2026-11-18.md) | Historical audit + 2026-11-19 owner decision | Why Turnwise Core (policy keeps control) and `HANDOFF_AGENT` (native agent takes control) are separate architectures |

## The code

| Document | Status | Read it for |
|---|---|---|
| [examples/architecture/README.md](../examples/architecture/README.md) | Demonstrated with simulated inference | The runnable OpenAI Agents SDK and LlamaIndex demonstration: traces, host checks, parity notes, limits |
| [framework-integration-roadmap.md](framework-integration-roadmap.md) | Proposed; SDK lines updated 2026-11-19 | Integration seams in LangGraph, OpenAI Agents SDK, LlamaIndex and Pipecat |
| [reference-adapter-contract.md](reference-adapter-contract.md) | Proposed (design contract, no adapter) | Checklist for a provider-neutral adapter |
| [action-scoped-modules-issue55.md](action-scoped-modules-issue55.md) | Demonstrated with simulated inference (opt-in exhibit); benefit not tested | Pre-authored, versioned instruction blocks selected per next operation; three offline paths; the prospective 2 × 2 ablation |
| [core-provider-input-budget-2026-11-20.md](core-provider-input-budget-2026-11-20.md) | Implemented and tested (offline) | The conservative whole-request input bound enforced before any provider request, and what it does not guarantee |
| [model-backend.md](model-backend.md) | Implemented; tested only against a local fake server | Boundaries of the opt-in `turnwise_lab.provider_cli` |
| [live-smoke-decision-packet.md](live-smoke-decision-packet.md) | First authorization consumed; provider HTTP 429, no model outputs; second authorization (#60) closed without dispatch | Bounded four-configuration plan, verified outcomes and owner spend gate |
| [privacy-threat-model.md](privacy-threat-model.md) | Current | What the public harness does and does not protect |
| [pr-consolidation-gates-2026-11-20.md](pr-consolidation-gates-2026-11-20.md) | Current integration decision record | How to reconcile open PRs, safety/budget contracts, and a prospective Level C study |

## Experiments and evidence

| Document | Status | Read it for |
|---|---|---|
| [../reports/live-smoke-44520205372.md](../reports/live-smoke-44520205372.md) | Historical paid attempt; INCONCLUSIVE | Owner-supplied sanitized summary, per-configuration HTTP 429 counts, provenance and unknowns |
| [../reports/arena.md](../reports/arena.md) | Experimentally measured (authored synthetic, no model) | v0.5 results, every failure, hypothesis verdicts |
| [preregistration-v0.5.md](preregistration-v0.5.md) | Frozen | v0.5 hypotheses, committed before any code |
| [../reports/trained-routing-synthetic.md](../reports/trained-routing-synthetic.md) | Historical (v0.4) | Route-label benchmark: rules 38/40, Naive Bayes 29/40 |
| [evaluation-plan.md](evaluation-plan.md) | Proposed (next gate) | What v0.5 established and what the next experiment must measure |
| [quality-constrained-efficiency-v06.md](quality-constrained-efficiency-v06.md) | Proposed (draft protocol, not pre-registered) | Comparator ladder and metrics for a real-model study |
| [benchmark-parity-contract.md](benchmark-parity-contract.md) | Implemented and tested (static preflight) | Checking that arms get equal access before comparing them |
| [enterprise-synthetic-scenarios.md](enterprise-synthetic-scenarios.md) | Proposed | Candidate synthetic enterprise case families |

## Project operations

| Document | Status | Read it for |
|---|---|---|
| [release-status.md](release-status.md) | Current | Evidence layers, what is on `main`, what is held |
| [publish.md](publish.md) | Historical (v0.4/v0.5 release checklist) | Pages deployment and announcement rules |
| [launch-plan.md](launch-plan.md) | Historical draft, numbers superseded | Unsent announcement draft |
| [../RELEASE_NOTES.md](../RELEASE_NOTES.md) | Historical | v0.4 and v0.5 release notes |
