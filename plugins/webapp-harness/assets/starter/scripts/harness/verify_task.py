#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

from common import append_result, atomic_write_json, read_json


def verify(root: Path) -> dict:
    harness = root / ".harness"
    state = read_json(harness / "state.json")
    run_id = state.get("active_run_id")
    if not run_id:
        raise ValueError("No active run")
    run_path = harness / "runs" / run_id / "run.json"
    run = read_json(run_path)
    if run.get("status") != "verifying":
        raise ValueError("Verification can only run during verifying")
    backlog = read_json(harness / "backlog.json")
    task = next(
        (task for task in backlog["tasks"] if task["id"] == run["task_id"]),
        None,
    )
    if not task:
        raise ValueError("Active task not found")

    config = read_json(harness / "config.json")
    checks = []
    failed = False
    incomplete = False
    for profile in task.get("verification", {}).get("profiles", []):
        for specification in config.get("verification_profiles", {}).get(profile, []):
            command = specification["command"]
            start = time.monotonic()
            try:
                process = subprocess.run(
                    command,
                    cwd=root,
                    text=True,
                    capture_output=True,
                )
                exit_code = process.returncode
                stdout = process.stdout
                stderr = process.stderr
            except OSError as error:
                exit_code = 127
                stdout = ""
                stderr = str(error)
                incomplete = True
            checks.append(
                {
                    "name": specification.get("name", " ".join(command)),
                    "command": command,
                    "exit_code": exit_code,
                    "duration_seconds": round(time.monotonic() - start, 3),
                    "stdout_summary": stdout[-4000:],
                    "stderr_summary": stderr[-4000:],
                }
            )
            failed |= exit_code != 0
    status = (
        "INCOMPLETE"
        if not checks or incomplete
        else "FAILED" if failed
        else "PASSED"
    )
    result = {
        "task_id": task["id"],
        "run_id": run_id,
        "status": status,
        "failure_class": (
            "environment" if status == "INCOMPLETE" else
            "product" if status == "FAILED" else
            None
        ),
        "checks": checks,
    }
    append_result(run, "verification", result)
    atomic_write_json(run_path, run)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    try:
        result = verify(Path(args.root))
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
    print(result["status"])
    raise SystemExit(0 if result["status"] == "PASSED" else 1)


if __name__ == "__main__":
    main()
