---
name: orchestrate-development-cycle
description: Run or resume exactly one task through the installed `.harness` sequential development lifecycle. Use in an initialized repository when one ready or active backlog task should be implemented, command-verified, browser-validated when required, independently reviewed, committed, recorded, and then stopped without beginning another task.
---

# Orchestrate Development Cycle

Run one task only. The deterministic scripts own state validation, task
selection, lifecycle transitions, result recording, verification, and commit
creation. Agents must not edit lifecycle fields directly.

## Preflight

1. Read the applicable repository instructions and `.harness/config.json`,
   `.harness/state.json`, and `.harness/backlog.json`.
2. Run:

   ```bash
   uv run python scripts/harness/validate_state.py
   uv run python scripts/harness/check_repo_clean.py --before-task
   ```

3. Stop on invalid state, an in-progress Git operation, unexpected dirty files,
   missing dependencies, or no eligible task. Report the exact blocker.
4. If an active task exists, resume its recorded phase. Otherwise run:

   ```bash
   uv run python scripts/harness/select_next_task.py
   ```

5. Read the selected task, all acceptance criteria, allowed and forbidden
   paths, verification profiles, retry limits, and the active run record.

## Implement

Spawn one temporary implementation subagent. This skill explicitly authorizes
that delegation. Direct it to read
`.harness/prompts/implementer.md` from the repository, then give it:

- the selected task and acceptance criteria;
- allowed and forbidden paths;
- applicable repository instructions;
- the implementation-result schema;
- the active run asset paths it must inspect;
- any installed task-specific skills it should use, without invoking this
  orchestration skill recursively;
- the instruction to plan internally, make no lifecycle edits, and create no
  commit.

Persist its JSON result and record it with:

```bash
uv run python scripts/harness/record_result.py implementation-result <result.json>
uv run python scripts/harness/update_task_state.py <task-id> verifying \
  --reason implementation_finished
```

Reject malformed or out-of-scope results.

## Verify and repair

Run:

```bash
uv run python scripts/harness/verify_task.py
```

If verification fails or is incomplete:

1. Transition back to `implementing`.
2. Spawn a repair implementer, direct it to read
   `.harness/prompts/repair.md`, and provide only the failing evidence plus the
   corresponding persisted run assets.
3. Record its result, transition to `verifying`, and rerun affected checks.
4. Stop as blocked after the configured verification retry limit.

Never treat zero executed checks as passed.

## Browser validation

When the task requires browser or visual verification, spawn a fresh,
independent browser validator. Direct it to read
`.harness/prompts/browser-validator.md`, the active task/run assets, and the
installed Browser or Chrome control skill appropriate to the session. Require
direct interaction with the rendered application and structured evidence for
every browser criterion.

Use Browser or Chrome tooling actually available in the session. Unavailable
tooling, unobserved criteria, stale console output, or test output without
rendered-app observation means `INCOMPLETE`, not passed.

Record the result:

```bash
uv run python scripts/harness/record_result.py browser-result <result.json>
```

Repair and rerun within the browser retry limit. Do not advance with failed or
incomplete required browser evidence.

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
uv run python scripts/harness/record_result.py review <result.json>
```

An approval containing a blocking finding is invalid. For
`CHANGES_REQUIRED`, transition to `implementing`, run a bounded repair, and
repeat affected verification, browser validation, and review within the retry
limit.

## Complete and stop

After approval:

```bash
uv run python scripts/harness/update_task_state.py <task-id> completed \
  --reason review_approved
uv run python scripts/harness/create_task_commit.py
uv run python scripts/harness/check_repo_clean.py --before-next-task
```

Confirm the commit contains only allowed task paths plus harness evidence.
Report the task, run, acceptance criteria, verification, browser result, review
verdict, commit hash, and any remaining risk.

Stop. Never select or begin another task in the same invocation.

## Non-negotiable boundaries

- Exactly one task and one final task commit per invocation.
- No planning-only subagent or planning lifecycle stage.
- Fresh implementation, browser-validation, and review contexts.
- No agent edits to lifecycle fields.
- No completion without passed verification, required browser evidence, and
  independent approval.
- No deployment or external write unless the selected task explicitly
  authorizes it.
