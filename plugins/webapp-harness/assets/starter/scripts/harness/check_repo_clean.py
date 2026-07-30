#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def git(root: Path, *args: str) -> str:
    process = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
    )
    if process.returncode:
        raise ValueError(process.stderr.strip() or "git command failed")
    return process.stdout


def check(root: Path) -> None:
    git(root, "rev-parse", "--is-inside-work-tree")
    git_dir = Path(git(root, "rev-parse", "--git-dir").strip())
    git_dir = git_dir if git_dir.is_absolute() else root / git_dir
    for marker in [
        "MERGE_HEAD",
        "CHERRY_PICK_HEAD",
        "REVERT_HEAD",
        "rebase-merge",
        "rebase-apply",
    ]:
        if (git_dir / marker).exists():
            raise ValueError(f"Git operation in progress: {marker}")
    status = git(root, "status", "--porcelain=v1").splitlines()
    if status:
        raise ValueError(
            "Lifecycle boundaries require a clean worktree:\n" + "\n".join(status)
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--before-task", action="store_true")
    mode.add_argument("--before-next-task", action="store_true")
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    try:
        check(Path(args.root))
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
    print("Repository worktree is clean.")


if __name__ == "__main__":
    main()
