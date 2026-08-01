# Webapp Harness plugin

This repository manages a local Codex plugin that operates a sequential,
GitHub issue-backed web-application development harness.

The maintained plugin source lives at `plugins/webapp-harness/`. Skills,
scripts, prompts, schemas, and reference material remain in the plugin. Target
repositories receive no harness state or copied tooling.

## Repository layout

```text
.agents/plugins/marketplace.json       Local marketplace catalog
plugins/webapp-harness/
  .codex-plugin/plugin.json            Plugin identity and UI metadata
  skills/                              Codex workflows
  scripts/                             GitHub lifecycle and migration tools
  prompts/                             Local worker contracts
  schemas/                             Local machine-readable contracts
  references/github-state.md           Canonical remote-state design
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

Initialization verifies or guides creation of the GitHub repository, creates a
configuration issue after confirmation, and continues into a repository-gap
audit. It does not add files to the target repository. Backlog creation requires
separate confirmation of the exact proposal SHA-256; confirmed tasks are added
as `proposed` GitHub sub-issues with native dependency relationships.

Run `$webapp-harness:generate-backlog` independently whenever requirements,
implementation, tests, or product behavior have drifted. The skill validates
the proposal, shows every task and its evidence, and will not create GitHub
issues until you confirm the exact preview. Promote accepted issues to `ready`
before running a development cycle.

`$webapp-harness:orchestrate-development-cycle` processes ready tasks
sequentially until the backlog is complete or it reaches a real blocker. Every
task retains its own implementation, verification, logic-review,
browser-validation, evidence, and commit boundary. Lifecycle events and text
results are append-only issue comments; binary browser evidence is stored as
an immutable release asset. Logic review precedes browser validation, and
non-product blockers do not consume product retries. Ask it to run
“only one task,” “up to N tasks,” or a specific eligible task when you want a
bounded invocation.

Existing `.harness` repositories use the initialization skill's plan-first,
hash-bound migration. It creates remote issues, dependencies, lifecycle events,
and a redacted legacy archive without deleting local files. Removing tracked
legacy files remains a separate, explicitly authorized cleanup.

## Upgrade a published release

After a new version is committed and pushed, refresh the Git-backed marketplace
snapshot and reinstall the plugin:

```bash
codex plugin marketplace upgrade webapp-harness
codex plugin add webapp-harness@webapp-harness
codex plugin list | rg webapp-harness
```

Start a new Codex chat so the refreshed skills are loaded. Enter each managed
repository and run:

```text
$webapp-harness:initialize-harness
```

The initializer validates or repairs the control issue after explicit
confirmation. It also previews a new gap-based backlog and asks separately
before creating any proposed issues.

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
