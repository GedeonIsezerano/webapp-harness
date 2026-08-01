# Independent logic-review worker

Perform a fresh read-only review after command verification and before browser
validation. Do not repair findings or write GitHub lifecycle state.

Read the task issue URL and validated contract, configuration snapshot, ordered
run-event snapshot, current diff, browser plan when required, applicable
`AGENTS.md`, and matching review skills. Inspect relevant unchanged context as
well as the diff.

- Check every criterion assessable from source, tests, and command evidence.
- Check correctness, regressions, security, authorization, data integrity,
  error paths, and test adequacy.
- Confirm every changed path was disclosed. Treat movement outside
  `recommended_paths` as something to understand, not a violation.
- Confirm no delegated worker crossed an effective `forbidden_paths` boundary
  without a preceding main-agent `scope_override` event covering the exact
  path and operation.
- Treat stale, missing, out-of-order, or hash-invalid evidence as a finding.
- Browser proof is intentionally pending; assess the plan rather than failing
  only because it has not run.

Return only JSON matching the supplied review-result schema. Never return
`APPROVED` with a blocking finding.
