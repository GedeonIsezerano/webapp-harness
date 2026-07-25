# Backlog audit subagent

Audit the repository for concrete gaps and return a proposed backlog. Remain
read-only: do not edit product files, harness state, or Git history.

## Read before auditing

Read:

- all applicable `AGENTS.md` files;
- `.harness/config.json`, `.harness/backlog.json`, `.harness/completed-tasks.json`, and
  `.harness/schema/backlog-proposal.schema.json`;
- `.harness/schema/task.schema.json`;
- `docs/harness.md`;
- requirements, product documentation, source, tests, CI configuration, and
  package scripts relevant to the requested audit scope.

Inspect the merge contract with
`uv run python -B scripts/harness/merge_backlog_proposal.py --help` so the
returned proposal matches it without creating bytecode in the repository. Use installed
technology-specific audit or review skills when they match the repository.
Read each selected skill fully before acting. Do not invoke
`$webapp-harness:generate-backlog` or
`$webapp-harness:orchestrate-development-cycle` recursively.

## Audit

- Compare documented or clearly established behavior with implemented and
  verified behavior.
- Use source locations, failing checks, missing coverage, or direct rendered
  application observations as evidence. Do not invent requirements.
- Prefer independently deliverable tasks. Split tasks whose acceptance
  criteria or path scope are too broad for one development cycle.
- Give every task a stable unused ID, a priority where lower values run first
  and 1 is the highest priority, explicit dependencies, testable acceptance
  criteria, existing verification profile names, and narrow allowed and
  forbidden paths.
- Make `allowed_paths` cover everything an acceptance criterion requires,
  including co-located test files and repository config the criterion must
  change. A task whose criteria demand artifacts its own scope forbids cannot
  complete.
- Require at least one configured verification profile per task. If the
  harness has no usable profile for a gap, report that setup blocker instead
  of proposing a task that cannot complete.
- Set every task status to `proposed`.
- Add at least one `gap_evidence` item to every task. Each item must identify a
  repository-relative location and explain the observed gap.
- Require browser validation for user-visible behavior. Set `requires_browser`
  from the paths the task will touch, not only its `type`: any task that edits
  UI routes, pages, components, or user-visible styling requires browser
  validation. Do not claim a visual or browser gap was observed unless
  rendered application evidence was actually collected.
- Exclude work already represented by an existing backlog task unless the
  evidence shows a separate gap. Do not reuse an ID from the completion index.

## Return

Write only the requested temporary proposal file. Its contents must be JSON
matching `.harness/schema/backlog-proposal.schema.json`. Do not write
`.harness/backlog.json`.
