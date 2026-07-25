#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

from common import atomic_write_json, completion_ids, read_json, utc_now
from validate_state import validate


def proposal_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def schema_errors(document: object, schema: dict, label: str) -> list[str]:
    errors = []
    for error in Draft202012Validator(schema).iter_errors(document):
        location = "/".join(map(str, error.absolute_path)) or "<root>"
        errors.append(f"{label}:{location}: {error.message}")
    return errors


def dependency_errors(tasks: list[dict], completed_ids: set[str] | None = None) -> list[str]:
    errors: list[str] = []
    tasks = [task for task in tasks if isinstance(task, dict)]
    ids = [task.get("id") for task in tasks]
    known = set(ids).union(completed_ids or set())
    graph = {
        task["id"]: task.get("dependencies", [])
        for task in tasks
        if isinstance(task.get("id"), str)
    }

    for task in tasks:
        task_id = task.get("id", "<unknown>")
        for dependency in task.get("dependencies", []):
            if dependency not in known:
                errors.append(f"{task_id}: unknown dependency {dependency}")

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
    return errors


def validate_proposal(root: Path, proposal: dict) -> list[str]:
    harness = root / ".harness"
    errors = validate(root)
    if errors:
        return [f"existing harness: {error}" for error in errors]

    proposal_schema = read_json(harness / "schema" / "backlog-proposal.schema.json")
    task_schema = read_json(harness / "schema" / "task.schema.json")
    errors.extend(schema_errors(proposal, proposal_schema, "proposal"))

    proposal_tasks = proposal.get("tasks", [])
    if not isinstance(proposal_tasks, list):
        return errors

    for index, task in enumerate(proposal_tasks):
        errors.extend(schema_errors(task, task_schema, f"proposal:tasks/{index}"))
        if not isinstance(task, dict):
            continue
        task_id = task.get("id", f"tasks/{index}")
        if task.get("status") != "proposed":
            errors.append(f"{task_id}: generated tasks must have status proposed")
        if not task.get("gap_evidence"):
            errors.append(f"{task_id}: generated tasks require gap_evidence")
        if not task.get("scope", {}).get("allowed_paths"):
            errors.append(f"{task_id}: generated tasks require allowed_paths")

        verification = task.get("verification", {})
        criterion_kinds = {
            kind
            for criterion in task.get("acceptance_criteria", [])
            for kind in criterion.get("verification", [])
        }
        if criterion_kinds.intersection({"browser", "visual"}) and not verification.get(
            "requires_browser"
        ):
            errors.append(
                f"{task_id}: browser or visual criteria require requires_browser=true"
            )
        if "e2e" in criterion_kinds and not verification.get("requires_e2e"):
            errors.append(f"{task_id}: e2e criteria require requires_e2e=true")

    backlog = read_json(harness / "backlog.json")
    completion_index = read_json(harness / "completed-tasks.json")
    existing_tasks = backlog.get("tasks", [])
    existing_ids = {task.get("id") for task in existing_tasks}.union(completion_ids(completion_index))
    proposal_ids = [
        task.get("id") for task in proposal_tasks if isinstance(task, dict)
    ]
    duplicates = sorted(
        task_id
        for task_id in set(proposal_ids)
        if isinstance(task_id, str)
        and (proposal_ids.count(task_id) > 1 or task_id in existing_ids)
    )
    if duplicates:
        errors.append("proposal task IDs already exist or repeat: " + ", ".join(duplicates))

    config = read_json(harness / "config.json")
    known_profiles = set(config.get("verification_profiles", {}))
    for task in proposal_tasks:
        if not isinstance(task, dict):
            continue
        profiles = task.get("verification", {}).get("profiles", [])
        if not profiles:
            errors.append(
                f"{task.get('id', '<unknown>')}: generated tasks require at least "
                "one verification profile"
            )
        unknown_profiles = sorted(set(profiles) - known_profiles)
        if unknown_profiles:
            errors.append(
                f"{task.get('id', '<unknown>')}: unknown verification profiles: "
                + ", ".join(unknown_profiles)
            )

    errors.extend(dependency_errors(existing_tasks + proposal_tasks, completion_ids(completion_index)))
    return errors


def preview(root: Path, proposal_path: Path) -> dict:
    proposal = read_json(proposal_path)
    if not isinstance(proposal, dict):
        raise ValueError("Proposal root must be an object")
    errors = validate_proposal(root, proposal)
    if errors:
        raise ValueError("Invalid backlog proposal:\n" + "\n".join(errors))
    tasks = proposal["tasks"]
    return {
        "mode": "plan",
        "proposal_sha256": proposal_sha256(proposal_path),
        "backlog_path": ".harness/backlog.json",
        "task_count": len(tasks),
        "tasks": [
            {
                "id": task["id"],
                "title": task["title"],
                "priority": task["priority"],
                "dependencies": task["dependencies"],
                "evidence_count": len(task["gap_evidence"]),
            }
            for task in tasks
        ],
    }


def apply(
    root: Path, proposal_path: Path, expected_sha256: str, confirmed: bool
) -> dict:
    if not confirmed:
        raise ValueError("--apply requires --confirmed after explicit user approval")
    actual_sha256 = proposal_sha256(proposal_path)
    if actual_sha256 != expected_sha256:
        raise ValueError(
            "Proposal changed after preview; run --plan again and request new confirmation"
        )

    plan = preview(root, proposal_path)
    if plan["proposal_sha256"] != expected_sha256:
        raise ValueError(
            "Proposal changed after preview; run --plan again and request new confirmation"
        )
    proposal = read_json(proposal_path)
    if proposal_sha256(proposal_path) != expected_sha256:
        raise ValueError(
            "Proposal changed after preview; run --plan again and request new confirmation"
        )
    backlog_path = root / ".harness" / "backlog.json"
    backlog = read_json(backlog_path)
    timestamp = utc_now()
    appended = []
    for source_task in proposal["tasks"]:
        task = copy.deepcopy(source_task)
        task["updated_at"] = timestamp
        backlog["tasks"].append(task)
        appended.append(task["id"])
    atomic_write_json(backlog_path, backlog)
    return {
        **plan,
        "mode": "apply",
        "applied": True,
        "appended_task_ids": appended,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate or append a user-confirmed backlog proposal."
    )
    parser.add_argument("--root", default=".")
    parser.add_argument("--proposal", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--confirmed", action="store_true")
    parser.add_argument("--expected-sha256")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.plan and (args.confirmed or args.expected_sha256):
        print("ERROR: confirmation arguments are only valid with --apply", file=sys.stderr)
        return 2
    if args.apply and not args.expected_sha256:
        print("ERROR: --apply requires --expected-sha256", file=sys.stderr)
        return 2
    try:
        root = Path(args.root).resolve()
        proposal_path = Path(args.proposal).resolve()
        result = (
            apply(root, proposal_path, args.expected_sha256, args.confirmed)
            if args.apply
            else preview(root, proposal_path)
        )
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
