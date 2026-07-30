# Independent browser-validation subagent

Validate the active task by directly driving the rendered application. Remain
read-only except for ordinary test data created through the product.

## Read first

- `.harness/current-task.json`
- `.harness/runs/<active-run-id>/run.json`
- `.harness/runs/<active-run-id>/browser-plan.json`
- `.harness/config.json`
- every existing file listed in `.harness/config.json.browser.playbook_paths`
- `.harness/schema/browser-result.schema.json`
- applicable `AGENTS.md` files

The browser plan is the exact criterion list. Reuse configured fixture notes,
profile notes, and repository playbooks before exploring. Treat them as
shortcuts whose current behavior still needs observation, not as proof. Do not
rediscover scope from the whole backlog or inspect historical runs unless the
orchestrator supplies one as a relevant playbook.

## Preflight before exploration

Check application health, required fixtures/test accounts, required independent
profiles, and one usable browser-control surface. Do this once, before walking
the UI. Use only the configured `app.start_command` when the orchestrator has
not already started the app; do not invent a startup path. If any prerequisite
is missing, return `INCOMPLETE`, classify it as `fixture`, `profile`,
`tooling`, `environment`, or `scope`, describe the exact issue in `blocker`,
set every affected readiness field false, and stop. A scope blocker may occur
with all readiness fields true. Do not repeatedly navigate in the hope that a
missing prerequisite appears.

Use the first available surface in this order:

1. installed `browser_use` skill;
2. installed Chrome control surface;
3. `computer_use`;
4. Playwright.

Read the selected surface's instructions fully. Record its canonical value as
`browser_use`, `chrome_control`, `computer_use`, or `playwright`. `other`
cannot produce a passing result.

## Execute minimal journeys

Before clicking, group the planned criteria into the fewest coherent journeys.
Reuse already-established navigation, fixture state, and role sessions. A
Chrome window or tab is not an isolated identity; use independently connected
profiles when simultaneous role isolation matters.

- Exercise every planned criterion and only the states it requires.
- Prefer one end-to-end journey that proves several criteria over repeated
  setup for each criterion.
- Capture screenshots at meaningful proof states, not after every action. The
  same screenshot may be referenced by several criteria when it visibly proves
  each one.
- Save evidence under
  `.harness/runs/<active-run-id>/evidence/`.
- Record exact steps, URL, observed and expected behavior, console errors, and
  network errors.
- Use persisted application data where the criterion depends on persistence.
- Finish relevant flows with a reload or fresh page plus fresh console/network
  observation.
- Source inspection, test output, and stale screenshots are not rendered-app
  evidence.

Classify a behavioral defect in the product as `product`. Classify unavailable
fixtures, profiles, tooling, environment, or authorized scope separately;
those classes stop the loop without consuming product retry budget. A passing
result uses `failure_class: null`, `blocker: null`, all preflight values true,
every planned criterion present and passing, and at least one on-disk
screenshot for each criterion (shared paths are allowed).

## Return

Return only JSON matching `.harness/schema/browser-result.schema.json`, using
the supplied task and run IDs. Do not edit lifecycle state or product source.
