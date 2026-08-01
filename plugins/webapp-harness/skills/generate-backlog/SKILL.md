---
name: generate-backlog
description: Audit a GitHub issue-backed Webapp Harness repository for evidence-backed implementation, verification, documentation, or user-experience gaps; preview a hash-bound proposal; and create only the explicitly confirmed parent and task issues with native dependencies. Use after initialization or whenever requirements, implementation, tests, or the existing GitHub issue backlog have drifted.
---

# Generate Backlog

Create confirmed GitHub task issues without repository state files.

## Preflight

Read applicable `AGENTS.md` and
`<plugin-root>/references/github-state.md`, resolving the absolute plugin root
from this skill's location. Use absolute plugin paths to resolve resources and
validate remote state:

```bash
python3 <plugin-root>/scripts/github_harness.py resources
python3 <plugin-root>/scripts/github_harness.py validate \
  --root <repo-root> --repo <owner/repo>
```

Require exactly one valid control issue and at least one usable verification
profile. Stop on invalid markers, multiple active tasks, event-chain failures,
missing GitHub access, or absent configuration. Do not select work.

## Audit into a temporary proposal

Create a `mktemp -d` directory outside the repository. Spawn one temporary
read-only audit worker. Give it the installed `backlog-auditor.md`, proposal
and task schemas, configuration snapshot, existing open task snapshots and
relationships, repository instructions, requested scope, relevant requirements,
and matching installed review skills. Do not give it GitHub write permission.
If workers are unavailable, perform the same read-only audit directly.

The schema requires:

- stable proposal keys and native-dependency keys;
- concrete gap evidence and acceptance criteria;
- real verification profiles and browser need;
- non-exclusive `recommended_paths` with reasons;
- only hard delegated-worker `forbidden_paths`, also with reasons.

Recommended paths are guidance, not an allowlist. The main agent may later make
an executive task-level forbidden-path override; higher-authority instructions
and secrets remain outside that mechanism.

## Preview and confirm

Run:

```bash
python3 <plugin-root>/scripts/github_harness.py proposal \
  --root <repo-root> --repo <owner/repo> \
  --proposal <temporary-proposal.json> --plan
```

Repair malformed temporary output without weakening the contract. Present
every task, evidence, criteria, dependencies, verification, recommended paths,
forbidden paths, and the exact proposal SHA-256. Ask for confirmation of that
exact proposal. The invoking request, silence, initialization approval, or a
confirmation for another digest is not approval.

After exact confirmation:

```bash
python3 <plugin-root>/scripts/github_harness.py proposal \
  --root <repo-root> --repo <owner/repo> \
  --proposal <temporary-proposal.json> --apply --confirmed \
  --expected-sha256 <previewed-sha256>
```

Report the parent and task issue URLs. Created tasks remain `proposed`; do not
silently promote or implement them. Promotion to `ready` is a separate explicit
decision recorded with the transition command.

## Boundaries

- Do not create issues before confirmation.
- Do not mutate an existing task contract or reuse a colliding proposal key.
- Do not write `.harness` or any proposal into the repository.
- Do not commit, push, deploy, publish, or start the development cycle.
