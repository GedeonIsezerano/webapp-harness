from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator


SCRIPT = (
    Path(__file__).parents[1]
    / "plugins"
    / "webapp-harness"
    / "scripts"
    / "initialize_harness.py"
)
STARTER = SCRIPT.parents[1] / "assets" / "starter"
SPEC = importlib.util.spec_from_file_location("initialize_harness", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def git_repo(tmp_path: Path) -> Path:
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=tmp_path,
        check=True,
        text=True,
        capture_output=True,
    )
    return tmp_path


def test_plan_reports_new_files(tmp_path: Path) -> None:
    root = git_repo(tmp_path)
    plan = MODULE.build_plan(root)
    assert plan
    assert {entry.status for entry in plan} == {"create"}
    assert ".harness/config.json" in {entry.path for entry in plan}


def test_starter_tracks_no_generated_python_cache() -> None:
    repository_root = Path(__file__).parents[1]
    tracked = subprocess.run(
        ["git", "ls-files", str(STARTER.relative_to(repository_root))],
        cwd=repository_root,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.splitlines()
    assert not [
        path
        for path in tracked
        if "__pycache__" in Path(path).parts or path.endswith(".pyc")
    ]


def test_development_credentials_example_matches_schema() -> None:
    example = json.loads(
        (STARTER / ".harness/dev-credentials.example.json").read_text()
    )
    schema = json.loads(
        (STARTER / ".harness/schema/dev-credentials.schema.json").read_text()
    )
    Draft202012Validator(schema).validate(example)
    assert example["environment"] == "development"
    assert example["accounts"] == []
    invalid_account = {
        "schema_version": 1,
        "environment": "development",
        "accounts": [
            {
                "label": "admin",
                "credentials": {"password": "development-only"},
            }
        ],
    }
    assert list(Draft202012Validator(schema).iter_errors(invalid_account))


def test_plugin_python_sources_compile_without_writing_bytecode() -> None:
    plugin_root = SCRIPT.parents[1]
    for source in plugin_root.rglob("*.py"):
        compile(source.read_text(encoding="utf-8"), str(source), "exec")


def test_release_versions_are_synchronized() -> None:
    repository_root = Path(__file__).parents[1]
    plugin_root = SCRIPT.parents[1]
    manifest_version = json.loads(
        (plugin_root / ".codex-plugin/plugin.json").read_text()
    )["version"]
    qwen_version = json.loads(
        (plugin_root / "qwen-extension.json").read_text()
    )["version"]
    project_version = tomllib.loads(
        (repository_root / "pyproject.toml").read_text()
    )["project"]["version"]
    assert {manifest_version, qwen_version, project_version} == {"0.0.8"}


def test_install_copies_starter_and_records_metadata(tmp_path: Path) -> None:
    root = git_repo(tmp_path)
    result = MODULE.install(root, MODULE.build_plan(root), preserve_conflicts=False)
    assert (root / ".harness/config.json").is_file()
    assert (root / "scripts/harness/validate_state.py").is_file()
    metadata = json.loads((root / ".harness/plugin-install.json").read_text())
    assert metadata["plugin"] == "webapp-harness"
    assert metadata["plugin_version"]
    assert ".harness/config.json" in metadata["managed_files"]
    credentials = root / ".harness/dev-credentials.local.json"
    assert credentials.is_file()
    assert credentials.stat().st_mode & 0o777 == 0o600
    assert json.loads(credentials.read_text())["accounts"] == []
    assert "/.harness/dev-credentials.local.json" in (
        root / ".gitignore"
    ).read_text().splitlines()
    ignored = subprocess.run(
        ["git", "check-ignore", "--quiet", ".harness/dev-credentials.local.json"],
        cwd=root,
    )
    assert ignored.returncode == 0
    assert ".harness/dev-credentials.local.json" not in metadata["managed_files"]
    assert result["local_setup"]["credentials"]["status"] == "created"
    assert result["preserved_conflicts"] == []


def test_install_aborts_before_copying_on_conflict(tmp_path: Path) -> None:
    root = git_repo(tmp_path)
    conflict = root / ".harness/config.json"
    conflict.parent.mkdir(parents=True)
    conflict.write_text('{"existing": true}\n')

    with pytest.raises(ValueError, match="Conflicting paths"):
        MODULE.install(root, MODULE.build_plan(root), preserve_conflicts=False)

    assert not (root / "scripts/harness/validate_state.py").exists()
    assert conflict.read_text() == '{"existing": true}\n'


def test_preserve_conflicts_never_overwrites_existing_files(tmp_path: Path) -> None:
    root = git_repo(tmp_path)
    conflict = root / ".harness/config.json"
    conflict.parent.mkdir(parents=True)
    conflict.write_text('{"existing": true}\n')

    result = MODULE.install(root, MODULE.build_plan(root), preserve_conflicts=True)

    assert conflict.read_text() == '{"existing": true}\n'
    assert ".harness/config.json" in result["preserved_conflicts"]
    assert (root / "scripts/harness/validate_state.py").is_file()


def test_install_preserves_existing_credentials_and_gitignore_content(
    tmp_path: Path,
) -> None:
    root = git_repo(tmp_path)
    credentials = root / ".harness/dev-credentials.local.json"
    credentials.parent.mkdir(parents=True)
    original = {
        "schema_version": 1,
        "environment": "development",
        "accounts": [
            {
                "label": "admin",
                "sign_in_url": "http://localhost:3000/sign-in",
                "credentials": {
                    "email": "admin@example.test",
                    "password": "local-secret",
                },
            }
        ],
    }
    credentials.write_text(json.dumps(original) + "\n")
    (root / ".gitignore").write_text("dist/\n")

    result = MODULE.install(root, MODULE.build_plan(root), preserve_conflicts=False)

    assert json.loads(credentials.read_text()) == original
    assert credentials.stat().st_mode & 0o777 == 0o600
    assert (root / ".gitignore").read_text().splitlines() == [
        "dist/",
        "/.harness/dev-credentials.local.json",
    ]
    assert result["local_setup"]["credentials"]["status"] == "preserved"


def test_plan_reports_local_credential_and_gitignore_actions(tmp_path: Path) -> None:
    root = git_repo(tmp_path)
    summary = MODULE.summarize(root, MODULE.build_plan(root))

    assert summary["local_setup"]["credentials"] == {
        "path": ".harness/dev-credentials.local.json",
        "status": "create",
        "permissions": "0600",
    }
    assert summary["local_setup"]["gitignore"]["status"] == "create"
