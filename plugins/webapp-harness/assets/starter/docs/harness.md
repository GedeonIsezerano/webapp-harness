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
5. Submit `SETUP_PROMPT.md` in a Codex setup thread.
6. Let that thread inspect real commands, browser startup, Git policy, and repository structure, then update `.harness/config.json` and tests.
7. Confirm the setup thread stops without selecting a backlog task.
8. Populate `.harness/backlog.json` and validate it.
9. Invoke `$webapp-harness:orchestrate-development-cycle` from a fresh Codex
   thread to process exactly one task.

Completed task commits use `<TASK-ID>: <title>` with task, run, acceptance-criterion, and evidence metadata in the body. The created commit hash is recorded afterward in mutable run/state metadata.
