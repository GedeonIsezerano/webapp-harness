# Webapp Harness plugin repository

This repository is the source of truth for the local Codex plugin in
`plugins/webapp-harness/`.

## Editing rules

- Edit the normalized starter under `plugins/webapp-harness/assets/starter/`.
- Keep the plugin name, plugin folder, and marketplace entry synchronized as
  `webapp-harness`.
- Do not add `.mcp.json`, `.app.json`, or hooks unless the plugin actually
  requires those capabilities.
- Do not copy the plugin skills into the starter's `.agents/skills`; installed
  plugin skills and repository skills with the same name appear as duplicates.
- Do not install, reinstall, publish, or commit the plugin unless the user
  explicitly asks.

## Required validation

Run all of the following after changing plugin code, skills, or starter assets:

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

When updating an already installed local plugin, use the plugin-creator
cachebuster helper and reinstall from the configured local marketplace. Start a
new Codex thread before testing updated skills.
