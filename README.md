# Webapp Harness plugin

This repository manages a local Codex plugin that installs and operates a
repository-native, sequential web-application development harness.

The maintained plugin source lives at `plugins/webapp-harness/`. Its normalized
starter assets are the source of truth for files installed into target
repositories.

## Repository layout

```text
.agents/plugins/marketplace.json       Local marketplace catalog
plugins/webapp-harness/
  .codex-plugin/plugin.json            Plugin identity and UI metadata
  skills/                              Codex workflows
  scripts/initialize_harness.py        Safe repository installer
  assets/starter/                      Files installed into target repositories
tests/                                 Plugin management tests
```

## Develop and validate

```bash
CODEX_SYSTEM_SKILLS="${CODEX_HOME:-$HOME/.codex}/skills/.system"
uv sync --dev
uv run pytest
uv run python "$CODEX_SYSTEM_SKILLS/skill-creator/scripts/quick_validate.py" \
  plugins/webapp-harness/skills/initialize-harness
uv run python "$CODEX_SYSTEM_SKILLS/skill-creator/scripts/quick_validate.py" \
  plugins/webapp-harness/skills/generate-backlog
uv run python "$CODEX_SYSTEM_SKILLS/skill-creator/scripts/quick_validate.py" \
  plugins/webapp-harness/skills/orchestrate-development-cycle
uv run python "$CODEX_SYSTEM_SKILLS/plugin-creator/scripts/validate_plugin.py" \
  plugins/webapp-harness
```

## Install this local marketplace

Marketplace registration changes global Codex state, so it is intentionally a
separate step:

```bash
codex plugin marketplace add "$(pwd)"
codex plugin add webapp-harness@webapp-harness
```

Start a new Codex chat after installation. In a target repository, use:

```text
$webapp-harness:initialize-harness
$webapp-harness:generate-backlog
$webapp-harness:orchestrate-development-cycle
```

`/plugins` manages installation and `/skills` opens the skill picker. Codex
plugins do not provide arbitrary custom slash commands.

Initialization leaves the target repository changes uncommitted for review and
continues into a repository-gap audit. It previews the generated backlog and
requires separate, explicit confirmation before adding any task. Confirmed
tasks are added as `proposed`.

Run `$webapp-harness:generate-backlog` independently whenever requirements,
implementation, tests, or product behavior have drifted. The skill validates
the proposal, shows every task and its evidence, and will not mutate the
backlog until you confirm the exact preview. Promote accepted tasks to `ready`
before running a development cycle.

Commit the initialized baseline and return the target repository to a clean
state before running the first development cycle.

## Upgrade a published release

After a new version is committed and pushed, refresh the Git-backed marketplace
snapshot and reinstall the plugin:

```bash
codex plugin marketplace upgrade webapp-harness
codex plugin add webapp-harness@webapp-harness
codex plugin list | rg webapp-harness
```

Start a new Codex chat so the refreshed skills are loaded. The plugin update
does not rewrite harness files that were copied into application repositories.
Enter each initialized repository and run:

```text
$webapp-harness:initialize-harness
```

The initializer plans the upgrade, creates newly introduced files, and
preserves conflicting repository adaptations for review. After setup
validation it also previews a new gap-based backlog and asks separately before
appending any proposed tasks.

## Update an installed development build

Validate first, then refresh the manifest cachebuster and reinstall:

```bash
CODEX_SYSTEM_SKILLS="${CODEX_HOME:-$HOME/.codex}/skills/.system"
python3 "$CODEX_SYSTEM_SKILLS/plugin-creator/scripts/update_plugin_cachebuster.py" \
  "$(pwd)/plugins/webapp-harness"
codex plugin add webapp-harness@webapp-harness
```

Start a new chat after reinstalling. Do not hand-edit Codex's plugin cache or
global plugin state.

## Versioning

- Use semantic versions in `.codex-plugin/plugin.json`.
- Change the semantic version for intentional releases.
- Use the plugin-creator cachebuster during local iteration.
- Keep the marketplace entry pointed at `./plugins/webapp-harness`.
- Commit source changes only after all validation passes.
