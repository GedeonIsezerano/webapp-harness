# Harness architecture

This is a generic deterministic sequential task harness installed inside the application repository. The repository is its durable memory.

## Python environment

The harness uses `uv`, `pyproject.toml`, and a committed `uv.lock`.

```bash
uv sync --dev
uv run pytest tests/harness
uv run python scripts/harness/validate_state.py
```

Do not create or maintain a separate `requirements.txt` for the harness.

## Verification profiles

`.harness/config.json` maps profile names to ordered command specifications.
Commands are argument arrays and run without a shell:

```json
{
  "verification_profiles": {
    "unit": [
      {
        "name": "Unit tests",
        "command": ["npm", "test", "--", "--runInBand"]
      }
    ],
    "quality": [
      {
        "name": "Lint",
        "command": ["npm", "run", "lint"]
      },
      {
        "name": "Typecheck",
        "command": ["npm", "run", "typecheck"]
      }
    ]
  }
}
```

Reference only profile names that exist in this map from backlog tasks. During
initialization, include commands only after confirming that they exist and run
in the real repository. A task with no executed command checks is incomplete,
not passed.

A Python backend repository would instead configure pytest plus an integration
or migration check:

```json
{
  "verification_profiles": {
    "unit": [
      {
        "name": "Backend unit tests",
        "command": ["pytest", "tests/unit", "-q"]
      }
    ],
    "integration": [
      {
        "name": "Backend integration tests",
        "command": ["pytest", "tests/integration", "-q"]
      }
    ],
    "quality": [
      {
        "name": "Lint",
        "command": ["ruff", "check", "."]
      },
      {
        "name": "Typecheck",
        "command": ["mypy", "src"]
      }
    ]
  }
}
```

## Application config for browser validation

The optional `app` section tells browser validators how to run and
health-check the application under test:

```json
{
  "app": {
    "start_command": ["npm", "run", "dev"],
    "health_url": "http://localhost:3000",
    "notes": "Use the seeded staff account; onboarding requires an account with no business."
  }
}
```

The development-cycle orchestrator starts the app with `start_command` when
`health_url` is not responding, and validators report `INCOMPLETE` instead of
inventing an environment when `app` is missing or unhealthy.

## Browser validation evidence

Tasks with `verification.requires_browser: true` must collect structured
browser evidence before review. Recording a browser result requires at least
one screenshot per criterion, saved under `.harness/runs/<run-id>/evidence/`
and referenced in the result; `record_result.py` rejects results whose
screenshots are missing on disk or outside the active run directory.
`update_task_state.py` rejects the transition to `reviewing` while the active
task requires browser validation and no passed browser result is recorded.

Validators drive the rendered application through a tooling cascade, using the
first surface actually available: an installed `browser_use` skill, an
installed Chrome control surface (Chrome DevTools MCP or Chrome extension
skill), `computer_use` MCP tools, then Playwright. The chosen surface is
recorded in `tooling.surface` as `browser_use`, `chrome_control`,
`computer_use`, or `playwright`; each canonical surface may produce a passing
result. The schema's `other` surface is limited to failed or incomplete
diagnostics.

## Task priority

Lower priority values run first; 1 is the highest priority. Selection and
status reporting sort eligible tasks by `(priority, id)`. Reorder the backlog
deterministically instead of editing `backlog.json` by hand:

```bash
uv run python -B scripts/harness/reprioritize.py <task-id> [<task-id> ...]
```

The first ID receives priority 1, the second priority 2, and so on.

## New-repository setup

1. Copy or merge the harness files into the target repository root.
2. Merge the harness dependencies and pytest configuration into the repository's existing `pyproject.toml`, or use the supplied file when none exists.
3. Run `uv sync --dev` and commit `uv.lock`.
4. Run the generic harness tests and state validator.
5. Invoke `$webapp-harness:initialize-harness`.
6. Let that workflow inspect real commands, browser startup, Git policy, and
   repository structure, then update `.harness/config.json` and tests.
7. Review its evidence-backed proposed backlog. Initialization must request
   explicit confirmation before appending any tasks.
8. Confirm, revise, or cancel the proposal. Confirmed tasks are appended as
   `proposed`, never automatically made runnable.
9. Promote an accepted task explicitly:

   ```bash
uv run python -B scripts/harness/update_task_state.py <task-id> ready \
     --reason user_approved
   ```

10. Invoke `$webapp-harness:orchestrate-development-cycle` from a fresh agent
    session. By default it processes ready tasks sequentially until the backlog
    is complete or a real blocker is reached. Ask for “only one task” when a
    single-task invocation is desired.

## Gap-based backlog generation

Run `$webapp-harness:generate-backlog` after initialization or whenever the
repository's requirements, implementation, and verification evidence have
drifted. The workflow audits through a read-only subagent and writes a proposal
to a temporary file. It then validates and previews every task before asking
for confirmation.

The deterministic merge command has two phases:

```bash
uv run python -B scripts/harness/merge_backlog_proposal.py \
  --proposal <proposal.json> --plan
uv run python -B scripts/harness/merge_backlog_proposal.py \
  --proposal <proposal.json> --apply --confirmed \
  --expected-sha256 <sha256-from-plan>
```

Apply rejects changed proposal content, duplicate task IDs, dependency cycles,
unknown dependencies, unknown verification profiles, missing gap evidence, and
tasks not in `proposed` status. It appends tasks without replacing existing
backlog entries.

Completed task commits use `<TASK-ID>: <title>` with task, run, acceptance-criterion, and evidence metadata in the body. The created commit hash is recorded afterward in mutable run/state metadata.

## Completed-task archive

Keep `.harness/backlog.json` limited to proposed, ready, active, and blocked
work. At a clean boundary after task commits have been created, archive the
completed records:

```bash
uv run python -B scripts/harness/archive_completed_tasks.py --dry-run
uv run python -B scripts/harness/archive_completed_tasks.py
```

The command refuses to move a task without a completed run record containing
its commit hash and completion time. It appends each full task record to
`.harness/archive/completed-tasks.jsonl`, removes it from the live backlog,
and adds only `task_id`, `commit`, and `completed_at` to
`.harness/completed-tasks.json`. Dependencies may reference that compact
index, so task IDs are never reused. Review and commit the archival change as
ordinary repository maintenance; do not run it before a task's final commit.

Selection writes the active task's complete task object and run ID to
`.harness/current-task.json`. Implementers, validators, and reviewers should
read that extracted document and the active run assets, not the whole backlog.

## Sequential backlog progress

`scripts/harness/backlog_status.py` reports whether the next action is to
resume an active task, select another ready task, stop because the backlog is
complete or empty, wait for proposed-task approval, or report a blocked
dependency chain. The development-cycle skill runs this command before
selection and after every task commit. Its total count includes archived
completed tasks and it separately reports the live and archived counts.

The harness keeps one active task at a time and creates one commit per completed
task. An unbounded invocation can therefore create multiple sequential commits.
Use an explicit one-task or maximum-count request to bound an invocation.
