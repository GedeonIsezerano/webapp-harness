#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_ROOT = PLUGIN_ROOT / "assets" / "starter"
MANIFEST_PATH = PLUGIN_ROOT / ".codex-plugin" / "plugin.json"
CREDENTIALS_EXAMPLE_PATH = Path(".harness/dev-credentials.example.json")
CREDENTIALS_LOCAL_PATH = Path(".harness/dev-credentials.local.json")
CREDENTIALS_GITIGNORE_ENTRY = "/.harness/dev-credentials.local.json"


@dataclass(frozen=True)
class FilePlan:
    path: str
    status: str
    source_sha256: str
    target_sha256: str | None = None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_root(start: Path) -> Path:
    proc = subprocess.run(
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
    )
    if proc.returncode:
        raise ValueError(proc.stderr.strip() or f"{start} is not a Git worktree")
    return Path(proc.stdout.strip()).resolve()


def template_files() -> list[Path]:
    if not TEMPLATE_ROOT.is_dir():
        raise ValueError(f"Missing plugin starter assets: {TEMPLATE_ROOT}")
    files = sorted(
        path
        for path in TEMPLATE_ROOT.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix != ".pyc"
    )
    if not files:
        raise ValueError(f"Plugin starter is empty: {TEMPLATE_ROOT}")
    for path in files:
        if path.is_symlink():
            raise ValueError(f"Starter assets must not contain symlinks: {path}")
    return files


def build_plan(root: Path) -> list[FilePlan]:
    plan: list[FilePlan] = []
    for source in template_files():
        relative = source.relative_to(TEMPLATE_ROOT)
        target = root / relative
        source_hash = sha256(source)
        if not target.exists():
            status = "create"
            target_hash = None
        elif not target.is_file():
            status = "conflict"
            target_hash = None
        else:
            target_hash = sha256(target)
            status = "identical" if target_hash == source_hash else "conflict"
        plan.append(
            FilePlan(
                path=relative.as_posix(),
                status=status,
                source_sha256=source_hash,
                target_sha256=target_hash,
            )
        )
    return plan


def plugin_version() -> str:
    try:
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["version"]
    except (FileNotFoundError, json.JSONDecodeError, KeyError) as exc:
        raise ValueError(f"Invalid plugin manifest: {MANIFEST_PATH}") from exc


def local_setup_plan(root: Path) -> dict[str, object]:
    credentials = root / CREDENTIALS_LOCAL_PATH
    gitignore = root / ".gitignore"
    gitignore_lines = (
        gitignore.read_bytes().splitlines()
        if gitignore.is_file()
        else []
    )
    return {
        "credentials": {
            "path": CREDENTIALS_LOCAL_PATH.as_posix(),
            "status": "preserve" if credentials.exists() else "create",
            "permissions": "0600",
        },
        "gitignore": {
            "path": ".gitignore",
            "entry": CREDENTIALS_GITIGNORE_ENTRY,
            "status": (
                "present"
                if CREDENTIALS_GITIGNORE_ENTRY.encode() in gitignore_lines
                else "append" if gitignore.exists() else "create"
            ),
        },
    }


def ensure_local_credentials(root: Path) -> dict[str, object]:
    example = root / CREDENTIALS_EXAMPLE_PATH
    credentials = root / CREDENTIALS_LOCAL_PATH
    gitignore = root / ".gitignore"

    if credentials.is_symlink():
        raise ValueError(
            f"Refusing to manage symlinked credential file: {credentials}"
        )
    if credentials.exists() and not credentials.is_file():
        raise ValueError(f"Credential path is not a file: {credentials}")
    if gitignore.is_symlink():
        raise ValueError(f"Refusing to manage symlinked ignore file: {gitignore}")
    if gitignore.exists() and not gitignore.is_file():
        raise ValueError(f"Ignore path is not a file: {gitignore}")
    if not example.is_file():
        raise ValueError(f"Missing installed credential example: {example}")

    credential_status = "preserved"
    if not credentials.exists():
        shutil.copy2(example, credentials)
        credential_status = "created"
    os.chmod(credentials, 0o600)

    gitignore_status = "present"
    existing = gitignore.read_bytes() if gitignore.is_file() else b""
    entry = CREDENTIALS_GITIGNORE_ENTRY.encode()
    if entry not in existing.splitlines():
        separator = b"" if not existing or existing.endswith((b"\n", b"\r")) else b"\n"
        with gitignore.open("ab") as handle:
            handle.write(separator + entry + b"\n")
        gitignore_status = "appended" if existing else "created"

    return {
        "credentials": {
            "path": CREDENTIALS_LOCAL_PATH.as_posix(),
            "status": credential_status,
            "permissions": "0600",
        },
        "gitignore": {
            "path": ".gitignore",
            "entry": CREDENTIALS_GITIGNORE_ENTRY,
            "status": gitignore_status,
        },
    }


def install(
    root: Path, plan: list[FilePlan], preserve_conflicts: bool
) -> dict[str, object]:
    conflicts = [entry for entry in plan if entry.status == "conflict"]
    if conflicts and not preserve_conflicts:
        raise ValueError(
            "Conflicting paths require manual review: "
            + ", ".join(entry.path for entry in conflicts)
        )

    created: list[str] = []
    for entry in plan:
        if entry.status != "create":
            continue
        source = TEMPLATE_ROOT / entry.path
        target = root / entry.path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        created.append(entry.path)

    metadata = {
        "schema_version": 1,
        "plugin": "webapp-harness",
        "plugin_version": plugin_version(),
        "installed_at": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "managed_files": [entry.path for entry in plan],
        "preserved_conflicts": [entry.path for entry in conflicts],
    }
    metadata_path = root / ".harness" / "plugin-install.json"
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    local_setup = ensure_local_credentials(root)
    return {
        "created": created,
        "identical": [
            entry.path for entry in plan if entry.status == "identical"
        ],
        "preserved_conflicts": [entry.path for entry in conflicts],
        "metadata": str(metadata_path.relative_to(root)),
        "local_setup": local_setup,
    }


def summarize(root: Path, plan: list[FilePlan]) -> dict[str, object]:
    return {
        "repository_root": str(root),
        "plugin_version": plugin_version(),
        "summary": {
            state: sum(entry.status == state for entry in plan)
            for state in ("create", "identical", "conflict")
        },
        "files": [asdict(entry) for entry in plan],
        "local_setup": local_setup_plan(root),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plan or apply a collision-aware harness installation."
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Path inside the target Git repository (default: current directory).",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true", help="Report without writing.")
    mode.add_argument("--apply", action="store_true", help="Copy starter files.")
    parser.add_argument(
        "--preserve-conflicts",
        action="store_true",
        help="With --apply, leave conflicting target files untouched.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.preserve_conflicts and not args.apply:
        print("ERROR: --preserve-conflicts requires --apply", file=sys.stderr)
        return 2
    try:
        root = git_root(Path(args.root).resolve())
        plan = build_plan(root)
        result = summarize(root, plan)
        if args.apply:
            result["installation"] = install(
                root, plan, preserve_conflicts=args.preserve_conflicts
            )
        print(json.dumps(result, indent=2))
        return 0
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
