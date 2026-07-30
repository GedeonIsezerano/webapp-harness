#!/usr/bin/env python3
"""Plan or apply the lossless v0.0.10 state and run compaction."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from common import (
    append_jsonl,
    atomic_write_json,
    completion_ids,
    latest_result,
    read_json,
    utc_now,
)


LEGACY_RESULTS = {
    "implementation": ("implementation", "implementation-result.json"),
    "verification": ("verification", "verification.json"),
    "browser_validation": ("browser_validation", "browser-result.json"),
    "review": ("review", "review.json"),
}


def all_run_paths(harness: Path) -> list[Path]:
    paths = list((harness / "runs").glob("*/run.json"))
    paths.extend((harness / "archive" / "runs").glob("*/run.json"))
    return sorted(paths)


def migration_plan(root: Path) -> dict:
    harness = root / ".harness"
    state = read_json(harness / "state.json")
    config = read_json(harness / "config.json")
    backlog = read_json(harness / "backlog.json")
    completed = completion_ids(read_json(harness / "completed-tasks.json"))
    runs = []
    redundant = []
    cold_store = []
    retained = []
    for run_path in all_run_paths(harness):
        run = read_json(run_path)
        if run.get("schema_version") != 2:
            runs.append(str(run_path.relative_to(root)))
        for kind, (legacy_key, filename) in LEGACY_RESULTS.items():
            candidate = run_path.parent / filename
            embedded = run.get(legacy_key) or latest_result(run, kind)
            if candidate.is_file() and embedded and read_json(candidate) == embedded:
                redundant.append(str(candidate.relative_to(root)))
        if (
            run_path.parent.parent == harness / "runs"
            and run.get("task_id") in completed
        ):
            cold_store.append(str(run_path.parent.relative_to(root)))
        elif run_path.parent.parent == harness / "runs":
            retained.append(str(run_path.parent.relative_to(root)))
    return {
        "clean_lifecycle_boundary": not bool(
            state.get("active_task_id") or state.get("active_run_id")
        ),
        "state_migration_required": state.get("schema_version") != 2,
        "run_records_to_migrate": runs,
        "redundant_result_files": redundant,
        "completed_run_directories_to_cold_store": cold_store,
        "unresolved_run_directories_retained": retained,
        "unused_plugin_metadata": (
            [".harness/plugin-install.json"]
            if (harness / "plugin-install.json").is_file()
            else []
        ),
        "deprecated_config_fields_to_remove": [
            field
            for field, present in (
                ("repository", "repository" in config),
                (
                    "commit.required",
                    "required" in config.get("commit", {}),
                ),
            )
            if present
        ],
        "deprecated_task_requires_e2e_to_remove": sum(
            "requires_e2e" in task.get("verification", {})
            for task in backlog.get("tasks", [])
        ),
        "transition_count_to_cold_store": len(state.get("transition_history", [])),
    }


def migrate_run(run_path: Path) -> None:
    run = read_json(run_path)
    if run.get("schema_version") == 2:
        return
    candidates = []
    for rank, (kind, (legacy_key, filename)) in enumerate(LEGACY_RESULTS.items()):
        result = run.get(legacy_key)
        if not isinstance(result, dict) or not result:
            continue
        evidence_path = run_path.parent / filename
        timestamp = (
            evidence_path.stat().st_mtime
            if evidence_path.exists()
            else run_path.stat().st_mtime
        )
        candidates.append((timestamp, rank, kind, result))
    results = {kind: [] for kind in LEGACY_RESULTS}
    for sequence, (_, _, kind, result) in enumerate(sorted(candidates), 1):
        results[kind].append(
            {
                "sequence": sequence,
                "recorded_at": run.get("started_at", utc_now()),
                "result": result,
            }
        )
    for legacy_key, _ in LEGACY_RESULTS.values():
        run.pop(legacy_key, None)
    run["schema_version"] = 2
    run["event_counter"] = len(candidates)
    run["results"] = results
    run.setdefault("attempt", 1)
    run.setdefault("base_commit", None)
    run.setdefault("transitions", [])
    run.setdefault("result_commit", None)
    run.setdefault("stop_reason", None)
    atomic_write_json(run_path, run)


def migrate_state(harness: Path) -> None:
    path = harness / "state.json"
    state = read_json(path)
    if state.get("schema_version") == 2:
        return
    transition_path = harness / "archive" / "transitions.jsonl"
    existing = set()
    if transition_path.is_file():
        existing = {
            json.dumps(json.loads(line), sort_keys=True)
            for line in transition_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
    for transition in state.get("transition_history", []):
        fingerprint = json.dumps(transition, sort_keys=True)
        if fingerprint not in existing:
            append_jsonl(transition_path, transition)
            existing.add(fingerprint)
    active_run_id = state.get("active_run_id")
    active_task_id = state.get("active_task_id")
    pending_task_id = None
    if active_run_id and not active_task_id:
        run_path = harness / "runs" / active_run_id / "run.json"
        if run_path.is_file() and read_json(run_path).get("status") == "completed":
            pending_task_id = state.get("last_completed_task_id")
        else:
            active_run_id = None
    atomic_write_json(
        path,
        {
            "schema_version": 2,
            "active_task_id": active_task_id,
            "active_run_id": active_run_id,
            "pending_commit_task_id": pending_task_id,
        },
    )
    if not active_run_id:
        (harness / "current-task.json").unlink(missing_ok=True)


def remove_deprecated_fields(harness: Path) -> None:
    config_path = harness / "config.json"
    config = read_json(config_path)
    config.pop("repository", None)
    config.get("commit", {}).pop("required", None)
    atomic_write_json(config_path, config)

    backlog_path = harness / "backlog.json"
    backlog = read_json(backlog_path)
    for task in backlog.get("tasks", []):
        task.get("verification", {}).pop("requires_e2e", None)
    atomic_write_json(backlog_path, backlog)


def apply_migration(root: Path, confirmed: bool) -> dict:
    if not confirmed:
        raise ValueError("--apply requires --confirmed")
    plan = migration_plan(root)
    if not plan["clean_lifecycle_boundary"]:
        raise ValueError(
            "Migration requires no active or pending run; finish or block it first"
        )
    harness = root / ".harness"
    archive_runs = harness / "archive" / "runs"
    for relative in plan["completed_run_directories_to_cold_store"]:
        destination = archive_runs / (root / relative).name
        if destination.exists():
            raise ValueError(
                f"Cold-store destination already exists: {destination.relative_to(root)}"
            )
    for relative in plan["run_records_to_migrate"]:
        migrate_run(root / relative)
    migrate_state(harness)
    remove_deprecated_fields(harness)
    for relative in plan["redundant_result_files"]:
        (root / relative).unlink()
    for relative in plan["unused_plugin_metadata"]:
        (root / relative).unlink()
    archive_runs.mkdir(parents=True, exist_ok=True)
    for relative in plan["completed_run_directories_to_cold_store"]:
        source = root / relative
        destination = archive_runs / source.name
        shutil.move(str(source), str(destination))
    return {**plan, "applied": True}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--confirmed", action="store_true")
    args = parser.parse_args()
    try:
        root = Path(args.root).resolve()
        result = (
            apply_migration(root, args.confirmed)
            if args.apply
            else migration_plan(root)
        )
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
