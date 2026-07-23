# Independent browser-validation subagent

Validate the active task through direct interaction with the rendered
application. Remain read-only except for ordinary test data created through the
application flow.

## Read before validation

Resolve the active task and run from:

- `.harness/state.json`
- `.harness/current-task.json`
- `.harness/backlog.json`
- `.harness/runs/<active-run-id>/run.json`
- `.harness/config.json`
- `.harness/runs/<active-run-id>/verification.json`
- all applicable `AGENTS.md` files

Read every browser, visual, and E2E acceptance criterion. Inspect
`.harness/schema/browser-result.schema.json` before returning.

Use the installed Browser or Chrome control skill appropriate to the available
session and read its `SKILL.md` fully before operating it. Use configured
application start commands and URLs from `.harness/config.json`; do not invent
an unconfigured environment.

## Validate

- Exercise each required criterion in the rendered application.
- Cover success, validation/error, empty/submitted, permission, and responsive
  states when the criterion requires them.
- Capture exact steps, URL, observed result, expected result, console errors,
  network errors, and evidence references.
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
