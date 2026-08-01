---
name: orchestrate-development-cycle
description: Run or resume ready GitHub issue-backed Webapp Harness tasks sequentially through implementation, verification, independent logic review, required rendered browser validation, evidence upload, and one task-referenced commit. Use to drain an initialized GitHub issue backlog or run an explicitly bounded eligible issue set without repository-local harness state.
---

# Orchestrate Development Cycle

Treat GitHub task issues and append-only events as durable authority. Resolve
the absolute plugin root from this skill's location, then read
`<plugin-root>/references/github-state.md`, all applicable `AGENTS.md`, and the
installed resource paths before work. Use absolute plugin paths for all helper
invocations below.

## Resolve the stop policy

- With no explicit limit, continue until complete or genuinely blocked.
- Honor an explicit one-task, count, or issue-number boundary.
- Keep one active task and one final task commit at a time.

## Preflight and select

Run:

```bash
python3 <plugin-root>/scripts/github_harness.py validate \
  --root <repo-root> --repo <owner/repo>
python3 <plugin-root>/scripts/github_harness.py status \
  --root <repo-root> --repo <owner/repo>
```

Resume the single active issue. Otherwise require a clean Git worktree and
select the first dependency-satisfied ready issue by priority then issue number.
Stop for proposed-task promotion, dependency stalls, blockers, invalid remote
state, or unavailable GitHub. Separate-clone concurrent orchestration is
unsupported.

Transition a selected issue from `ready` to `implementing` with a fresh run
UUID and exact reason, then obtain its validated context:

```bash
python3 <plugin-root>/scripts/github_harness.py transition \
  --root <repo-root> --repo <owner/repo> --issue <number> \
  --to implementing --reason selected --run-id <uuid>
python3 <plugin-root>/scripts/github_harness.py context \
  --root <repo-root> --repo <owner/repo> --issue <number>
```

## Implement

Spawn one implementation worker with the issue URL/number, task/config/event
snapshot, run UUID, applicable instructions, installed implementer prompt,
result schema, and matching skills. The worker cannot write GitHub or commit.

`recommended_paths` are non-exclusive. `forbidden_paths` are absolute for the
worker. If it needs one, it stops before touching it. The main agent makes the
executive decision: reject it, edit the file directly, or record an exact
override before authorizing a follow-up worker:

```bash
python3 <plugin-root>/scripts/github_harness.py scope-override \
  --root <repo-root> --repo <owner/repo> --issue <number> --run-id <uuid> \
  --path <path> --operation modify --reason <reason>
```

Do not ask the user for a routine task-level override that remains within the
accepted outcome. Ask only when it crosses user/repository authority, expands
scope materially, or requires destructive, production, deployment, purchase,
or third-party action. Never let parent and worker edit overlapping files
concurrently.

Validate the returned JSON in a temporary directory and record it with
`record-result --kind implementation`. Then transition to `verifying`.

## Verify and retry

Run every configured verification profile directly as argument arrays, with no
shell and at least one executed check. Record the structured result. Only
`product` failures consume retry budget; `fixture`, `profile`, `tooling`,
`environment`, and `scope` block immediately with exact evidence.

After every non-passing verification, review, or browser result, obtain the
deterministic decision before changing phase:

```bash
python3 <plugin-root>/scripts/github_harness.py retry-status \
  --root <repo-root> --repo <owner/repo> --issue <number> \
  --run-id <uuid> --phase <verification|review|browser>
```

For a product repair, transition to `implementing`, use a fresh repair worker,
record a new implementation result, and repeat verification. Any main-agent
code edit is also a new implementation result and invalidates later evidence.

## Review before browser validation

After passed verification, transition to `reviewing`. Capture the current diff
outside the repository and spawn a fresh read-only reviewer with the issue
context, ordered events, diff, browser plan when required, reviewer prompt,
schema, and matching review skills. Record its result.

For changes required, return through implementation and verification, collect
a fresh diff, and obtain a fresh review. Never carry stale approval forward.

## Browser validation

When required, transition to `browser_validating`. Preflight the configured app
health and start it only with the configured command when needed. Create a
temporary evidence directory outside the repository. Spawn a fresh validator
with the exact browser/visual/E2E criteria, context snapshot, browser prompt,
schema, playbooks, and evidence directory.

Use current rendered interaction and persisted state. Record the result. For a
passing result, upload the redacted binary bundle and record its immutable URL
and digest:

```bash
python3 <plugin-root>/scripts/github_harness.py upload-evidence \
  --root <repo-root> --repo <owner/repo> --issue <number> \
  --run-id <uuid> --directory <temporary-evidence-dir>
```

Never upload credentials, secrets, production data, or sensitive screenshots.
Product repairs repeat implementation, verification, review, and browser work.

## Commit and complete

After every required gate passes, inspect the actual diff, preserve unrelated
work, and stage an explicit allowlist of the files actually changed for this
task. Create exactly one commit using the configured subject and trailers:

```text
Harness-Issue: #<number>
Harness-Run: <uuid>
```

Record completion only after the commit succeeds:

```bash
python3 <plugin-root>/scripts/github_harness.py transition \
  --root <repo-root> --repo <owner/repo> --issue <number> \
  --to completed --reason <commit-sha> --run-id <uuid>
```

Require a clean worktree, validate remote state, report the issue/evidence/
commit URLs, and continue according to the stop policy. If GitHub cannot record
an event, do not advance, commit, close, or select another task.

## Non-negotiable boundaries

- Main agent owns GitHub lifecycle writes and executive scope overrides.
- Workers never edit GitHub state or make final commits.
- Logic review precedes browser validation.
- No completion with stale, missing, or hash-invalid evidence.
- No repository-local harness state or evidence.
