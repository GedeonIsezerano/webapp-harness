#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from common import atomic_write_json, read_json, utc_now


def collect(root: Path) -> Path:
    harness = root / ".harness"
    state = read_json(harness / "state.json")
    run_id = state.get("active_run_id")
    if not run_id:
        raise ValueError("No active run")
    run_path = harness / "runs" / run_id / "run.json"
    run = read_json(run_path)
    if run.get("status") != "reviewing":
        raise ValueError("Diff collection can only run during reviewing")
    base = run.get("base_commit") or "HEAD"
    diff = subprocess.run(
        [
            "git",
            "diff",
            "--find-renames",
            base,
            "--",
            ".",
            ":(exclude).harness",
        ],
        cwd=root,
        text=True,
        capture_output=True,
    )
    if diff.returncode:
        raise ValueError(diff.stderr.strip())
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=root,
        text=True,
        capture_output=True,
    )
    if untracked.returncode:
        raise ValueError(untracked.stderr.strip())
    output = harness / "runs" / run_id / "task.diff"
    output.write_text(
        diff.stdout
        + "\n# Untracked files\n"
        + "\n".join(
            path
            for path in untracked.stdout.splitlines()
            if not path.startswith(".harness/")
        )
        + "\n",
        encoding="utf-8",
    )
    run["diff_snapshot"] = {
        "path": str(output.relative_to(root)),
        "collected_at": utc_now(),
        "after_event_sequence": run.get("event_counter", 0),
    }
    atomic_write_json(run_path, run)
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    try:
        print(collect(Path(args.root)))
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
