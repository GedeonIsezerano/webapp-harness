---
name: orchestrate-development-cycle
description: Run or resume ready backlog tasks through the installed `.harness` development lifecycle, sequentially implementing, verifying, browser-validating when required, independently reviewing, committing, and continuing until the backlog is complete or a real blocker is reached. Use in an initialized repository to drain the ready backlog by default, or when the user explicitly requests one task, a bounded task count, or a particular eligible task.
---

# Orchestrate Development Cycle

Run verified tasks sequentially. By default continue until every backlog task
is completed. The deterministic scripts own state validation, task selection,
lifecycle transitions, progress classification, result recording,
verification, and commit creation. Agents must not edit lifecycle fields
directly.

## Resolve the invocation policy

Before selecting work, derive the stop policy from the user's request:

- No explicit limit: continue until the backlog is complete or blocked.
- “Only one task” or equivalent: stop after one completed or blocked task.
- An explicit maximum count: stop after that many task attempts.
- Explicit task IDs or order: select those eligible tasks sequentially and
  stop after the requested set.

Do not infer a one-task limit from “run the development cycle.” Keep exactly
one active task at a time and one final commit per completed task. The current
state schema is intentionally single-active-task; do not parallelize unless the
user explicitly requests a separate state-model migration.

## Backlog preflight

1. Read the applicable repository instructions and `.harness/config.json`,
   `.harness/state.json`, `.harness/backlog.json`, and
   `.harness/completed-tasks.json`. Do not load the completion archive unless
   historical evidence is specifically needed.
2. Run:

   ```bash
   uv run python -B scripts/harness/validate_state.py
   uv run python -B scripts/harness/check_repo_clean.py --before-task
   uv run python -B scripts/harness/backlog_status.py
   ```

3. Use `backlog_status.py` as the source of truth:

   - `resume_active`: resume the recorded task and phase.
   - `select_next`: select the next task.
   - `complete`: report successful backlog completion and stop.
   - `empty`: report the empty backlog, suggest
     `$webapp-harness:generate-backlog`, and stop.
   - `awaiting_approval`: list proposed tasks that must be explicitly promoted
     to `ready`, then stop.
   - `stalled`: report blocked and dependency-stalled task IDs, then stop.

4. To use deterministic priority and ID ordering, run:

   ```bash
   uv run python -B scripts/harness/select_next_task.py
   ```

   When the user explicitly selects a task, preserve eligibility and dependency
   checks:

   ```bash
   uv run python -B scripts/harness/select_next_task.py --task-id <task-id>
   ```

5. Read `.harness/current-task.json` as the selected task document, then read
   its acceptance criteria, allowed and forbidden paths, verification
   profiles, retry limits, and active run record. Do not provide implementers,
   validators, or reviewers the entire backlog.

## Implement one active task

Spawn one temporary implementation subagent. This skill explicitly authorizes
that delegation. Direct it to read `.harness/prompts/implementer.md`, then give
it:

- the selected task and acceptance criteria;
- allowed and forbidden paths;
- applicable repository instructions;
- the implementation-result schema;
- the active run asset paths it must inspect;
- any installed task-specific skills it should use, without invoking this
  orchestration skill recursively;
- the instruction to plan internally, make no lifecycle edits, and create no
  commit.

Persist its JSON result and record it:

```bash
uv run python -B scripts/harness/record_result.py \
  implementation-result <result.json>
uv run python -B scripts/harness/update_task_state.py <task-id> verifying \
  --reason implementation_finished
```

Reject malformed or out-of-scope results.

## Verify and repair

Run:

```bash
uv run python -B scripts/harness/verify_task.py
```

If verification fails or is incomplete:

1. Transition back to `implementing`.
2. Spawn a repair implementer, direct it to read
   `.harness/prompts/repair.md`, and provide only the failing evidence plus the
   corresponding persisted run assets.
3. Record its result, transition to `verifying`, and rerun affected checks.
4. At the configured retry limit, transition the task to `blocked`, report the
   exact evidence and working-tree state, and stop the invocation.

Never treat zero executed checks as passed.

## Browser validation

When the task requires browser or visual verification, first ensure the
application is healthy at the `app.health_url` from `.harness/config.json`;
when it is not responding and `app.start_command` is configured, start it and
wait for health. Then spawn a fresh, independent browser validator. Direct it
to read `.harness/prompts/browser-validator.md` and the active task/run
assets, and drive the rendered application through the tooling cascade:
(1) an installed `browser_use` skill, (2) an installed Chrome control surface
(Chrome DevTools MCP or Chrome extension skill), (3) `computer_use` MCP
tools, (4) Playwright. Use the first surface actually available in the
session. Require direct interaction with the rendered application, structured
evidence for every browser criterion, and at least one screenshot per
criterion saved under `.harness/runs/<active-run-id>/evidence/` and
referenced in the recorded result.

Record the selected surface exactly as `browser_use`, `chrome_control`,
`computer_use`, or `playwright`. All four canonical surfaces may produce a
passing result. `other` may document a failed or incomplete attempt, but the
deterministic recorder rejects it for a passing result.

Unavailable tooling, unobserved criteria, stale console output, or test
output without rendered-app observation means `INCOMPLETE`, not passed. The
transition to `reviewing` is rejected deterministically while the active
task's `requires_browser` is true and no passed browser result is recorded.

Record the result:

```bash
uv run python -B scripts/harness/record_result.py \
  browser-result <result.json>
```

Repair and rerun within the browser retry limit. At the retry limit, transition
to `blocked` and stop. Do not advance with failed or incomplete required
browser evidence.

## Review

After verification and required browser validation pass, transition to
`reviewing`. Spawn a fresh read-only reviewer and direct it to read
`.harness/prompts/reviewer.md`. Give it:

- the task and acceptance criteria;
- the collected diff;
- verification and browser evidence;
- the review schema.

Also identify any installed technology-specific review skills it should read
and use. Do not let the reviewer invoke this orchestration skill recursively.

Record its result:

```bash
uv run python -B scripts/harness/record_result.py review <result.json>
```

An approval containing a blocking finding is invalid. For
`CHANGES_REQUIRED`, transition to `implementing`, run a bounded repair, and
repeat affected verification, browser validation, and review. At the retry
limit, transition to `blocked` and stop.

## Complete the task and decide whether to continue

After approval:

```bash
uv run python -B scripts/harness/update_task_state.py <task-id> completed \
  --reason review_approved
uv run python -B scripts/harness/create_task_commit.py
uv run python -B scripts/harness/check_repo_clean.py --before-next-task
uv run python -B scripts/harness/backlog_status.py
```

Confirm the commit contains only allowed task paths plus harness evidence.
Record the task ID, run ID, acceptance results, verification, browser result,
review verdict, and commit hash in the invocation summary.

Then:

- Stop if the user's task limit or requested task list is satisfied.
- Stop successfully when `backlog_status.py` returns `complete`.
- Continue from **Backlog preflight** when it returns `select_next`.
- Resume an active task if it returns `resume_active`.
- Stop and report the exact unresolved task groups for `empty`,
  `awaiting_approval`, or `stalled`.

Do not ask for confirmation between tasks when the user invoked the default
unbounded mode. A single invocation may create multiple commits, but always
exactly one commit per successfully completed task.

At a clean boundary after the requested task cycle, the user may compact
completed tasks without losing dependency information:

```bash
uv run python -B scripts/harness/archive_completed_tasks.py --dry-run
uv run python -B scripts/harness/archive_completed_tasks.py
```

This is separate maintenance because the task commit hash is only known after
its final task commit. Review and commit the resulting archive/index change
under the repository's normal policy; never archive before `create_task_commit.py`.

## Non-negotiable boundaries

- Exactly one active task at a time.
- Exactly one final task commit per completed task.
- Fresh implementation, browser-validation, and review contexts for every
  task.
- No planning-only subagent or planning lifecycle stage.
- No agent edits to lifecycle fields.
- No completion without passed verification, required browser evidence, and
  independent approval.
- No deployment or external write unless the active task explicitly authorizes
  it.
