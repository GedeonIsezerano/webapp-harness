#!/usr/bin/env python3
"""Replace a non-active task's dependencies with validation and an audit event."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from common import (
    append_jsonl,
    atomic_write_json,
    completion_ids,
    read_json,
    task_map,
    utc_now,
)
from validate_state import validate


def cycle_errors(tasks: dict[str, dict]) -> list[str]:
    graph = {
        task_id: task.get("dependencies", [])
        for task_id, task in tasks.items()
    }
    visiting: set[str] = set()
    visited: set[str] = set()
    errors: list[str] = []

    def visit(task_id: str, trail: list[str]) -> None:
        if task_id in visiting:
            errors.append("dependency cycle: " + " -> ".join(trail + [task_id]))
            return
        if task_id in visited:
            return
        visiting.add(task_id)
        for dependency in graph.get(task_id, []):
            if dependency in graph:
                visit(dependency, trail + [task_id])
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in graph:
        visit(task_id, [])
    return errors


def update_dependencies(
    root: Path,
    task_id: str,
    dependencies: list[str],
    reason: str,
) -> dict:
    errors = validate(root)
    if errors:
        raise ValueError("Harness state invalid:\n" + "\n".join(errors))
    harness = root / ".harness"
    state = read_json(harness / "state.json")
    if state.get("active_task_id"):
        raise ValueError("Dependency edits require a clean lifecycle boundary")
    backlog_path = harness / "backlog.json"
    backlog = read_json(backlog_path)
    tasks = task_map(backlog)
    if task_id not in tasks:
        raise ValueError(f"Unknown task: {task_id}")
    task = tasks[task_id]
    if task["status"] in {
        "implementing",
        "verifying",
        "reviewing",
        "browser_validating",
        "completed",
        "cancelled",
        "superseded",
    }:
        raise ValueError(f"Cannot edit dependencies for {task['status']} task")
    if len(dependencies) != len(set(dependencies)):
        raise ValueError("Dependencies must be unique")
    if task_id in dependencies:
        raise ValueError("Task cannot depend on itself")
    known = set(tasks).union(
        completion_ids(read_json(harness / "completed-tasks.json"))
    )
    unknown = sorted(set(dependencies) - known)
    if unknown:
        raise ValueError("Unknown dependencies: " + ", ".join(unknown))

    before = list(task.get("dependencies", []))
    task["dependencies"] = dependencies
    cycles = cycle_errors(tasks)
    if cycles:
        task["dependencies"] = before
        raise ValueError("\n".join(cycles))
    timestamp = utc_now()
    task["updated_at"] = timestamp
    event = {
        "event": "dependencies_replaced",
        "task_id": task_id,
        "before": before,
        "after": dependencies,
        "reason": reason,
        "timestamp": timestamp,
    }
    atomic_write_json(backlog_path, backlog)
    append_jsonl(harness / "archive" / "task-events.jsonl", event)
    return event


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id")
    parser.add_argument("--set", nargs="*", default=[])
    parser.add_argument("--reason", required=True)
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    try:
        print(
            json.dumps(
                update_dependencies(
                    Path(args.root),
                    args.task_id,
                    args.set,
                    args.reason,
                ),
                indent=2,
            )
        )
        return 0
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
