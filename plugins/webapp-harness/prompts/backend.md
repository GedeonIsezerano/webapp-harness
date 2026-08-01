# Backend guidance

Apply this in addition to the implementation, repair, or review prompt when a
task changes server, API, job, database, or authorization behavior.

- Preserve or explicitly version public contracts.
- Validate inputs at the boundary and derive identity from trusted context.
- Enforce authorization at every data read and write.
- Keep related writes atomic and retried operations idempotent.
- Add backward-compatible migrations; never rewrite applied history.
- Exercise not-found, conflict, timeout, partial-failure, validation, and
  permission-denied paths.
- Never hardcode, log, upload, or prompt with secrets.
- Add integration coverage through the real boundary when practical.
- Review data integrity, concurrency, authorization, redaction, error safety,
  and evidence freshness before approval.
