#!/usr/bin/env python3
"""Move committed completed tasks out of the live backlog without losing evidence."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from common import atomic_write_json, completion_ids, read_json
from validate_state import validate


ARCHIVE_RELATIVE_PATH = Path("archive") / "completed-tasks.jsonl"


def read_archive_records(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    records: dict[str, dict] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            task_id = record["completion"]["task_id"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ValueError(f"Invalid completion archive at line {line_number}") from exc
        if not isinstance(task_id, str):
            raise ValueError(f"Invalid completion archive task ID at line {line_number}")
        if task_id in records:
            raise ValueError(f"Duplicate completion archive task ID: {task_id}")
        records[task_id] = record
    return records


def completion_for_task(harness: Path, task_id: str) -> dict:
    matches: list[tuple[str, dict]] = []
    for run_path in sorted((harness / "runs").glob("*/run.json")):
        run = read_json(run_path)
        if run.get("task_id") != task_id or run.get("status") != "completed":
            continue
        commit = run.get("result_commit")
        completed_at = run.get("completed_at")
        if isinstance(commit, str) and commit and isinstance(completed_at, str) and completed_at:
            matches.append((run_path.parent.name, {"task_id": task_id, "commit": commit, "completed_at": completed_at}))
    if not matches:
        raise ValueError(
            f"Cannot archive {task_id}: no completed run with a result commit and completion time"
        )
    if len(matches) > 1:
        raise ValueError(f"Cannot archive {task_id}: multiple completed run records found")
    return matches[0][1]


def append_records(path: Path, records: list[dict]) -> None:
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(record, sort_keys=True) + "\n" for record in records)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


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
    completed_tasks = [task for task in backlog["tasks"] if task["status"] == "completed"]
    if not completed_tasks:
        return {
            "mode": "dry-run" if dry_run else "apply",
            "archived_task_ids": [],
            "archive_path": str(ARCHIVE_RELATIVE_PATH),
            "completion_index_path": ".harness/completed-tasks.json",
        }

    existing_index_ids = completion_ids(index)
    archive_records = read_archive_records(archive_path)
    new_records: list[dict] = []
    index_entries: list[dict] = []
    for task in completed_tasks:
        task_id = task["id"]
        if task_id in existing_index_ids:
            raise ValueError(f"Cannot archive {task_id}: it already exists in the completion index")
        completion = completion_for_task(harness, task_id)
        archived = archive_records.get(task_id)
        if archived:
            if archived.get("task") != task or archived.get("completion") != completion:
                raise ValueError(f"Cannot archive {task_id}: existing archive record differs")
        else:
            new_records.append({"schema_version": 1, "task": task, "completion": completion})
        index_entries.append(completion)

    result = {
        "mode": "dry-run" if dry_run else "apply",
        "archived_task_ids": [entry["task_id"] for entry in index_entries],
        "archive_path": str(ARCHIVE_RELATIVE_PATH),
        "completion_index_path": ".harness/completed-tasks.json",
    }
    if dry_run:
        return result

    append_records(archive_path, new_records)
    backlog["tasks"] = [task for task in backlog["tasks"] if task["status"] != "completed"]
    index["completed_tasks"].extend(index_entries)
    atomic_write_json(backlog_path, backlog)
    atomic_write_json(index_path, index)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Archive committed completed tasks and retain a compact dependency index."
    )
    parser.add_argument("--root", default=".")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(archive_completed(Path(args.root), args.dry_run), indent=2))
        return 0
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
