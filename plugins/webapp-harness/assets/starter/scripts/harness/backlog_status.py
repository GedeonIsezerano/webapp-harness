#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from common import read_json, task_map, priority_sort_key
from validate_state import validate


def backlog_status(root: Path) -> dict:
    errors = validate(root)
    if errors:
        raise ValueError("Harness state invalid:\n" + "\n".join(errors))

    harness = root / ".harness"
    backlog = read_json(harness / "backlog.json")
    state = read_json(harness / "state.json")
    tasks = task_map(backlog)
    counts = Counter(task["status"] for task in tasks.values())
    active_task_id = state.get("active_task_id")
    eligible = sorted(
        (
            task
            for task in tasks.values()
            if task["status"] == "ready"
            and all(tasks[dependency]["status"] == "completed" for dependency in task.get("dependencies", []))
        ),
        key=priority_sort_key,
    )
    dependency_stalled = sorted(
        task["id"]
        for task in tasks.values()
        if task["status"] == "ready" and task not in eligible
    )
    proposed = sorted(
        task["id"] for task in tasks.values() if task["status"] == "proposed"
    )
    blocked = sorted(
        task["id"] for task in tasks.values() if task["status"] == "blocked"
    )
    complete = bool(tasks) and counts["completed"] == len(tasks)

    if active_task_id:
        next_action = "resume_active"
    elif eligible:
        next_action = "select_next"
    elif complete:
        next_action = "complete"
    elif not tasks:
        next_action = "empty"
    elif proposed and not blocked and not dependency_stalled:
        next_action = "awaiting_approval"
    else:
        next_action = "stalled"

    return {
        "schema_version": 1,
        "complete": complete,
        "next_action": next_action,
        "task_count": len(tasks),
        "status_counts": dict(sorted(counts.items())),
        "active_task_id": active_task_id,
        "eligible_task_ids": [task["id"] for task in eligible],
        "unresolved": {
            "proposed": proposed,
            "blocked": blocked,
            "dependency_stalled": dependency_stalled,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Report deterministic backlog progress and the next action."
    )
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    try:
        print(json.dumps(backlog_status(Path(args.root)), indent=2))
        return 0
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
