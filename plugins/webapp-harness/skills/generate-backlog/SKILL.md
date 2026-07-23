---
name: generate-backlog
description: Audit an initialized Webapp Harness repository for evidence-backed implementation, verification, documentation, or user-experience gaps; generate a validated proposed task list; show it to the user; and append only the explicitly confirmed proposal to `.harness/backlog.json`. Use after harness initialization, when requirements and implementation have drifted, when failing checks expose missing work, or when the user asks to identify gaps or build, refresh, or extend the harness backlog.
---

# Generate Backlog

Generate proposed tasks from observed repository gaps. Preview the complete
proposal and obtain fresh, explicit user confirmation before changing the
durable backlog.

## Preflight

1. Resolve the Git root and read all applicable `AGENTS.md` files.
2. Require an initialized harness with `.harness/config.json`,
   `.harness/backlog.json`, `.harness/schema/backlog-proposal.schema.json`, and
   `scripts/harness/merge_backlog_proposal.py`.
3. Run:

   ```bash
   uv run python -B scripts/harness/validate_state.py
   ```

   Stop on invalid state. Do not select or implement a task.
4. Require at least one usable entry in
   `.harness/config.json.verification_profiles`. If none exists, stop and
   report that initialization must configure a real command before runnable
   backlog tasks can be proposed.
5. Determine the audit scope from the user's request. If none was supplied,
   audit the repository's documented product behavior, implementation, tests,
   verification commands, and existing backlog without inventing requirements.

## Audit into a temporary proposal

Create a dedicated temporary directory with `mktemp -d`. Keep the proposal
outside the repository until it is confirmed.

Spawn one temporary read-only audit subagent. This skill explicitly authorizes
that delegation. Direct it to read `.harness/prompts/backlog-auditor.md`, then
give it:

- the repository root and requested audit scope;
- the exact temporary proposal path it must write;
- the existing backlog, proposal schema, task schema, and harness config paths;
- relevant requirement and product documentation paths;
- applicable repository instructions;
- installed technology-specific audit or review skills it should use.

Do not give it permission to modify the repository. If subagents are
unavailable, perform the same read-only audit in the current context and write
the temporary proposal yourself.

Run the deterministic proposal validator:

```bash
uv run python -B scripts/harness/merge_backlog_proposal.py \
  --proposal <temporary-proposal.json> --plan
```

Repair malformed proposals in the temporary file and rerun `--plan`. Do not
weaken the schema or merge contract to make a proposal pass.

## Preview and confirm

Present every proposed task to the user before applying it. Include:

- ID, title, priority, and dependencies;
- the observed gap and its evidence location;
- acceptance criteria and verification requirements;
- allowed and forbidden paths;
- the proposal SHA-256 printed by `--plan`.

Then stop and ask: “Confirm adding these tasks to `.harness/backlog.json` as
`proposed`?”

The user may confirm all tasks, request edits or a subset, or cancel. The
request that invoked this skill is not confirmation. Never infer approval from
silence, initialization approval, or a general request to generate a backlog.

If the user requests any edit or subset, revise the temporary proposal, rerun
`--plan`, show the full revised preview and new SHA-256, and request fresh
confirmation. Do not reuse confirmation for a different proposal hash.

## Apply only the confirmed proposal

After explicit confirmation, apply the exact previewed file and hash:

```bash
uv run python -B scripts/harness/merge_backlog_proposal.py \
  --proposal <temporary-proposal.json> \
  --apply --confirmed --expected-sha256 <previewed-sha256>
uv run python -B scripts/harness/validate_state.py
```

Report the appended task IDs. Tasks remain `proposed`; do not silently make
them runnable. Explain that an approved task can be promoted with:

```bash
uv run python -B scripts/harness/update_task_state.py <task-id> ready \
  --reason user_approved
```

End by noting that `$webapp-harness:generate-backlog` can be run again whenever
new gaps appear.

## Boundaries

- Never overwrite, delete, or mutate an existing backlog task.
- Never write `.harness/backlog.json` without explicit confirmation.
- Never add speculative tasks without concrete gap evidence.
- Never convert generated tasks from `proposed` to `ready`.
- Never start the development-cycle skill, commit, deploy, publish, or push.
