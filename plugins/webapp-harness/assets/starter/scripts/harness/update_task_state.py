#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from common import (
    append_jsonl,
    atomic_write_json,
    latest_result,
    latest_result_entry,
    read_json,
    task_map,
    utc_now,
)
from lifecycle import ACTIVE_STATES, RETIRED_STATES, can_transition
from retry_status import retry_advice


def require_passed_after(run: dict, kind: str, earlier_kind: str | None = None) -> None:
    entry = latest_result_entry(run, kind)
    result = latest_result(run, kind)
    passed = (
        result.get("verdict") == "APPROVED"
        if kind == "review"
        else result.get("status") == "PASSED"
    )
    if not entry or not passed:
        raise ValueError(f"Cannot advance without a passed {kind.replace('_', ' ')}")
    if earlier_kind:
        earlier = latest_result_entry(run, earlier_kind)
        if not earlier or entry["sequence"] <= earlier["sequence"]:
            raise ValueError(
                f"{kind.replace('_', ' ').title()} must be newer than "
                f"the latest {earlier_kind.replace('_', ' ')}"
            )

def require_recorded(run: dict, kind: str) -> None:
    if not latest_result_entry(run, kind):
        raise ValueError(
            f"Cannot advance without a recorded {kind.replace('_', ' ')} result"
        )


def transition(root: Path, task_id: str, target: str, reason: str) -> None:
    harness = root / ".harness"
    backlog = read_json(harness / "backlog.json")
    state = read_json(harness / "state.json")
    tasks = task_map(backlog)
    if task_id not in tasks:
        raise ValueError(f"Unknown task: {task_id}")
    task = tasks[task_id]
    source = task["status"]
    if not can_transition(source, target):
        raise ValueError(f"Illegal transition: {source} -> {target}")

    run_id = state.get("active_run_id")
    run_path = harness / "runs" / run_id / "run.json" if run_id else None
    run = read_json(run_path) if run_path else None
    if run and run.get("task_id") != task_id:
        raise ValueError("Active run belongs to another task")
    if source in ACTIVE_STATES and not run:
        raise ValueError("Active lifecycle transition requires an active run")

    if target == "verifying":
        require_recorded(run, "implementation")
    elif target == "reviewing":
        require_passed_after(run, "verification", "implementation")
    elif target == "browser_validating":
        if not task["verification"]["requires_browser"]:
            raise ValueError("Task does not require browser validation")
        require_passed_after(run, "verification", "implementation")
        require_passed_after(run, "review", "verification")
    elif target == "completed":
        require_passed_after(run, "verification", "implementation")
        require_passed_after(run, "review", "verification")
        if task["verification"]["requires_browser"]:
            if source != "browser_validating":
                raise ValueError(
                    "Browser-required task must complete from browser_validating"
                )
            require_passed_after(run, "browser_validation", "review")
        elif source != "reviewing":
            raise ValueError("Non-browser task must complete from reviewing")
    elif target == "implementing" and source in {
        "verifying",
        "reviewing",
        "browser_validating",
    }:
        phase = {
            "verifying": "verification",
            "reviewing": "review",
            "browser_validating": "browser",
        }[source]
        advice = retry_advice(run, read_json(harness / "config.json"), phase)
        if advice["action"] != "repair":
            raise ValueError(
                f"{phase} repair is not allowed; retry action is "
                f"{advice['action']} ({advice['counted_failures']}/"
                f"{advice['retry_limit']} counted failures)"
            )

    timestamp = utc_now()
    task["status"] = target
    task["updated_at"] = timestamp
    entry = {
        "task_id": task_id,
        "run_id": run_id,
        "from": source,
        "to": target,
        "reason": reason,
        "timestamp": timestamp,
    }
    if run:
        run["status"] = target
        run.setdefault("transitions", []).append(entry)
        if target == "completed":
            run["completed_at"] = timestamp
        if target in {"blocked", *RETIRED_STATES}:
            run["stop_reason"] = reason
        atomic_write_json(run_path, run)

    state["active_task_id"] = task_id if target in ACTIVE_STATES else None
    if target == "completed":
        state["pending_commit_task_id"] = task_id
    elif target in {"blocked", *RETIRED_STATES}:
        state["active_run_id"] = None
        state["pending_commit_task_id"] = None
        (harness / "current-task.json").unlink(missing_ok=True)

    atomic_write_json(harness / "backlog.json", backlog)
    atomic_write_json(harness / "state.json", state)
    append_jsonl(harness / "archive" / "transitions.jsonl", entry)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id")
    parser.add_argument("target")
    parser.add_argument("--reason", required=True)
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    try:
        transition(Path(args.root), args.task_id, args.target, args.reason)
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
    print(f"{args.task_id} transitioned to {args.target}.")


if __name__ == "__main__":
    main()
