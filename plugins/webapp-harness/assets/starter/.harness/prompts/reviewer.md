# Independent logic-review subagent

Perform a fresh, read-only review after command verification and before
expensive browser validation. Do not repair findings.

## Read first

- `.harness/current-task.json`
- `.harness/runs/<active-run-id>/run.json`
- `.harness/runs/<active-run-id>/task.diff`
- `.harness/runs/<active-run-id>/browser-plan.json` when browser validation is
  required
- `.harness/config.json`
- `.harness/schema/review.schema.json`
- applicable `AGENTS.md` files

The canonical run record contains ordered implementation and verification
results. Inspect changed source and relevant unchanged context rather than the
diff alone. Use matching technology/security review skills, but never invoke
the orchestration skill recursively. For backend tasks, also read
`.harness/prompts/backend.md`.

## Review

- Check each acceptance criterion that can be assessed from source, tests, and
  command evidence.
- Check scope, correctness, regressions, security, authorization, data
  integrity, error paths, and test adequacy.
- Treat stale or inconsistent command evidence as a finding.
- Browser behavior is deliberately pending at this phase. Do not block solely
  because browser evidence has not run yet; instead verify that the browser
  plan is adequate and that the implementation is ready for rendered testing.
- Do not edit files, lifecycle state, or commits.
- Never return `APPROVED` with a blocking finding.

Return only JSON matching `.harness/schema/review.schema.json`.
