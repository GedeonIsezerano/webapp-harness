#!/usr/bin/env python3
"""Archive committed tasks and their run directories outside the hot state."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from common import atomic_write_json, completion_ids, latest_result, read_json
from validate_state import validate


ARCHIVE_RELATIVE_PATH = Path("archive") / "completed-tasks.jsonl"
RESULT_FILES = {
    "implementation-result.json": "implementation",
    "verification.json": "verification",
    "review.json": "review",
    "browser-result.json": "browser_validation",
}


def read_archive_records(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    records: dict[str, dict] = {}
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        1,
    ):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            task_id = record["completion"]["task_id"]
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            raise ValueError(
                f"Invalid completion archive at line {line_number}"
            ) from error
        if not isinstance(task_id, str):
            raise ValueError(
                f"Invalid completion archive task ID at line {line_number}"
            )
        if task_id in records:
            raise ValueError(f"Duplicate completion archive task ID: {task_id}")
        records[task_id] = record
    return records


def run_paths(harness: Path) -> list[Path]:
    paths = list((harness / "runs").glob("*/run.json"))
    paths.extend((harness / "archive" / "runs").glob("*/run.json"))
    return sorted(paths)


def git_commit_for_run(root: Path, run_id: str, task_id: str) -> str:
    process = subprocess.run(
        [
            "git",
            "log",
            "--all",
            "--format=%H",
            "--fixed-strings",
            f"--grep=Run: {run_id}",
        ],
        cwd=root,
        text=True,
        capture_output=True,
    )
    if process.returncode:
        raise ValueError(process.stderr.strip() or "Unable to inspect Git history")
    matches = []
    for commit in process.stdout.splitlines():
        body_process = subprocess.run(
            ["git", "show", "-s", "--format=%B", commit],
            cwd=root,
            text=True,
            capture_output=True,
        )
        if body_process.returncode:
            raise ValueError(
                body_process.stderr.strip() or f"Unable to inspect commit {commit}"
            )
        body = body_process.stdout.splitlines()
        if f"Run: {run_id}" in body and f"Task: {task_id}" in body:
            matches.append(commit)
    if len(matches) != 1:
        raise ValueError(
            f"Cannot resolve one task commit for run {run_id}; found {len(matches)}"
        )
    return matches[0]


def completion_for_task(
    root: Path,
    harness: Path,
    task_id: str,
) -> tuple[dict, Path]:
    matches: list[tuple[dict, Path]] = []
    for run_path in run_paths(harness):
        run = read_json(run_path)
        if run.get("task_id") != task_id or run.get("status") != "completed":
            continue
        commit = run.get("result_commit") or git_commit_for_run(
            root,
            run_path.parent.name,
            task_id,
        )
        completed_at = run.get("completed_at")
        if (
            isinstance(commit, str)
            and commit
            and isinstance(completed_at, str)
            and completed_at
        ):
            run_id = run_path.parent.name
            completion = {
                "task_id": task_id,
                "commit": commit,
                "completed_at": completed_at,
                "run_id": run_id,
                "archive_path": f".harness/archive/runs/{run_id}",
            }
            matches.append((completion, run_path.parent))
    if not matches:
        raise ValueError(
            f"Cannot archive {task_id}: no completed run with a result commit "
            "and completion time"
        )
    if len(matches) > 1:
        raise ValueError(f"Cannot archive {task_id}: multiple completed runs found")
    return matches[0]


def append_records(path: Path, records: list[dict]) -> None:
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(
        json.dumps(record, sort_keys=True) + "\n" for record in records
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def redundant_result_files(run_dir: Path) -> list[Path]:
    run = read_json(run_dir / "run.json")
    redundant = []
    for filename, kind in RESULT_FILES.items():
        candidate = run_dir / filename
        if candidate.is_file() and read_json(candidate) == latest_result(run, kind):
            redundant.append(candidate)
    return redundant


def archive_completed(root: Path, dry_run: bool = False) -> dict:
    errors = validate(root)
    if errors:
        raise ValueError("Harness state invalid:\n" + "\n".join(errors))
    harness = root / ".harness"
    backlog_path = harness / "backlog.json"
    index_path = harness / "completed-tasks.json"
    archive_path = harness / ARCHIVE_RELATIVE_PATH
    backlog = read_json(backlog_path)
    index = read_json(index_path)
    completed_tasks = [
        task for task in backlog["tasks"] if task["status"] == "completed"
    ]
    if not completed_tasks:
        return {
            "mode": "dry-run" if dry_run else "apply",
            "archived_task_ids": [],
            "archived_run_ids": [],
            "removed_redundant_result_files": [],
            "archive_path": str(ARCHIVE_RELATIVE_PATH),
        }

    existing_index_ids = completion_ids(index)
    archive_records = read_archive_records(archive_path)
    new_records = []
    index_entries = []
    sources: dict[str, Path] = {}
    redundant: list[Path] = []
    for task in completed_tasks:
        task_id = task["id"]
        if task_id in existing_index_ids:
            raise ValueError(f"Cannot archive {task_id}: already in completion index")
        completion, source = completion_for_task(root, harness, task_id)
        archived = archive_records.get(task_id)
        if archived:
            if archived.get("task") != task or archived.get("completion") != completion:
                raise ValueError(f"Cannot archive {task_id}: archive record differs")
        else:
            new_records.append(
                {"schema_version": 2, "task": task, "completion": completion}
            )
        index_entries.append(completion)
        sources[completion["run_id"]] = source
        redundant.extend(redundant_result_files(source))

    result = {
        "mode": "dry-run" if dry_run else "apply",
        "archived_task_ids": [entry["task_id"] for entry in index_entries],
        "archived_run_ids": [entry["run_id"] for entry in index_entries],
        "removed_redundant_result_files": [
            str(path.relative_to(root)) for path in redundant
        ],
        "archive_path": str(ARCHIVE_RELATIVE_PATH),
    }
    if dry_run:
        return result

    append_records(archive_path, new_records)
    for path in redundant:
        path.unlink()
    archive_runs = harness / "archive" / "runs"
    archive_runs.mkdir(parents=True, exist_ok=True)
    for run_id, source in sources.items():
        destination = archive_runs / run_id
        if source == destination:
            continue
        if destination.exists():
            raise ValueError(f"Archive run destination already exists: {run_id}")
        shutil.move(str(source), str(destination))
    backlog["tasks"] = [
        task for task in backlog["tasks"] if task["status"] != "completed"
    ]
    index["completed_tasks"].extend(index_entries)
    atomic_write_json(backlog_path, backlog)
    atomic_write_json(index_path, index)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Archive committed tasks and cold-store their run evidence."
    )
    parser.add_argument("--root", default=".")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(archive_completed(Path(args.root), args.dry_run), indent=2))
        return 0
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
