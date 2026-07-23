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
$webapp-harness:orchestrate-development-cycle
```

`/plugins` manages installation and `/skills` opens the skill picker. Codex
plugins do not provide arbitrary custom slash commands.

Initialization leaves the target repository changes uncommitted for review.
Commit that baseline and return the target repository to a clean state before
running the first development cycle.

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
