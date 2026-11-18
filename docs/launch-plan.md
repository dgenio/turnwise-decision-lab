# External visibility plan: evidence before promotion

**Publication draft / not sent.** The idea has already been published separately on LinkedIn and Substack; a subsequent post must add a demonstrable result, not paraphrase the original thesis.

First touchpoint: repository README → local interactive execution receipts → independent reproduction of benchmark misses. Lead with **"route the work, not just the model"**, not an invented performance improvement.

## Proposed technical follow-up (English)

I argued recently that model routing starts one decision too late.

Before choosing a model, an agent should be able to decide whether it even needs a model — or whether a verified fact, a read tool, or a known workflow is enough. And when reasoning is needed, the context should be selected for that particular task.

I built a small public experiment to make that decision visible. It can execute local synthetic tool/flow calls, produce a reviewable receipt, and hold side-effecting actions outside the classifier's authority.

The initial result wasn't a win for the classifier: on 40 hand-authored synthetic route examples, simple host rules matched 38 labels, while a tiny trained classifier alone matched 29. Adding a safety/answer preflight brought the hybrid to 38 — no gain over plain rules.

These aren't real decision-model or production results, and the prompts aren't independently labeled. That's precisely the point: an additional routing layer has to earn its latency and failure modes against a competent baseline.

The next test is a real current provider-native router on independently labeled multi-turn tasks, measuring *cost per correctly resolved task*, evidence recall, retries and authorization errors.

[ADD VERIFIED GITHUB REPO + DEMO LINKS BEFORE PUBLISHING]

## Distribution sequence

1. Get one practitioner to execute the offline demo and check reproducibility without the maintainer.
2. Request two expert critiques on the strong-baseline design, not praise for the framework.
3. Add an independently sourced task set and a working native-router arm only if reviewers find a plausible value gap.
4. Publish a technical article with the full failures and exact provider/model configuration, if the evidence warrants it.

Do not market empty model-router novelty, do not mass-contact maintainers, and do not confuse stars/reads with retained usage.
