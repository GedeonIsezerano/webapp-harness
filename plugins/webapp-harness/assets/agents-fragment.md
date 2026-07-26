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
- Completion requires passed command verification, direct rendered-app browser
  evidence when required, and fresh independent review approval.
- Use the ignored development credential file named by
  `.harness/config.json` only for normal rendered development-app sign-in
  during browser validation; never expose, screenshot, log, or commit its
  values.
- Create exactly one task-referenced commit after each successful task,
  record the resulting hash, and re-check deterministic backlog status before
  selecting the next task.
