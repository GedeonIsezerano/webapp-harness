# Harness architecture

The harness is a repository-native, deterministic, sequential task runner. The
repository is durable memory; agents do not own lifecycle state.

## Runtime model

`.harness/state.json` is intentionally tiny. It records only the active task,
active run, and a completed task waiting for its final commit. Global
transition history lives append-only in
`.harness/archive/transitions.jsonl`; the active run also carries its relevant
transitions.

Each run has one canonical `run.json`. Phase results are ordered entries under
`results.implementation`, `results.verification`, `results.review`, and
`results.browser_validation`. The harness does not write duplicate
`implementation-result.json`, `verification.json`, `review.json`, or
`browser-result.json` files. Ordered sequence numbers prevent stale evidence
from advancing a repaired task.

The lifecycle is:

```text
ready -> implementing -> verifying -> reviewing
                                      |          \
                                      |           -> completed (no browser)
                                      -> browser_validating -> completed
```

Any product repair returns to implementation, then requires new verification
and review. Logic review runs before browser validation so review-driven code
repairs do not invalidate an expensive browser pass.

## Python and verification

Use `uv`, the repository `pyproject.toml`, and committed `uv.lock`:

```bash
uv sync --dev
uv run pytest tests/harness
uv run python -B scripts/harness/validate_state.py
```

`.harness/config.json` maps verification profile names to ordered argument
arrays. Commands run directly without a shell:

```json
{
  "verification_profiles": {
    "quality": [
      {"name": "Lint", "command": ["npm", "run", "lint"]},
      {"name": "Typecheck", "command": ["npm", "run", "typecheck"]}
    ],
    "unit": [
      {"name": "Unit tests", "command": ["npm", "test"]}
    ]
  }
}
```

Only configure commands proven to exist. Zero executed checks are
`INCOMPLETE`, never passed.

`retry_limits` are maximum counted product failures per phase. After a
non-passing result, inspect the deterministic decision:

```bash
uv run python -B scripts/harness/retry_status.py verification
uv run python -B scripts/harness/retry_status.py review
uv run python -B scripts/harness/retry_status.py browser
```

Only `product` failures consume verification/browser retry budget. Missing
fixtures, profiles, tooling, environment, or scope block immediately, retain
their classification, and record an exact `blocker` instead of causing
repeated blind attempts.

## Browser validation

Configure application startup and health when discoverable:

```json
{
  "app": {
    "start_command": ["npm", "run", "dev"],
    "health_url": "http://localhost:3000",
    "notes": "Use documented seeded accounts only."
  }
}
```

Persist stable navigation, fixture, and role-profile knowledge in config
instead of making every validator rediscover it:

```json
{
  "browser": {
    "playbook_paths": ["tests/e2e/playbooks/onboarding.md"],
    "fixture_notes": ["Seed with the documented local fixture command."],
    "profile_notes": ["Customer and Admin require independently connected profiles."]
  }
}
```

Only reference maintained repository files and non-secret notes. A playbook
reduces exploration but never substitutes for current rendered observation.

Selection creates `browser-plan.json` containing exactly the browser, visual,
and E2E acceptance criteria. The validator:

1. preflights health, fixtures, independent profiles, and tooling once;
2. groups criteria into the fewest coherent journeys;
3. reuses navigation and fixture state;
4. captures screenshots at proof states rather than after every action;
5. may reference one screenshot from several criteria when it visibly proves
   each;
6. verifies persisted state and finishes relevant flows with a fresh
   page/console/network observation.

Evidence stays under `.harness/runs/<run-id>/evidence/`. A passing result must
cover the exact plan through direct rendered-app interaction. Browser windows
or tabs are not assumed to isolate identities; use independently connected
profiles where simultaneous roles matter.

Canonical control surfaces are `browser_use`, `chrome_control`,
`computer_use`, and `playwright`. `other` may describe a non-passing attempt
but cannot pass.

## Backlog and commits

Lower priority values run first. Reprioritize without editing lifecycle fields:

```bash
uv run python -B scripts/harness/reprioritize.py <task-id> [<task-id> ...]
```

Replace a proposed, ready, or blocked task's dependency list at a clean
lifecycle boundary without hand-editing backlog JSON:

```bash
uv run python -B scripts/harness/update_task_dependencies.py <task-id> \
  --set <dependency-id> [<dependency-id> ...] --reason <reason>
```

The command validates IDs and cycles and writes a cold audit event. Obsolete
proposed, ready, or blocked tasks may transition deterministically to
`cancelled` or `superseded`; dependencies on those retired tasks remain
unsatisfied until explicitly rewritten.

The deprecated `verification.requires_e2e` flag is ignored; E2E need is derived
from each acceptance criterion's verification kinds.

The sequential harness always creates one final task commit.
`commit.subject_format` is effective and supports `{task_id}` and `{title}`.
The old `commit.required: true` field is accepted only for upgrade
compatibility and should be removed.

Task boundaries require a fully clean Git worktree. v0.0.10 removes
`repository.allowed_dirty_paths`: allowing all `.harness/` changes hid
post-commit metadata and could leak it into the next task's commit.

## Completed-task archive

After the final task commit is known, cold-store completed tasks and runs:

```bash
uv run python -B scripts/harness/archive_completed_tasks.py --dry-run
uv run python -B scripts/harness/archive_completed_tasks.py
```

The command appends the full task to
`.harness/archive/completed-tasks.jsonl`, keeps a compact dependency entry in
`.harness/completed-tasks.json`, and moves the run directory to
`.harness/archive/runs/<run-id>`. It removes only standalone result files that
are exactly redundant with canonical run data. It never guesses that an
unreferenced screenshot is safe to delete.

Archive maintenance is a separate change because a Git commit cannot contain
its own hash. Do not mix it into an unrelated product-task commit.

## Upgrade existing v0.0.8 state

After reconciling starter conflicts during initialization, preview the lossless
state/run migration:

```bash
uv run python -B scripts/harness/migrate_v0_0_10.py --plan
uv run python -B scripts/harness/migrate_v0_0_10.py --apply --confirmed
uv run python -B scripts/harness/validate_state.py
```

Apply only when the plan reports `clean_lifecycle_boundary: true`. Finish or
block an active legacy run before changing lifecycle contracts.

Migration moves legacy global transitions to cold JSONL, converts embedded
phase results to ordered canonical entries, and deletes only exact duplicate
standalone result files. It also removes the old `plugin-install.json`
provenance file, which no runtime or upgrade decision consumed. Historical run
directories for task IDs already in the completion index move to
`.harness/archive/runs/`, including earlier failed attempts for tasks that
eventually completed. Runs for unresolved tasks stay hot. Review the plan before
applying it; `unresolved_run_directories_retained` makes that conservative
remainder explicit instead of deleting or silently archiving it. The migration
also removes deprecated `repository`, `commit.required`, and live-task
`requires_e2e` fields after showing their counts in the plan.

## Backlog generation and progress

Use `$webapp-harness:generate-backlog` for an evidence-backed proposal. The
two-phase merge remains hash-bound and requires explicit confirmation:

```bash
uv run python -B scripts/harness/merge_backlog_proposal.py \
  --proposal <proposal.json> --plan
uv run python -B scripts/harness/merge_backlog_proposal.py \
  --proposal <proposal.json> --apply --confirmed \
  --expected-sha256 <previewed-sha256>
```

`backlog_status.py` is the source of truth for resume, selection, completion,
approval waits, and stalls. Agents read `.harness/current-task.json` and the
active run, not the entire backlog or completion archive.
