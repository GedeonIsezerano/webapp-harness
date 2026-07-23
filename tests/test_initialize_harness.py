from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


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


def test_starter_contains_no_generated_python_cache() -> None:
    assert not list(STARTER.rglob("__pycache__"))
    assert not list(STARTER.rglob("*.pyc"))


def test_plugin_python_sources_compile_without_writing_bytecode() -> None:
    plugin_root = SCRIPT.parents[1]
    for source in plugin_root.rglob("*.py"):
        compile(source.read_text(encoding="utf-8"), str(source), "exec")


def test_install_copies_starter_and_records_metadata(tmp_path: Path) -> None:
    root = git_repo(tmp_path)
    result = MODULE.install(root, MODULE.build_plan(root), preserve_conflicts=False)
    assert (root / ".harness/config.json").is_file()
    assert (root / "scripts/harness/validate_state.py").is_file()
    metadata = json.loads((root / ".harness/plugin-install.json").read_text())
    assert metadata["plugin"] == "webapp-harness"
    assert metadata["plugin_version"]
    assert ".harness/config.json" in metadata["managed_files"]
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
