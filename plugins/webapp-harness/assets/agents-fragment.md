## Sequential development harness

- Use `uv` for the harness Python environment; do not add a harness
  requirements file.
- Validate `.harness` state before selecting or resuming a task.
- Generate backlog tasks only from concrete gap evidence, preview the complete
  proposal, and require explicit user confirmation before appending it.
- Keep generated tasks `proposed` until the user explicitly promotes them.
- Run exactly one backlog task per development-cycle invocation.
- Deterministic scripts own task selection and lifecycle transitions; agents
  must not edit lifecycle fields directly.
- Respect each task's allowed and forbidden path scope.
- Completion requires passed command verification, direct rendered-app browser
  evidence when required, and fresh independent review approval.
- Create exactly one task-referenced commit after successful completion, record
  the resulting hash, and stop without starting another task.
