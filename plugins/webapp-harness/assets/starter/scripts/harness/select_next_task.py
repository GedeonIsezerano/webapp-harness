#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from common import (
    atomic_write_json,
    completion_ids,
    priority_sort_key,
    read_json,
    task_map,
    utc_now,
)
from prepare_browser_plan import prepare
from update_task_state import transition
from validate_state import validate


def git_head(root: Path) -> str | None:
    process = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
        capture_output=True,
    )
    return process.stdout.strip() if process.returncode == 0 else None


def previous_run_count(harness: Path, task_id: str) -> int:
    paths = list((harness / "runs").glob("*/run.json"))
    paths.extend((harness / "archive" / "runs").glob("*/run.json"))
    return sum(read_json(path).get("task_id") == task_id for path in paths)


def select(root: Path, task_id: str | None = None) -> dict:
    errors = validate(root)
    if errors:
        raise ValueError("Harness state invalid:\n" + "\n".join(errors))
    harness = root / ".harness"
    backlog = read_json(harness / "backlog.json")
    completion_index = read_json(harness / "completed-tasks.json")
    state = read_json(harness / "state.json")
    if state.get("active_task_id") or state.get("active_run_id"):
        raise ValueError("An active or uncommitted run already exists")

    tasks = task_map(backlog)
    completed = completion_ids(completion_index).union(
        task["id"] for task in tasks.values() if task["status"] == "completed"
    )
    eligible = [
        task
        for task in tasks.values()
        if task["status"] == "ready"
        and all(dependency in completed for dependency in task.get("dependencies", []))
    ]
    if not eligible:
        raise ValueError("No eligible ready task")
    if task_id:
        if task_id not in tasks:
            raise ValueError(f"Unknown task: {task_id}")
        chosen = tasks[task_id]
        if chosen not in eligible:
            raise ValueError(f"Task is not eligible and ready: {task_id}")
    else:
        chosen = sorted(eligible, key=priority_sort_key)[0]

    attempt = previous_run_count(harness, chosen["id"]) + 1
    run_id = (
        f"{chosen['id']}-{utc_now().replace(':', '').replace('-', '')}"
        f"-a{attempt}"
    )
    run_dir = harness / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    run = {
        "schema_version": 2,
        "run_id": run_id,
        "task_id": chosen["id"],
        "attempt": attempt,
        "status": "implementing",
        "started_at": utc_now(),
        "base_commit": git_head(root),
        "event_counter": 0,
        "transitions": [],
        "results": {
            "implementation": [],
            "verification": [],
            "review": [],
            "browser_validation": [],
        },
        "stop_reason": None,
    }
    atomic_write_json(run_dir / "run.json", run)
    state["active_run_id"] = run_id
    state["pending_commit_task_id"] = None
    atomic_write_json(harness / "state.json", state)
    transition(root, chosen["id"], "implementing", "task_selected")

    active_task = task_map(read_json(harness / "backlog.json"))[chosen["id"]]
    atomic_write_json(
        harness / "current-task.json",
        {
            "schema_version": 2,
            "task": active_task,
            "run_id": run_id,
            "generated_at": utc_now(),
        },
    )
    browser_plan = prepare(root) if active_task["verification"]["requires_browser"] else None
    return {
        "task_id": chosen["id"],
        "run_id": run_id,
        "title": chosen["title"],
        "attempt": run["attempt"],
        "browser_plan": str(browser_plan.relative_to(root)) if browser_plan else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--task-id")
    args = parser.parse_args()
    try:
        print(json.dumps(select(Path(args.root), args.task_id), indent=2))
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
