---
name: initialize-harness
description: Initialize, upgrade, or repair the sequential web-development harness in the current Git repository, then audit repository gaps and preview a proposed backlog for explicit user confirmation. Use when a repository does not yet contain `.harness`, when starter files must be merged safely with existing Python or agent configuration, or when an installed harness must be checked against this plugin without starting a product task.
---

# Initialize Harness

Install the repository-native harness, then generate a confirmable proposed
backlog without implementing or selecting a product task.

## Workflow

1. Resolve the Git root from the current working directory. Stop if the target
   is not a Git worktree.
2. Inspect all applicable `AGENTS.md` files plus existing `.agents`, `.codex`,
   `.harness`, `scripts`, `tests`, `docs`, `pyproject.toml`, and `uv.lock`.
3. Resolve the plugin root from this skill's installed path. The collision-aware
   installer is `../../scripts/initialize_harness.py` relative to this skill
   directory.
4. Run the installer in plan mode:

   ```bash
   python3 <plugin-root>/scripts/initialize_harness.py --root <repo-root> --plan
   ```

5. Review every reported conflict. Never overwrite repository files blindly.
   Preserve useful existing configuration and merge only the harness-specific
   portions. If conflicts are intentionally preserved, run:

   ```bash
   python3 <plugin-root>/scripts/initialize_harness.py \
     --root <repo-root> --apply --preserve-conflicts
   ```

   Without conflicts, omit `--preserve-conflicts`.
6. Merge `<plugin-root>/assets/pyproject-fragment.toml` into the repository's
   existing `pyproject.toml`. If none exists, use the fragment as the starting
   file and set project metadata appropriate to the target repository. Do not
   create a requirements file. Deduplicate dependencies, preserve unrelated
   dependency groups and tool settings, retain existing pytest `addopts`, and
   append `tests/harness` to existing pytest `testpaths` instead of replacing
   other test roots.
7. Merge `<plugin-root>/assets/agents-fragment.md` into the root `AGENTS.md`.
   Preserve all existing repository guidance. Do not install repo-local copies
   of these plugin skills unless the user explicitly requests portable mode.
8. Inspect the actual framework, package manager, monorepo boundaries, start
   commands, lint, typecheck, unit, integration, build, and E2E commands.
   Populate `.harness/config.json` only with commands that exist and work.
   Use the verification-profile structure documented in `docs/harness.md`.
   Populate the optional `app` section (`start_command`, `health_url`,
   `notes`) whenever the repository has a discoverable dev server; browser
   validation depends on it and reports `INCOMPLETE` without it.
   Populate optional `browser.playbook_paths`, `fixture_notes`, and
   `profile_notes` only from maintained repository evidence. Never store
   credentials. These shortcuts prevent validators from rediscovering stable
   routes and setup on every task.
   Omit commands that fail discovery checks and report why they were omitted.
9. Preserve existing Git hooks and repository policies. Lifecycle boundaries
   require a fully clean worktree; do not configure path exceptions that could
   leak one task's harness metadata into another task's commit.
10. When upgrading a pre-v0.0.10 harness, reconcile the new schemas and scripts
    first, then preview the lossless migration before using the new validator:

    ```bash
    uv run python -B scripts/harness/migrate_v0_0_10.py --plan
    ```

    Show the exact plan. Apply it only when the user explicitly approves that
    migration, using `--apply --confirmed`. Never infer migration approval from
    permission to initialize or upgrade. If approval is pending, pause the
    upgrade here; old state is not expected to validate against the new schema.
11. Run:

   ```bash
   uv sync --dev
   uv run python -B -c "from pathlib import Path; [compile(path.read_text(), str(path), 'exec') for path in Path('scripts/harness').glob('*.py')]"
   uv run pytest tests/harness
   uv run python -B scripts/harness/validate_state.py
   ```

12. Re-run installer plan mode. Explain any remaining conflicts as intentional
    repository adaptations.
13. Report created and merged files, detected commands, validation results, and
    limitations.
14. Read `../generate-backlog/SKILL.md` relative to this skill directory and
    follow its audit, validation, preview, and confirmation workflow. This is a
    required part of initialization, not a suggestion-only handoff. Never treat
    the user's approval to initialize as approval to write the proposed tasks.
15. After the user confirms, revises, or cancels the proposal, report the
    outcome and suggest `$webapp-harness:generate-backlog` for future gap
    audits. Stop without selecting a task or invoking the cycle skill.

## Safety boundaries

- Do not replace an existing `AGENTS.md`, `pyproject.toml`, `uv.lock`,
  `.harness`, `scripts`, or `tests` tree wholesale.
- Do not run `select_next_task.py`.
- Do not implement product work.
- Do not append generated backlog tasks without the separate confirmation
  required by the generate-backlog skill.
- Do not commit unless the user explicitly requests it.
- Do not claim browser tooling is configured until it is exercised in the
  target application.
