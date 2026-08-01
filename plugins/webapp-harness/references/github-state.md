# GitHub state contract

GitHub Issues are the only durable lifecycle authority. The plugin, prompts,
schemas, and executable scripts remain local to the installed plugin. Target
repositories receive no `.harness`, harness scripts, test suite, Python
dependency, or instruction fragment.

## Repository objects

- One open issue labeled `harness:control` stores repository-specific
  configuration in a `webapp-harness:config` machine marker.
- Each confirmed proposal creates one parent issue labeled `harness:backlog`.
- Each task is a sub-issue labeled `harness:task` and exactly one
  `harness:status:*` label.
- Native GitHub `blocked by` relationships are the dependency authority.
- Completed issues close with `state_reason: completed`; cancelled and
  superseded issues close with `state_reason: not_planned`.
- Append-only `webapp-harness:event` comments are the lifecycle authority.
  Labels are a queryable projection and must agree with the latest event.

Do not require GitHub Projects, issue forms, repository workflows, custom
organization fields, or a GitHub App. They may be added as optional views or
integrations but cannot become lifecycle authority.

## Task scope

`recommended_paths` are non-exclusive starting points. A delegated worker may
inspect and modify other repository paths when the accepted task requires it.
It must disclose every changed path and explain material movement beyond the
recommendations.

`forbidden_paths` prohibit delegated workers from modifying, deleting,
renaming, or generating into those paths. A worker stops and reports the exact
need before crossing that boundary. The main agent may make an executive
task-level override without asking the user when the change remains within the
authorized outcome. It records a `scope_override` event with exact paths,
operations, reason, and duration, then either edits directly or authorizes a
follow-up worker.

The main agent cannot override system instructions, user instructions,
applicable `AGENTS.md`, secret-handling rules, or authority required for a
materially broader, destructive, production, deployment, or third-party
action. Do not encode those higher-authority constraints as ordinary
task-level forbidden paths.

Never let the main agent and a worker edit overlapping files concurrently.
Any code change after a passed phase records a new implementation event and
returns through verification, independent review, and required browser
validation.

## Machine markers

Issue bodies and comments include one JSON object inside an HTML comment:

```text
<!-- webapp-harness:task
{"schema_version":2,...}
-->
```

Supported marker kinds are `config`, `proposal`, `task`, and `event`. Human
Markdown may surround the marker. Parse only a complete matching marker and
reject duplicate markers of the requested kind.

Task bodies are immutable contracts. Amendments, status changes, phase
results, scope overrides, and completion are append-only events. Every event
contains an event UUID, run UUID when applicable, sequence, previous event
digest, payload, timestamp, and its own SHA-256 digest. Repeated event UUIDs
are idempotent; a gap or broken digest chain blocks advancement.

## Lifecycle

```text
proposed -> ready -> implementing -> verifying -> reviewing
                                                |          \
                                                |           -> completed
                                                -> browser_validating -> completed
```

Product repairs return to `implementing`, then repeat verification and review.
Fixture, profile, tooling, environment, and scope blockers transition directly
to `blocked` without spending product retry budget. A blocked task may return
to `ready`; cancelled and superseded tasks are terminal.

Exactly one task may be active across `implementing`, `verifying`, `reviewing`,
and `browser_validating`. A local lock may prevent two processes in the same
checkout, but it is not durable state. Separate-clone concurrent orchestration
is unsupported; detect multiple remote active tasks and stop.

## Backlog approval

Generate proposals in a temporary directory outside the repository. Validate
and show every task plus the proposal SHA-256. Do not create issues until the
user confirms that exact hash. Confirming a proposal creates `proposed` task
issues; it does not promote them to `ready`. Promotion remains a separate
explicit decision.

Issue creation is resumable. Proposal and task markers carry stable keys and
the confirmed proposal digest so an interrupted apply discovers existing
objects rather than duplicating them.

## Evidence and secrets

Post structured text results as issue events. Bundle binary browser evidence
outside the repository and upload it as an immutable asset on the rolling
`harness-evidence-v1` prerelease. Record the asset URL, size, and SHA-256 in an
event. Do not use expiring Actions artifacts as the only evidence archive.

Never upload credentials, tokens, secrets, production data, or unredacted
sensitive screenshots. Store development credentials in an owner-only local
credential store outside the project and pass only the minimum required
account to the browser controller. Never include credentials in worker
prompts, issue bodies, comments, evidence bundles, logs, or screenshots.

## Offline behavior

Require GitHub before selecting work. A short-lived cache, process lock, or
outbox may live under `git rev-parse --git-path harness/`, but it is never
authoritative and cannot prove a passed phase. If an event cannot be posted,
do not advance, commit, close the issue, or select another task.

## Legacy migration

Migration is plan-first, hash-bound, resumable, and non-destructive. It creates
GitHub issues for unresolved tasks, closed stubs for completed tasks still
needed by dependencies, uploads a complete non-sensitive legacy `.harness`
archive, reports credential-like files excluded from upload, and records the
mapping on the control issue. It never deletes local files.

Only after remote counts, relationships, events, and asset digests validate
may the user separately authorize removal of tracked legacy harness files.
