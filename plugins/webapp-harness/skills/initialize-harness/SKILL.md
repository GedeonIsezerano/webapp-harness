---
name: initialize-harness
description: Initialize, upgrade, repair, or migrate the GitHub issue-backed sequential web-development harness for the current Git repository without adding harness state files to the repository. Use when a project lacks a harness control issue, has no GitHub remote, still has legacy `.harness` data, needs verified configuration, or needs its first evidence-backed backlog proposal.
---

# Initialize Harness

Configure GitHub as durable lifecycle authority, then preview the first backlog.
Do not copy plugin scripts, prompts, schemas, tests, dependencies, or state into
the target repository.

## Read the contract

Resolve the absolute plugin root from this skill's location and read
`<plugin-root>/references/github-state.md`. Use absolute plugin paths for every
helper invocation:

```bash
python3 <plugin-root>/scripts/github_harness.py resources
```

to resolve installed prompt and schema paths. Read all applicable repository
`AGENTS.md` files before any action.

## Establish the GitHub repository

1. Resolve the Git root. Stop if it is not a Git worktree.
2. Inspect all remotes without assuming `origin` is GitHub.
3. Verify `gh` exists and `gh auth status` succeeds.
4. Resolve the GitHub repository and confirm Issues are enabled. If an existing
   non-GitHub `origin` must remain, use a separate `github` remote.
5. If no GitHub repository exists, obtain the exact owner, repository name,
   visibility, remote name, and whether to push the current branch. Show the
   exact `gh repo create` and push operations and require explicit confirmation
   before creating the repository or pushing. Never infer public/private
   visibility or replace an existing remote.

## Build and apply configuration

Inspect the real framework, package manager, monorepo boundaries, start command,
health URL, lint, typecheck, unit, integration, build, and E2E commands. Include
only commands proven to exist. Put a schema-v2 configuration JSON in a
`mktemp -d` directory outside the repository. Never store credentials.

Preview without writing:

```bash
python3 <plugin-root>/scripts/initialize_harness.py \
  --root <repo-root> --repo <owner/repo> --config <temporary-config.json> --plan
```

Show the target, labels, configuration digest, and control-issue operation.
Require explicit confirmation, then apply the exact configuration:

```bash
python3 <plugin-root>/scripts/initialize_harness.py \
  --root <repo-root> --repo <owner/repo> --config <temporary-config.json> \
  --apply --confirmed
```

The initializer may create labels and one `[Harness] Configuration` issue. It
must not write project files. When the plan reports
`update_requires_confirmation` or `reopen_requires_confirmation`, show the
complete repair and require explicit confirmation, then add
`--update-existing` to the confirmed apply. Never overwrite or reopen the
control issue implicitly.

## Migrate legacy state

If `.harness` exists, preview the non-destructive migration:

```bash
python3 <plugin-root>/scripts/migrate_legacy_harness.py \
  --root <repo-root> --repo <owner/repo> --plan
```

Show the issue count, completion stubs, archive bytes/files, excluded
sensitive-looking files, and migration SHA-256. Require separate explicit
confirmation before `--apply --confirmed --expected-sha256 <digest>`.
Migration is resumable, uploads the complete non-sensitive legacy state
archive, and never deletes local files or uploads credential files.

After validating the remote mapping and archive digest, explain that removal
of tracked legacy `.harness`, `scripts/harness`, `tests/harness`, and harness-only
dependency fragments requires a separate exact cleanup authorization and
commit. Preserve customized or conflicting files.

## Generate the first backlog

Read `../generate-backlog/SKILL.md` and follow it. Initialization approval is
not backlog approval. Stop without selecting or implementing a task.

## Boundaries

- Do not create issue templates, GitHub Actions workflows, local state files,
  or repository instruction fragments.
- Do not install, reinstall, publish, commit, deploy, or push unless separately
  and explicitly authorized.
- Do not claim configuration works until its commands and relevant browser
  startup path are exercised.
