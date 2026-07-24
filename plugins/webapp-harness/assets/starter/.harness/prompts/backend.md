# Backend task guidance

Read this when the active task `type` is `backend`, or when it changes server,
API, job, or database code. Apply it in addition to your role prompt
(implementer, repair, or reviewer).

## Implementation

- Match the existing framework, layering, and naming. Do not introduce a new
  framework, ORM, or dependency for a single task.
- Keep API contracts stable or version them. Do not silently change request or
  response shapes, status codes, or field names that callers depend on.
- Validate input at the boundary. Reject malformed requests with correct status
  codes and safe error bodies.
- Never trust client-supplied identity or role. Enforce authorization where the
  data is read or written.
- Wrap related writes in a transaction and leave the database consistent on
  failure. Make retried operations idempotent where clients can retry.
- Add a migration for every schema change and keep it backward-compatible with
  the previously deployed code. Never edit a migration that has already run.
- Handle error and edge paths: not-found, conflict, timeout, partial failure.
  Do not swallow exceptions or report success when the write did not happen.
- Never hardcode or log secrets, tokens, or credentials. Read them from the
  configured environment or secret store and keep them out of logs and errors.
- Add integration tests that exercise the real path, request to response or job
  to stored result, covering success, validation failure, and authorization
  denial.

## Review

- Confirm every acceptance criterion against the code and the recorded
  evidence.
- Check data integrity: transactions, constraints, migration safety, and
  idempotency under retry.
- Check authorization and input validation at every entry point the diff
  touches.
- Check that error handling returns correct status codes and does not leak
  internal detail or secrets.
- Confirm integration coverage for the changed behavior. Unit tests alone do
  not prove an API or database path works.
- Treat missing, stale, or inconsistent evidence as a finding.
