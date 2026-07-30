---
name: orchestrate-development-cycle
description: Run or resume ready backlog tasks through the installed `.harness` lifecycle, sequentially implementing, verifying, logic-reviewing, browser-validating when required, committing, and continuing until complete or genuinely blocked. Use to drain an initialized backlog or run an explicitly bounded eligible task set.
---

# Orchestrate Development Cycle

Run one active task at a time. Deterministic scripts own state, selection,
ordered result history, retry decisions, transitions, verification, and commit
creation. Never edit lifecycle fields directly.

## Resolve the stop policy

- No explicit limit: continue until complete or blocked.
- “Only one task”: stop after one completed or blocked task.
- Explicit count or task IDs: stop at that boundary.

Do not infer a one-task limit. Keep one final commit per completed task.

## Preflight and select

Read applicable repository instructions plus `.harness/config.json`. Run:

```bash
uv run python -B scripts/harness/validate_state.py
uv run python -B scripts/harness/backlog_status.py
```

Follow `next_action`: resume, select, report complete/empty, wait for proposed
task approval, or report the exact stalled groups. An active task is expected
to have tracked harness changes, so do not run a clean-boundary check before
`resume_active`.

For `select_next` only, require a clean boundary and then select
deterministically:

```bash
uv run python -B scripts/harness/check_repo_clean.py --before-task
uv run python -B scripts/harness/select_next_task.py
```

Use `--task-id <id>` only for an explicitly requested eligible task. Read
`.harness/current-task.json` and its active `run.json`; do not give workers the
whole backlog.

## Implement

Spawn one temporary implementation subagent. This skill explicitly authorizes
that delegation. Direct it to `.harness/prompts/implementer.md` and provide the
task, scope, applicable instructions, result schema, and relevant skills. It
must not edit lifecycle state or commit.

Write its returned JSON to a temporary path outside the repository, then:

```bash
uv run python -B scripts/harness/record_result.py \
  implementation-result <temporary-result.json>
uv run python -B scripts/harness/update_task_state.py <task-id> verifying \
  --reason implementation_finished
```

## Verify and make a deterministic retry decision

Run:

```bash
uv run python -B scripts/harness/verify_task.py
```

On a non-passing result, run:

```bash
uv run python -B scripts/harness/retry_status.py verification
```

- `repair`: transition to `implementing`, spawn a repair worker using
  `.harness/prompts/repair.md`, record its implementation result, transition
  back to `verifying`, and verify again:

  ```bash
  uv run python -B scripts/harness/update_task_state.py \
    <task-id> implementing --reason verification_product_failure
  uv run python -B scripts/harness/record_result.py \
    implementation-result <temporary-repair-result.json>
  uv run python -B scripts/harness/update_task_state.py \
    <task-id> verifying --reason repair_finished
  uv run python -B scripts/harness/verify_task.py
  ```

- `block`: always persist the terminal transition before stopping:

  ```bash
  uv run python -B scripts/harness/update_task_state.py \
    <task-id> blocked --reason <failure-class-and-exact-evidence>
  ```

- `advance`: continue.

Zero checks are `INCOMPLETE`. Only `product` failures consume retry budget;
non-product prerequisites block immediately instead of causing blind retries.

## Review logic before browser work

After passed verification:

```bash
uv run python -B scripts/harness/update_task_state.py <task-id> reviewing \
  --reason verification_passed
uv run python -B scripts/harness/collect_diff.py
```

Spawn a fresh read-only reviewer. Direct it to
`.harness/prompts/reviewer.md`, the current task, canonical run, diff, review
schema, applicable instructions, matching review skills, and the generated
browser plan when browser validation is required. Browser evidence is
intentionally pending. Record its temporary result:

```bash
uv run python -B scripts/harness/record_result.py review <temporary-result.json>
```

For `CHANGES_REQUIRED`, run `retry_status.py review`. On `block`, persist the
`reviewing -> blocked` transition before stopping. On `repair`, transition to
`implementing`, record the repair result, explicitly transition to
`verifying`, run verification, transition to `reviewing`, rerun
`collect_diff.py`, and obtain a fresh review. Ordered run events and the diff
snapshot make stale evidence fail deterministic gates.

## Browser-validate only approved code

Skip this section when `verification.requires_browser` is false. Otherwise:

```bash
uv run python -B scripts/harness/update_task_state.py \
  <task-id> browser_validating --reason logic_review_approved
```

Check `app.health_url` once. If it is down and `app.start_command` is
configured, start that command once and wait for health before spawning the
validator. If the app cannot become healthy, use the validator only to return
the structured `environment` `INCOMPLETE` preflight result, then follow the
`block` path; do not begin UI exploration.

Spawn one fresh browser validator and direct it to
`.harness/prompts/browser-validator.md`. It must use the generated
`browser-plan.json` plus configured playbook/fixture/profile shortcuts,
preflight health/fixtures/profiles/tooling once, group criteria into minimal
journeys, reuse meaningful evidence, and directly drive the rendered app. Use
the first available canonical surface:
`browser_use`, `chrome_control`, `computer_use`, then `playwright`.

Save screenshots under the active run's `evidence/` directory and record the
temporary result:

```bash
uv run python -B scripts/harness/record_result.py \
  browser-result <temporary-result.json>
```

On failure, run `retry_status.py browser`.

- For `block`, transition `browser_validating -> blocked` with the failure
  class and exact evidence before stopping. Fixture, tooling, environment, and
  scope blockers therefore stop without consuming browser retry budget or
  leaving an active task that restarts preflight.
- For `repair`, transition to `implementing`, record the repair result,
  explicitly transition to `verifying`, run verification, transition to
  `reviewing`, rerun `collect_diff.py`, obtain and record a fresh review, then
  transition back to `browser_validating`.

Never jump directly from implementation to a verification command. Any code
repair must repeat verification and logic review before browser validation.

## Complete, commit, and continue

After approved review and, when required, passed browser validation:

```bash
uv run python -B scripts/harness/update_task_state.py <task-id> completed \
  --reason acceptance_gates_passed
uv run python -B scripts/harness/create_task_commit.py
uv run python -B scripts/harness/check_repo_clean.py --before-next-task
uv run python -B scripts/harness/backlog_status.py
```

Report task/run IDs, acceptance results, verification, review, browser result,
and commit. Continue according to the invocation boundary.

At a clean maintenance boundary, cold-store committed completed tasks and run
evidence:

```bash
uv run python -B scripts/harness/archive_completed_tasks.py --dry-run
uv run python -B scripts/harness/archive_completed_tasks.py
```

This archive change is separate because a commit cannot contain its own hash.
Do not let it leak into an unrelated product-task commit.

## Non-negotiable boundaries

- One active task and one final commit per completed task.
- Fresh implementation, logic-review, and browser contexts per task.
- Logic review precedes browser validation.
- No completion with stale or missing verification, review, or required browser
  evidence.
- No agent lifecycle edits, deployment, or external writes outside active task
  authority.
