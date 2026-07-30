#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

from common import (
    append_result,
    atomic_write_json,
    latest_result_entry,
    read_json,
)


PASSING_BROWSER_SURFACES = frozenset(
    {"browser_use", "chrome_control", "computer_use", "playwright"}
)
RESULT_KIND = {
    "verification": "verification",
    "browser-result": "browser_validation",
    "review": "review",
    "implementation-result": "implementation",
}
EXPECTED_STAGE = {
    "verification": "verifying",
    "browser-result": "browser_validating",
    "review": "reviewing",
    "implementation-result": "implementing",
}


def schema_errors(data: dict, schema: dict) -> list[str]:
    return [
        error.message
        for error in Draft202012Validator(schema).iter_errors(data)
    ]


def validate_browser_result(root: Path, harness: Path, run_id: str, data: dict) -> None:
    surface = data["tooling"]["surface"]
    if data["status"] == "PASSED" and surface not in PASSING_BROWSER_SURFACES:
        allowed = ", ".join(sorted(PASSING_BROWSER_SURFACES))
        raise ValueError(
            "PASSED browser result requires a supported control surface "
            f"({allowed}); got {surface}"
        )
    if data["status"] == "PASSED":
        if data["failure_class"] is not None:
            raise ValueError("PASSED browser result must use failure_class=null")
        if data["blocker"] is not None:
            raise ValueError("PASSED browser result must use blocker=null")
        if not all(data["preflight"].values()):
            raise ValueError("PASSED browser result requires a complete preflight")
    else:
        if data["failure_class"] is None:
            raise ValueError("Non-passing browser result requires failure_class")
        if not isinstance(data["blocker"], str) or not data["blocker"].strip():
            raise ValueError("Non-passing browser result requires an exact blocker")

    plan = read_json(harness / "runs" / run_id / "browser-plan.json")
    required_ids = [item["criterion_id"] for item in plan["criteria"]]
    criteria = data.get("criteria", [])
    recorded_ids = [criterion["criterion_id"] for criterion in criteria]
    if len(recorded_ids) != len(set(recorded_ids)):
        raise ValueError("Browser result repeats criterion IDs")
    if any(criterion_id not in required_ids for criterion_id in recorded_ids):
        raise ValueError("Browser result contains a criterion outside browser-plan.json")
    if data["status"] == "PASSED":
        if set(recorded_ids) != set(required_ids):
            raise ValueError("PASSED browser result must cover every planned criterion")
        if any(criterion["result"] != "PASS" for criterion in criteria):
            raise ValueError("PASSED browser result cannot contain non-passing criteria")
    elif data["status"] == "FAILED" and not any(
        criterion["result"] == "FAIL" for criterion in criteria
    ):
        raise ValueError("FAILED browser result requires at least one failed criterion")

    run_dir = (harness / "runs" / run_id).resolve()
    for criterion in criteria:
        screenshots = criterion.get("screenshots", [])
        if criterion["result"] != "NOT_VERIFIED" and not screenshots:
            raise ValueError(
                f"{criterion['criterion_id']} requires at least one screenshot"
            )
        for relative in screenshots:
            target = (root / relative).resolve()
            if run_dir not in target.parents:
                raise ValueError(
                    "Screenshot must live under the active run directory: "
                    f"{relative}"
                )
            if not target.is_file():
                raise ValueError(f"Missing screenshot file: {relative}")


def record(root: Path, kind: str, input_path: Path) -> dict:
    harness = root / ".harness"
    state = read_json(harness / "state.json")
    run_id = state.get("active_run_id")
    if not run_id:
        raise ValueError("No active run")
    data = read_json(input_path)
    schema = read_json(harness / "schema" / f"{kind}.schema.json")
    errors = schema_errors(data, schema)
    if errors:
        raise ValueError("; ".join(errors))

    run_path = harness / "runs" / run_id / "run.json"
    run = read_json(run_path)
    if run.get("status") != EXPECTED_STAGE[kind]:
        raise ValueError(
            f"{kind} can only be recorded during {EXPECTED_STAGE[kind]}"
        )
    if data.get("task_id") != run["task_id"] or data.get("run_id") != run_id:
        raise ValueError("Result does not belong to active task/run")
    if (
        kind == "review"
        and data["verdict"] == "APPROVED"
        and any(finding["severity"] == "blocking" for finding in data["findings"])
    ):
        raise ValueError("APPROVED review cannot contain blocking findings")
    if kind == "review":
        verification = latest_result_entry(run, "verification")
        snapshot = run.get("diff_snapshot", {})
        diff_path = root / snapshot.get("path", "")
        if (
            not verification
            or snapshot.get("after_event_sequence", -1) < verification["sequence"]
            or not diff_path.is_file()
        ):
            raise ValueError(
                "Review requires a diff collected after the latest verification"
            )
    if kind == "verification":
        if data["status"] == "PASSED" and data["failure_class"] is not None:
            raise ValueError("PASSED verification must use failure_class=null")
        if data["status"] != "PASSED" and data["failure_class"] is None:
            raise ValueError("Non-passing verification requires failure_class")
    if kind == "browser-result":
        validate_browser_result(root, harness, run_id, data)

    entry = append_result(run, RESULT_KIND[kind], data)
    atomic_write_json(run_path, run)
    return entry


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "kind",
        choices=[
            "verification",
            "browser-result",
            "review",
            "implementation-result",
        ],
    )
    parser.add_argument("input")
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    try:
        entry = record(Path(args.root), args.kind, Path(args.input))
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
    print(f"Recorded {args.kind} as event {entry['sequence']}.")


if __name__ == "__main__":
    main()
