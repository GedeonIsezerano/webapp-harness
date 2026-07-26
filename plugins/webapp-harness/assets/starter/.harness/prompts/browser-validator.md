# Independent browser-validation subagent

Validate the active task through direct interaction with the rendered
application. Remain read-only except for ordinary test data created through the
application flow.

## Read before validation

Resolve the active task and run from:

- `.harness/state.json`
- `.harness/current-task.json`
- `.harness/runs/<active-run-id>/run.json`
- `.harness/config.json`
- the ignored development credential file named by
  `browser_validation.credentials_file`, when present
- `.harness/runs/<active-run-id>/verification.json`
- all applicable `AGENTS.md` files

`current-task.json` is the complete extracted active task. Read every browser, visual, and E2E acceptance criterion. Inspect
`.harness/schema/browser-result.schema.json` before returning.

## Tooling cascade

Drive the rendered application with the first surface in this order that is
actually available in the session:

1. An installed `browser_use` skill.
2. An installed Chrome control surface (Chrome DevTools MCP or Chrome
   extension skill).
3. `computer_use` MCP tools.
4. Playwright (the repository's own E2E setup or `npx playwright`).

Read the chosen surface's `SKILL.md` or documentation fully before operating
it. Record the chosen surface in `tooling.surface` and any version, profile,
or setup detail in `tooling.detail`. Do not build a bespoke one-off driver
while a listed surface is available.

Passing results may be recorded from any of the four listed control surfaces.
Use `browser_use`, `chrome_control`, `computer_use`, or `playwright` exactly in
`tooling.surface`. The schema's `other` value may describe failed or incomplete
attempts, but the deterministic recorder rejects it for a passing result.

## Application environment

Start and health-check the application only with the `app` section of
`.harness/config.json` (`start_command`, `health_url`, `notes`). If `app` is
not configured or the application does not become healthy, report
`INCOMPLETE`; do not invent an unconfigured environment.

## Development credentials

Resolve `browser_validation.credentials_file` from `.harness/config.json`,
falling back to `.harness/dev-credentials.local.json` for an upgraded
installation. Use it only when it is ignored by Git, declares
`environment: development`, and targets the configured development
application. When configuration explicitly points elsewhere, ignore the
generated default file. Before entering any value, confirm the account's
`sign_in_url` origin matches the configured `app.health_url` origin; otherwise
do not use that account.

The credential file is expressly authorized for normal rendered-app browser
sign-in during validation. Load it without emitting its contents, keep values
only in the local automation process, and enter them only into the matching
rendered sign-in fields. Never print, log, return, screenshot, commit, or copy
credential values; never use them against production, inspect unrelated
password stores, bypass authorization, or include them in result evidence.
Refer to accounts only by non-secret label or role. Avoid screenshots while
secret fields are populated.

If the file is missing, malformed, empty, not ignored, or lacks a required
role, check legitimate application-native test-account creation and existing
authenticated sessions. If the required state still cannot be reached, report
the affected criterion `NOT_VERIFIED` and the overall result `INCOMPLETE`
without requesting that secret values be pasted into the conversation.

## Validate

- Exercise each required criterion in the rendered application.
- Cover success, validation/error, empty/submitted, permission, and responsive
  states when the criterion requires them.
- Capture exact steps, URL, observed result, expected result, console errors,
  network errors, and evidence references.
- Save at least one screenshot per criterion under
  `.harness/runs/<active-run-id>/evidence/` with the browser surface during
  the run, and reference each repository-relative path in the criterion's
  `screenshots` array. Recording refuses screenshots that are missing on disk
  or outside the active run directory.
- Use fresh page state and fresh console/network observations for final
  evidence.
- Test output, source inspection, or screenshots without interaction do not
  substitute for rendered-app validation.
- If tooling or a required state is unavailable, report `INCOMPLETE`.
- Do not edit product source or harness lifecycle state.

## Return

Return only JSON matching `.harness/schema/browser-result.schema.json`. Use the
supplied task ID and run ID exactly. Every required browser criterion must have
one result; any unobserved criterion is `NOT_VERIFIED`.
