#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from common import atomic_write_json, latest_result, read_json, task_map


def git(root: Path, *args: str) -> str:
    process = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
    )
    if process.returncode:
        raise ValueError(process.stderr.strip() or process.stdout.strip())
    return process.stdout.strip()


def changed_paths(root: Path) -> set[str]:
    tracked = git(root, "diff", "--name-only", "HEAD").splitlines()
    staged = git(root, "diff", "--cached", "--name-only", "HEAD").splitlines()
    untracked = git(root, "ls-files", "--others", "--exclude-standard").splitlines()
    return {path for path in tracked + staged + untracked if path}


def within(path: str, prefix: str) -> bool:
    normalized = prefix.rstrip("/")
    return path == normalized or path.startswith(normalized + "/")


def assert_task_scope(root: Path, task: dict) -> None:
    scope = task.get("scope", {})
    allowed = scope.get("allowed_paths", [])
    forbidden = scope.get("forbidden_paths", [])
    runtime_paths = [
        ".harness/backlog.json",
        ".harness/completed-tasks.json",
        ".harness/archive/",
        ".harness/state.json",
        ".harness/current-task.json",
        ".harness/runs/",
    ]
    violations = []
    for path in sorted(changed_paths(root)):
        if any(within(path, prefix) for prefix in runtime_paths):
            continue
        if any(within(path, prefix) for prefix in forbidden):
            violations.append(f"{path} is forbidden")
            continue
        if not any(within(path, prefix) for prefix in allowed):
            violations.append(f"{path} is outside allowed paths")
    if violations:
        raise ValueError("Task scope violation:\n" + "\n".join(violations))


def commit_subject(config: dict, task: dict) -> str:
    template = config["commit"]["subject_format"]
    try:
        subject = template.format(task_id=task["id"], title=task["title"])
    except (KeyError, ValueError) as error:
        raise ValueError(f"Invalid commit.subject_format: {error}") from error
    if not subject.strip():
        raise ValueError("commit.subject_format produced an empty subject")
    return subject[:72]


def create(root: Path) -> str:
    harness = root / ".harness"
    state = read_json(harness / "state.json")
    run_id = state.get("active_run_id")
    task_id = state.get("pending_commit_task_id")
    if not run_id or not task_id:
        raise ValueError("A completed task pending commit is required")
    backlog = read_json(harness / "backlog.json")
    task = task_map(backlog)[task_id]
    run_path = harness / "runs" / run_id / "run.json"
    run_data = read_json(run_path)
    if task["status"] != "completed" or run_data["status"] != "completed":
        raise ValueError("Task and run must both be completed")

    assert_task_scope(root, task)
    git(root, "diff", "--check")
    criteria = ", ".join(
        criterion["id"] for criterion in task["acceptance_criteria"]
    )
    config = read_json(harness / "config.json")
    subject = commit_subject(config, task)
    browser = latest_result(run_data, "browser_validation")
    body = (
        f"Task: {task_id}\n"
        f"Run: {run_id}\n"
        f"Acceptance-Criteria: {criteria}\n"
        "Verification: passed\n"
        f"Browser-Validation: {browser.get('status', 'not-required').lower()}\n"
        "Review: approved"
    )

    run_data["stop_reason"] = "completed"
    state["active_run_id"] = None
    state["pending_commit_task_id"] = None
    atomic_write_json(run_path, run_data)
    atomic_write_json(harness / "state.json", state)
    (harness / "current-task.json").unlink(missing_ok=True)
    git(root, "add", "-A")
    git(root, "commit", "-m", subject, "-m", body)
    return git(root, "rev-parse", "HEAD")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    try:
        print(create(Path(args.root)))
    except (KeyError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
