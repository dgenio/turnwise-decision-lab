# AGENTS.md

Instructions for coding agents (and humans) working in this repository. Keep changes small, honest and reproducible.

## What this repository is

A **research lab** testing one architectural hypothesis: a small typed **decision policy**, re-invoked after every unresolved observation, chooses the next operation (direct answer, tool, workflow, light/heavy model call, clarify, hold, finish), instead of a generative LLM controlling the agent loop. The host validates and executes everything.

**Non-goals.** Do not build another agent framework, orchestrator, model router product or provider SDK. Do not add features to make the idea look better. If simple host rules or a native framework do the same job, the expected outcome is SHRINK/STOP, not more code. Overview: [README.md](README.md). Hypothesis and falsifiers: [docs/per-step-execution-hypothesis.md](docs/per-step-execution-hypothesis.md).

## Architecture invariants (do not break)

1. **The policy regains control after every unresolved observation, including model output.** A model's tool request is a `tool_proposal` observation returned to the policy. It is never executed directly.
2. **Model calls in Turnwise Core execute nothing.** A model step runs with no tools, handoffs or MCP servers and returns a typed `StepOutcome` (`answer_candidate`, `tool_proposal`, `needs_evidence`).
3. **The host owns authority.** Permissions, argument validation, side effects, write intent (parsed from the user's text only), budgets and terminal acceptance (`FINISH` citation checks) live in the host, never in the policy or the model. Writes are held for approval, never executed.
4. **`HANDOFF_AGENT` is not Turnwise Core.** It gives a native agent its own loop for a segment, so control ownership changes. Keep it labelled as a contrast/ablation in code, traces and docs.
5. **Simulated is not inference.** Offline runs use simulated model replies. Never describe them as model results.

These were set by the architecture gate in [#34](https://github.com/dgenio/turnwise-decision-lab/issues/34) ([audit](docs/architecture-fit-audit-2026-11-18.md)). Earlier experimental branches broke invariant 1 by letting a heavy agent take over subsequent decisions; do not reintroduce that pattern under the Turnwise Core name.

## Where things are

| Path | What it is |
|---|---|
| `examples/architecture/` | **Canonical Turnwise Core demonstration.** `turnwise_core.py` (typed `Op`, `Decision`, `Snapshot`, `Policy` and `ModelPort` protocols; the loop is `TurnwiseRuntime.run`, host checks are `host_validates`, model replies are parsed by `parse_outcome`), `policies.py` (`TriagePolicy`; `HandoffPolicy` = contrast), `incident_env.py` (`IncidentHost`), `openai_agents/` and `llamaindex/` (`conventional.py` = A, `turnwise.py` = B, `models.py` = simulated/live model choice), `simulated_model.py`, `sample_output/`. Opt-in #55 exhibit: `context_modules.py` + `instruction_modules.v1.json` (pre-authored instruction blocks), `scoped_runtime.py` (`ScopedContextRuntime`), `action_context_demo.py`. Real-provider path: `provider.py` (bounded `ProviderLedger`), `provider_double.py` (simulated Responses API), `live_smoke.py` (four-way rehearsal / manual opt-in live test), `secure_live_once.py` (owner-local launcher), `actions_summary.py` (sanitized one-shot workflow evidence) |
| `turnwise_lab/` | v0.4/v0.5 lab: `arena.py` (v0.5 experiment), `world.py` (synthetic world and handlers, shared by the demo), `runtime.py` (`LocalHarness`), `explorer.py`, `benchmark.py`, `provider.py` (opt-in OpenAI-compatible adapter, tested only against a local fake server), `parity.py` (benchmark-parity preflight) |
| `tests/` | `test_architecture_*.py` for the demo and provider rehearsal; `test_secure_live_once.py` for the credential-free launcher; everything else for the lab |
| `fixtures/`, `reports/`, `demo/` | **Frozen evidence and generated artefacts** (see below) |
| `docs/` | Design, protocols and history. Index with status labels: [docs/README.md](docs/README.md) |

**Current truth is `main`.** v0.6 to v0.8 runtime code (`turnwise_lab/agent/`, `turnwise_lab/v08/`, and similar) exists only on unmerged experimental branches (PRs #6, #37, #38, #44, #46). Some PRs show "merged" but were merged into those stacked branches, not `main` (for example #47 and #48). Do not cite, import or extend that code as if it were on `main`. Status of each layer: [docs/release-status.md](docs/release-status.md).

## Setup and commands

Main lab: Python 3.10+, stdlib only. Use `python3` where `python` is not on your path.

```bash
python -m unittest discover -s tests
```

Architecture demo and its framework tests: Python 3.11+.

```bash
pip install -r examples/architecture/requirements.txt
```

```bash
TURNWISE_REQUIRE_FRAMEWORKS=1 python -m unittest discover -s tests -p 'test_architecture*.py'
```

```bash
python -m examples.architecture.run_demo --brief
```

Free, entirely offline provider-path rehearsal (no API key or inference):

```bash
python -m examples.architecture.live_smoke --provider double
```

Without the pinned SDKs installed, the framework tests are **skipped** (not failed) and `run_demo` exits with an install hint. `TURNWISE_REQUIRE_FRAMEWORKS=1` turns skips into failures, as CI does.

**Regeneration checks (run these whenever you touch code that feeds them):**

```bash
examples/architecture/regenerate_samples.sh && git diff --exit-code -- examples/architecture/sample_output
```

```bash
python -m turnwise_lab.arena
python -m turnwise_lab.explorer
python -m turnwise_lab.live_demo --output reports/live-local-run.json
python -m turnwise_lab.benchmark --output /tmp/trained.json --markdown reports/trained-routing-synthetic.md
python -m turnwise_lab.showcase --json-out demo/showcase.json --html-out demo/planning-contract.html
python -m scripts.render_local_demo
python -m turnwise_lab.evaluate --output reports/synthetic-contract-replay.json
git diff --exit-code -- reports demo
```

This is the same sequence as the `test` job in `.github/workflows/tests.yml`; if they ever differ, the workflow wins.

CI (`.github/workflows/tests.yml`) runs the full suite on Python 3.10/3.12, regenerates every report and page as above and requires byte-identical output, and runs the architecture job on 3.11/3.12 with the network pointed at a dead proxy, including the `live_smoke --provider double` rehearsal. A diff in `reports/`, `demo/` or `sample_output/` after your change means you changed evidence: stop and explain why in the PR, or revert.

## Frozen evidence: do not silently change

- `docs/preregistration-v0.5.md`, `fixtures/sessions.json`, `turnwise_lab/world.py`, the v0.5 routers in `turnwise_lab/arena.py`, `reports/arena.*`: frozen v0.5 experiment. `tests/test_arena.py` pins the hypothesis verdicts.
- `reports/trained-routing-synthetic.*`, `fixtures/route_*.jsonl`, `reports/live-local-run.json`, `reports/synthetic-contract-replay.*`, `demo/*`: historical v0.4 artefacts, regenerated by CI.
- `examples/architecture/sample_output/*`: committed demo output.
- Dated audits and reports (for example `docs/architecture-fit-audit-2026-11-18.md`): add a dated note instead of rewriting findings.

Never tune a router or policy on the 46 v0.5 turns and present the result as held-out. Never turn a negative finding into a positive one; add new evidence alongside the old.

## How to make common changes

- **New or modified policy** (Turnwise Core, in `examples/architecture/policies.py`; the v0.5 routers in `arena.py` and the v0.4 deciders in `deciders.py` are frozen history): implement `Policy.decide(snapshot) -> Decision` (see `TriagePolicy`) and pass it to `TurnwiseRuntime`. Leave the default policy and `run_demo` unchanged unless you intend to regenerate the sample output. Decide and document what your policy does after declining a proposal (another read, `HOLD`, a model call). Do not move validation into the policy; the host must still refuse bad decisions. Add tests that drive it with varied model outcomes (proposal, immediate answer, write proposal, malformed output), as `tests/test_architecture_core.py` does.
- **New tool or workflow:** the demo's registry is the subset of the `turnwise_lab/world.py` catalogue named in `_ROLES` in `examples/architecture/incident_env.py`; every call goes through `LocalHarness`, and both A and B get the same tools. **`world.py` also drives the frozen v0.5 experiment**: adding or changing a capability there can change `reports/arena.*`. Run the regeneration check; if v0.5 evidence moves, keep the new capability out of the v0.5 world instead. Writes must record the attempt and raise.
- **Model adapter or provider:** extend the framework's `models.py` (`choose_models` / `choose_llms`). Send real-provider requests through the bounded `ProviderLedger` in `examples/architecture/provider.py`; prohibit hidden retries, set a bounded output, and test against `provider_double.py`. A simulated endpoint proves only wire compatibility. Live paths must be explicit opt-in, never run in CI, and labelled untested until a real run is recorded with model IDs and configuration.
- **Experiment:** write the hypothesis, cases, metrics and margin first (see [docs/evaluation-plan.md](docs/evaluation-plan.md) and [docs/benchmark-parity-contract.md](docs/benchmark-parity-contract.md)). Use new, ideally independently authored, cases. Report every arm, including failures.
- **Documentation:** update [docs/release-status.md](docs/release-status.md) when a status changes, and use the status labels below. Link to authoritative docs rather than duplicating them.

## Fair comparisons and claims

- Every arm gets the same task, tools, data, host, permissions and model, unless a difference is inherent and documented (see the demo's parity notes).
- The mandatory nulls are simple host rules + the same capable agent, the native agent, and a checklist-prompted native agent ([#43](https://github.com/dgenio/turnwise-decision-lab/issues/43)).
- Count every policy call, retry and fallback. Mark unmeasured values `unknown`, never `0`.
- **A mechanism test is not a scientific result.** A passing test proves a control-flow property (for example, "the policy is called after a tool proposal"). It says nothing about quality, cost or latency. Results need held-out cases, real executed baselines and a predeclared analysis ([#9](https://github.com/dgenio/turnwise-decision-lab/issues/9)).

Status labels: **Implemented and tested** · **Demonstrated with simulated inference** · **Experimentally measured** · **Proposed** · **Not tested** · **Held / inconclusive** · **Rejected / falsified**.

## Paid providers, secrets and data

- Default runs are offline. Never call `live_smoke --provider openai`, `secure_live_once --execute`, dispatch `.github/workflows/paid-smoke.yml`, or use `turnwise_lab.provider_cli --allow-remote` without explicit human authorization for that **specific model, cap and one attempt**. No automatic reruns; these calls can cost money.
- First owner-dispatched GPT-6.1 Sol authorization was consumed on 2026-11-19 ([run 44520205372](https://github.com/dgenio/turnwise-decision-lab/actions/runs/44520205372), fixed tag `turnwise-paid-gpt-6-1-sol-001`). HTTP 429 produced no model output. Do not move/delete this tag or bypass the create-only reservation. PR #60 proposes a *separate* one-shot authorization; merging the workflow is not permission to dispatch it without verifying account/model capacity.
- All real-provider calls must use the dedicated bounded `ProviderLedger`, a provider-double rehearsal and the first-429 stop; the client USD cap is an **estimate**, not a provider billing ceiling. Agents must not handle the owner's API key.
- Use the [PR consolidation gates](docs/pr-consolidation-gates-2026-11-20.md) before promoting any v0.6/v0.7/v0.8 research branch into the canonical Turnwise Core on `main`.
- Never commit keys, `.env` files, real company or customer data, or logs from real systems. All data here is invented and synthetic. See [docs/privacy-threat-model.md](docs/privacy-threat-model.md) and [docs/model-backend.md](docs/model-backend.md).
- Do not make a claim about live-model behaviour based on an open PR.

## Pull requests

- Branch from the latest `main`; one focused change per PR. Do not modify, merge or close other contributors' or agents' branches.
- Separate code, evidence and documentation changes where practical. Never mix a scoring change into an unrelated PR.
- State in the PR: what changed, which tests ran, whether any committed evidence changed (and why), and what the change does **not** show.
- Both CI jobs (`test`, `architecture-examples`) must pass. Green CI is not a scientific or safety proof.
