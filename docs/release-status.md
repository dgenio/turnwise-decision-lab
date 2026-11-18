# Release candidate: v0.4 — what is and is not ready

**2026-11-18 · Public demo/research RC. No production or external model claims.**

## Ready

- Source-only Python package, MIT license, Python 3.10+ with no core dependency.
- Offline six-turn interactive exhibit (`demo/index.html`) clearly labeled **planning-only**.
- Executable closed-world six-turn scenario, with verified direct answer, actual read tool, actual deterministic flow, two generation handoffs and one blocked publication (`turnwise_lab.live_demo`).
- Generated execution receipts (`reports/live-local-run.json`; mirrored in `demo/live-local-run.json`) with side-effect and host-permission checks in local harness.
- Frozen dataset of 60 synthetic train / 40 synthetic test cases and a genuinely fitted minimal Naive Bayes route baseline; no claims of independent labeling.
- Strong simple rules and hybrid arms, with per-case misses shown, classifier-call counts (hybrid: 23 calls, 2 accepted), and unknown API costs/null outcome metrics explicit.
- Unit/integration tests, including forged-plan tests and a localhost mocked provider HTTP test.
- Static `demo/local-run.html` displaying the local execution receipt trail; GitHub Pages workflow is present.
- Public sources contain no real organizational conversations, credentials, customer identifiers, or corporate measurements.

## Not done / blocked

- No real Jev or generative-provider model inference performed in this release preparation.
- No deployed LiteLLM Auto Router, vLLM Semantic Router or native tool search benchmark.
- No independently labeled, held-out multi-turn corpus, statistical noninferiority assessment, measured token economics or provider latency.
- No GitHub repository or Pages URL created by this preparation. Requires an authenticated repository-creation operation unavailable in the current connector; code package is ready to push once `dgenio/turnwise-decision-lab` is initialized.
- The local harness is educational and is not a sandbox, IAM implementation, complete mediation layer or signed audit log.

## Publishing rule

Release as **"runnable engineering exhibit + initial negative synthetic benchmark"**, not a new routing product or an AI-performance result. A maintainer review of README, source-license consistency, synthetic fixtures and links precedes external promotion. Leave ContextWeaver D1 untouched.

**GO** for bounded public source publication when the repository exists. **HOLD** for provider-performance, cost-savings and enterprise-readiness claims.

## Naming check

The word "Turnwise" is already used by unrelated conversational-AI evaluation packages and academic work. Use **Turnwise Decision Lab** plus the distinctive tagline, not "the Turnwise framework"; avoid publishing to PyPI under `turnwise`. This is a search-based conflict flag, not legal trademark clearance.
