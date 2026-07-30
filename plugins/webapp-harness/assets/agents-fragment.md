## Sequential development harness

- Use `uv` for the harness Python environment; do not add a harness
  requirements file.
- Validate `.harness` state before selecting or resuming a task.
- Generate backlog tasks only from concrete gap evidence, preview the complete
  proposal, and require explicit user confirmation before appending it.
- Keep generated tasks `proposed` until the user explicitly promotes them.
- Run ready backlog tasks sequentially until completion by default. Honor an
  explicit one-task, bounded-count, or task-selection request.
- Deterministic scripts own task selection and lifecycle transitions; agents
  must not edit lifecycle fields directly.
- Respect each task's allowed and forbidden path scope.
- Run fresh independent logic review after command verification and before
  expensive browser validation. Completion also requires direct rendered-app
  evidence when the task requires it.
- Use the deterministic retry decision; fixture, tooling, environment, and
  scope blockers must not consume product retry budget.
- Create exactly one task-referenced commit after each successful task,
  report the resulting hash, and re-check deterministic backlog status before
  selecting the next task. Do not rewrite tracked run state after committing.
