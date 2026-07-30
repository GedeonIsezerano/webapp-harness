#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

from common import atomic_write_json, read_json, utc_now


BROWSER_KINDS = {"browser", "visual", "e2e"}


def prepare(root: Path) -> Path:
    harness = root / ".harness"
    state = read_json(harness / "state.json")
    run_id = state.get("active_run_id")
    if not run_id:
        raise ValueError("No active run")
    current = read_json(harness / "current-task.json")
    if current.get("run_id") != run_id:
        raise ValueError("Current task does not match the active run")
    task = current["task"]
    criteria = [
        {
            "criterion_id": criterion["id"],
            "description": criterion["description"],
            "verification_kinds": criterion["verification"],
        }
        for criterion in task["acceptance_criteria"]
        if BROWSER_KINDS.intersection(criterion["verification"])
    ]
    if task["verification"]["requires_browser"] and not criteria:
        raise ValueError(
            "Browser validation is required but no acceptance criterion uses "
            "browser, visual, or e2e verification"
        )
    plan = {
        "schema_version": 1,
        "task_id": task["id"],
        "run_id": run_id,
        "generated_at": utc_now(),
        "criteria": criteria,
        "execution_policy": {
            "group_criteria_into_minimal_journeys": True,
            "shared_screenshots_allowed": True,
            "fresh_console_and_network_required": True,
            "persisted_state_required": True,
        },
    }
    schema = read_json(harness / "schema" / "browser-plan.schema.json")
    errors = list(Draft202012Validator(schema).iter_errors(plan))
    if errors:
        raise ValueError(
            "Generated browser plan is invalid: "
            + "; ".join(error.message for error in errors)
        )
    path = harness / "runs" / run_id / "browser-plan.json"
    atomic_write_json(path, plan)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract the exact browser criteria for the active run."
    )
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    try:
        print(json.dumps({"browser_plan": str(prepare(Path(args.root)))}, indent=2))
        return 0
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
