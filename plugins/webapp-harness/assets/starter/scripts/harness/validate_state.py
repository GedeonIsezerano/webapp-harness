#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

from common import active_tasks, completion_ids, read_json


REQUIRED = ["config.json", "backlog.json", "completed-tasks.json", "state.json"]
SCHEMAS = {
    "config.json": "config.schema.json",
    "backlog.json": "backlog.schema.json",
    "completed-tasks.json": "completion-index.schema.json",
    "state.json": "state.schema.json",
}


def document_errors(document: object, schema: dict, label: str) -> list[str]:
    errors = []
    for error in Draft202012Validator(schema).iter_errors(document):
        location = "/".join(map(str, error.absolute_path)) or "<root>"
        errors.append(f"{label}:{location}: {error.message}")
    return errors


def validate(root: Path) -> list[str]:
    harness = root / ".harness"
    errors: list[str] = []
    documents = {}
    for name in REQUIRED:
        try:
            documents[name] = read_json(harness / name)
        except ValueError as error:
            errors.append(str(error))
    if errors:
        return errors

    for name, schema_name in SCHEMAS.items():
        try:
            errors.extend(
                document_errors(
                    documents[name],
                    read_json(harness / "schema" / schema_name),
                    name,
                )
            )
        except ValueError as error:
            errors.append(str(error))

    backlog = documents["backlog.json"]
    completion_index = documents["completed-tasks.json"]
    state = documents["state.json"]
    tasks = backlog.get("tasks", [])
    try:
        task_schema = read_json(harness / "schema" / "task.schema.json")
        for index, task in enumerate(tasks):
            errors.extend(
                document_errors(task, task_schema, f"backlog.json:tasks/{index}")
            )
    except ValueError as error:
        errors.append(str(error))

    ids = [task.get("id") for task in tasks]
    if len(ids) != len(set(ids)):
        errors.append("backlog.json: task IDs must be unique")
    completed_ids = completion_ids(completion_index)
    if len(completed_ids) != len(completion_index.get("completed_tasks", [])):
        errors.append("completed-tasks.json: task IDs must be unique")
    overlap = sorted(set(ids).intersection(completed_ids))
    if overlap:
        errors.append(
            "backlog.json and completed-tasks.json repeat task IDs: "
            + ", ".join(overlap)
        )

    known = set(ids).union(completed_ids)
    for task in tasks:
        for dependency in task.get("dependencies", []):
            if dependency not in known:
                errors.append(f"{task.get('id')}: unknown dependency {dependency}")
        if task.get("status") == "ready" and not task.get("acceptance_criteria"):
            errors.append(f"{task.get('id')}: ready task has no acceptance criteria")
        kinds = {
            kind
            for criterion in task.get("acceptance_criteria", [])
            for kind in criterion.get("verification", [])
        }
        if task.get("verification", {}).get("requires_browser") and not kinds.intersection(
            {"browser", "visual", "e2e"}
        ):
            errors.append(
                f"{task.get('id')}: requires_browser needs a browser, visual, "
                "or e2e acceptance criterion"
            )

    graph = {
        task["id"]: task.get("dependencies", [])
        for task in tasks
        if "id" in task
    }
    visiting: set[str] = set()
    visited: set[str] = set()

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

    active = active_tasks(backlog)
    if len(active) > 1:
        errors.append("more than one active task")
    active_id = state.get("active_task_id")
    expected_active_id = active[0]["id"] if active else None
    if active_id != expected_active_id:
        errors.append("state.active_task_id disagrees with backlog")

    run_id = state.get("active_run_id")
    pending_task_id = state.get("pending_commit_task_id")
    if bool(run_id) != bool(active_id or pending_task_id):
        errors.append(
            "state.active_run_id must accompany an active or pending-commit task"
        )
    if pending_task_id:
        pending = next(
            (task for task in tasks if task.get("id") == pending_task_id),
            None,
        )
        if not pending or pending.get("status") != "completed":
            errors.append("state.pending_commit_task_id is not a completed live task")
        if active_id:
            errors.append("pending commit and active task cannot coexist")

    if run_id:
        try:
            run = read_json(harness / "runs" / run_id / "run.json")
            errors.extend(
                document_errors(
                    run,
                    read_json(harness / "schema" / "run.schema.json"),
                    f"runs/{run_id}/run.json",
                )
            )
        except ValueError:
            errors.append("active run record is missing or invalid")
        else:
            run_task_id = run.get("task_id")
            live_task = next(
                (task for task in tasks if task.get("id") == run_task_id),
                None,
            )
            if not live_task:
                errors.append("active run references an unknown live task")
            elif run.get("status") != live_task.get("status"):
                errors.append("active run status disagrees with backlog")
            if active_id and run_task_id != active_id:
                errors.append("active run disagrees with state.active_task_id")
            if pending_task_id and run_task_id != pending_task_id:
                errors.append("active run disagrees with pending commit task")
            result_entries = [
                entry
                for entries in run.get("results", {}).values()
                if isinstance(entries, list)
                for entry in entries
                if isinstance(entry, dict)
            ]
            sequences = sorted(
                entry.get("sequence")
                for entry in result_entries
                if isinstance(entry.get("sequence"), int)
            )
            if sequences != list(range(1, len(result_entries) + 1)):
                errors.append("active run result sequences must be unique and contiguous")
            if run.get("event_counter") != len(result_entries):
                errors.append("active run event_counter disagrees with result history")
        try:
            current = read_json(harness / "current-task.json")
        except ValueError:
            errors.append("current task document is missing or invalid")
        else:
            current_task = current.get("task", {})
            expected_task_id = active_id or pending_task_id
            if current.get("run_id") != run_id:
                errors.append("current task run ID disagrees with state")
            if current_task.get("id") != expected_task_id:
                errors.append("current task ID disagrees with state")
    elif (harness / "current-task.json").exists():
        errors.append("current task document exists without an active run")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    errors = validate(Path(args.root))
    if args.json:
        print(json.dumps({"valid": not errors, "errors": errors}, indent=2))
    elif errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
    else:
        print("Harness state is valid.")
    raise SystemExit(1 if errors else 0)


if __name__ == "__main__":
    main()
