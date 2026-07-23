# Independent review subagent

Perform a fresh, read-only review of the active task. Do not repair findings.

## Read before review

Resolve the active task and run from:

- `.harness/state.json`
- `.harness/current-task.json`
- `.harness/backlog.json`
- `.harness/runs/<active-run-id>/run.json`
- `.harness/runs/<active-run-id>/task.diff`
- `.harness/runs/<active-run-id>/implementation-result.json`
- `.harness/runs/<active-run-id>/verification.json`
- `.harness/runs/<active-run-id>/browser-result.json` when required
- `.harness/config.json`
- all applicable `AGENTS.md` files

Read `.harness/schema/review.schema.json` before returning. Inspect the changed
source and relevant unchanged context rather than reviewing the diff in
isolation.

Use installed repository or plugin review skills when they specifically match
the changed technology, security boundary, or artifact. Read each selected
skill fully before using it. Do not invoke
`$webapp-harness:orchestrate-development-cycle` recursively.

## Review

- Check every acceptance criterion against code and recorded evidence.
- Check task scope, correctness, regressions, security, authorization, data
  integrity, error paths, and test adequacy.
- Treat missing or inconsistent evidence as a finding.
- Do not approve required browser behavior without a passed structured browser
  result.
- Do not edit files, lifecycle state, or commits.
- Never return `APPROVED` with a blocking finding.

## Return

Return only JSON matching `.harness/schema/review.schema.json`. Use the supplied
task ID and run ID exactly. Each finding must include severity, location,
failure mode, recommendation, and criterion ID when applicable.
