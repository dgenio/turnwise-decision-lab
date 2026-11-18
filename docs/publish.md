# Publishing and verifying Turnwise Decision Lab

Repository: https://github.com/dgenio/turnwise-decision-lab
v0.4 was merged in [PR #1](https://github.com/dgenio/turnwise-decision-lab/pull/1). Pages is live at https://dgenio.github.io/turnwise-decision-lab/ (deployed by `.github/workflows/pages.yml` on pushes to `main` that touch `demo/`).

This repository is an experimental **engineering exhibit**, not a provider benchmark or production routing library. The public code is synthetic. Do not announce model-performance savings or an independently validated routing result.

## Review before merge

1. Inspect the PR against `README.md`, `reports/arena.md`, `docs/preregistration-v0.5.md`, the demo HTML files and `docs/privacy-threat-model.md`.
2. Verify the `offline-tests` GitHub Actions matrix succeeds for Python 3.10 and 3.12 on the **latest PR head**, not just an older commit.
3. Check that report counts, synthetic status, null cost fields, hold failures, and the separate planning-only vs actually executed paths are accurately described.
4. Confirm no credentials, customer data, corporate measurements or non-public incident content are committed.
5. Merge only once the review is complete.

A local validation path (no provider key):

```bash
python -m unittest discover -s tests -v
python -m turnwise_lab.arena
python -m turnwise_lab.explorer
python -m turnwise_lab.live_demo --output reports/live-local-run.json
python -m turnwise_lab.benchmark --output reports/trained-routing-synthetic.json --markdown reports/trained-routing-synthetic.md
python -m scripts.render_local_demo
```

## Publish the static demo after merge

Open repository **Settings → Pages → Build and deployment → Source: GitHub Actions**. The committed `.github/workflows/pages.yml` deploys the `demo/` directory on `main` changes and allows manual `workflow_dispatch` after it exists on the default branch.

Verify the deployment status and the actual Pages URL in GitHub. Check `index.html` (v0.5 outcome explorer), `local-run.html` (v0.4 receipts) and `planning-contract.html` (v0.4 fixture-fed planning) on desktop and mobile. **Do not guess a URL or claim Pages is live before verifying it.**

If Pages is disabled or the workflow needs a setting change, leave the release as source-only until enabled.

## First public announcement

Ask at least one engineer who was not involved in the implementation to reproduce the offline benchmark and examine a failure case. Then link only verified repository and Pages URLs. Lead with the trade-off, not the saving. On authored synthetic data, the state-aware router cut model calls from 78 to 20, but returned 6 silent wrong answers whose receipts said `completed`. The route-aware context hypothesis was falsified. This is not end-to-end task success, cost savings, a live Jev evaluation or evidence of architectural novelty.

The separate LinkedIn/Substack idea has already been published. A follow-up should add executable evidence rather than restate the hypothesis.
