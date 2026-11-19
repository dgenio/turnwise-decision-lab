# Contributing to Turnwise Decision Lab

Thank you for helping test an idea, which may turn out to be wrong. This lab values **evidence over features**: a rigorous negative result is a good contribution. Not every proposal belongs in the core runtime, and the project deliberately avoids becoming another agent framework.

Before you start, read the [README](README.md) and [AGENTS.md](AGENTS.md). `AGENTS.md` holds the commands, architecture invariants and frozen-evidence rules for humans and coding agents alike.

## Most valuable contributions

1. **Independent held-out cases.** Multi-turn incident sessions written by someone other than the author, which no policy has seen. Include follow-ups, ambiguous referents, negated or polite writes, and near-neighbour traps. Label what a correct answer needs, not which route to take. See [docs/evaluation-plan.md](docs/evaluation-plan.md#data-and-independence).
2. **Alternative policies.** A rules, learned, small-LLM or decision-service implementation of `Policy.decide(snapshot) -> Decision` in [`examples/architecture/`](examples/architecture/README.md). Remote or paid policies must be opt-in and use synthetic data only.
3. **Strong native-agent baselines.** A checklist-prompted native agent ([#43](https://github.com/dgenio/turnwise-decision-lab/issues/43)), native tool search, or simple host rules plus the same agent. Turnwise has to beat these, so they should be strong.
4. **Safety and evidence failures.** Cases where a write is executed, an action intent is lost, a `FINISH` is accepted on wrong or insufficient evidence, or a proposal bypasses the policy. A failing test is the best bug report.
5. **Quality-constrained experiments.** Real-model comparisons against an executed, capable heavy-only agent, following the [v0.6 protocol](docs/quality-constrained-efficiency-v06.md) and the [study gate (#9)](https://github.com/dgenio/turnwise-decision-lab/issues/9). Agree on the margin and budget with the maintainer **before** spending money.
6. **Framework investigations.** Whether existing primitives in LangGraph, the OpenAI Agents SDK, LlamaIndex or others already express this pattern ([roadmap](docs/framework-integration-roadmap.md)). Do not open upstream issues without a working minimal example and maintainer agreement.

## Ground rules

- Do not edit frozen evidence (pre-registration, fixtures, reports, committed sample output) to improve a result. Add new evidence next to it.
- Keep every arm in a comparison on the same task, tools, data, host, permissions and model, and document any inherent difference.
- Say what your change does **not** show. A passing mechanism test is not a quality, cost or latency result.
- No real company, customer or personal data, and no secrets.

## Workflow

1. Branch from the latest `main`. Open an issue first for anything larger than a fix.
2. Run the checks in [AGENTS.md](AGENTS.md#setup-and-commands), including the regeneration checks if your change can affect committed output.
3. Open a focused PR that states what changed, which tests ran and whether any committed evidence changed. Both CI jobs must pass.
