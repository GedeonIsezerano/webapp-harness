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

10. Invoke `$webapp-harness:orchestrate-development-cycle` from a fresh Codex
    thread. By default it processes ready tasks sequentially until the backlog
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

## Sequential backlog progress

`scripts/harness/backlog_status.py` reports whether the next action is to
resume an active task, select another ready task, stop because the backlog is
complete or empty, wait for proposed-task approval, or report a blocked
dependency chain. The development-cycle skill runs this command before
selection and after every task commit.

The harness keeps one active task at a time and creates one commit per completed
task. An unbounded invocation can therefore create multiple sequential commits.
Use an explicit one-task or maximum-count request to bound an invocation.
