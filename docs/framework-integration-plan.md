# Framework integration and upstream discussion plan

This is a **planning document**, not evidence of framework support or maintainers' interest. No external issues should be opened before review and credible experimental results.

## Candidate ecosystems
- **LangGraph / LangChain:** explore a policy node or middleware inside the agent loop, retaining graph state, checkpoints, tool permissions and tracing. Likely first candidate; verify current extension APIs before implementation.
- **OpenAI Agents SDK:** explore an optional execution policy around turns and tools while preserving handoffs, guardrails, tracing and native tool calling. Avoid replacing SDK internals.
- **LlamaIndex:** explore workflow steps or agent-loop hooks with scoped memory, tools and observability.
- **Pipecat:** explore a real-time voice/pipeline adaptation only after the basic pattern works; account for streaming, interruption and latency budgets.

## Criteria for choosing the first adapter
Minimum invasive code; clear documented extension points; representative agent baseline; deterministic host actions; permissions and tracing; maintained tests; compatibility with normal agent behavior. Confirm actual APIs and repository contribution policies before coding.

## Proposed work items
1. Document state machine, routes, safety and verification invariants.
2. Define policy interface and a minimal adapter test harness.
3. Execute independent heavy-only baseline and adaptive agent on unseen tasks.
4. Run ablations: no state, no light model, no decision API, forced-heavy on uncertainty, context variants.
5. Publish reproducibility instructions, limitations and outcome/error taxonomy.
6. Select and implement one framework adapter behind an opt-in flag.
7. Draft a tailored upstream discussion issue, with benchmark links, minimal example, trade-offs and precise maintainer questions.
8. Incorporate feedback before proposing other integrations.

## Draft upstream discussion template — NOT POSTED
**Title:** Discussion: opt-in quality-constrained adaptive execution within the agent loop

We are exploring a framework-agnostic pattern where each agent step may use verified host facts, deterministic registered tools, a light model, or a heavy model with native tool calling. It is not a new framework or generic model router. The policy re-evaluates after observations and falls back to heavy reasoning when uncertain. Authorization remains with the host; outcomes and action intents are verified.

Spec: [adaptive execution pattern](adaptive-execution-pattern.md). Reproducible lab: https://github.com/dgenio/turnwise-decision-lab .

**Evidence:** [add independently executed heavy-only versus adaptive results; do not claim v0.5 proves efficiency].

**Questions for maintainers:** Is there an existing extension point for this policy? What safety/state invariants would an opt-in adapter need to respect? Would a minimal reference integration be welcome?

Tailor this draft to each project's documented architecture and contribution guidance. Do not mass-post.
