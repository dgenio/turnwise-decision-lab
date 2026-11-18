# Security and privacy boundaries for a public experiment

This is not a production authorization layer, privacy filter, model gateway, or compliance product.

- `sensitivity` and `allow_external_decider` are trusted host assertions. This demo cannot verify that a public label is accurate. Its regex preflight only detects a few obvious secret/PII shapes and cannot certify de-identification.
- External model access requires explicit request opt-in and `public` classification, except a host-verified answer bypass that sends **nothing** externally. Public content can still carry sensitive material: the caller must independently approve release.
- The decision model sees only bounded metadata, text and short IDs; source bodies are never sent to the classifier. Metadata itself can be sensitive. Host owners must approve it.
- A `Plan` is advisory. A decision model's `tool`, `flow` or `direct` recommendation never authenticates a principal or authorizes execution. The executable host must enforce identity, allowlists, arguments, side-effect grants, approvals and auditing again.
- This demo's host-provided `approved_actions` is a **test placeholder**, not a signed proof of authorization, and has no expiration/revocation. Do not use it in production.
- Only hosts can mark a `direct_answer` as previously verified. If the host passes an unverified answer, the demo cannot detect that mistake.
- Lexical source matching is not trust scoring; a malicious source may be chosen and its body included in an advisory context pack. Real hosts must apply provenance, prompt-injection handling and data-boundary controls before submitting any pack to an LLM.
- Missing tools/schemas/classifier outputs trigger deep-model escalation proposals, never automatic side-effecting calls. A production failure policy could legitimately choose abstention instead; evaluate costs.
- Logging must not store full prompts, source bodies, access credentials or employee/customer identities in a shared OSS test artifact.
- Fully synthetic examples must remain synthetic. Do not derive real incident IDs, system URLs, company data models or internal topology from production without explicit clearance.
