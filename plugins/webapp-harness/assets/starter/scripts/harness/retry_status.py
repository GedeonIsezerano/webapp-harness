#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from common import latest_result, read_json, result_entries


PHASE_RESULT_KIND = {
    "verification": "verification",
    "review": "review",
    "browser": "browser_validation",
}


def unsuccessful(result: dict, phase: str) -> bool:
    if phase == "review":
        return result.get("verdict") == "CHANGES_REQUIRED"
    return result.get("status") in {"FAILED", "INCOMPLETE"}


def countable_failure(result: dict, phase: str) -> bool:
    if phase == "review":
        return unsuccessful(result, phase)
    return unsuccessful(result, phase) and result.get("failure_class") == "product"


def retry_advice(run: dict, config: dict, phase: str) -> dict:
    if phase not in PHASE_RESULT_KIND:
        raise ValueError(f"Unknown retry phase: {phase}")
    kind = PHASE_RESULT_KIND[phase]
    latest = latest_result(run, kind)
    if not latest:
        raise ValueError(f"No {phase} result has been recorded")
    limit = config["retry_limits"][phase]
    failures = sum(
        countable_failure(entry.get("result", {}), phase)
        for entry in result_entries(run, kind)
    )
    if not unsuccessful(latest, phase):
        action = "advance"
    elif phase != "review" and latest.get("failure_class") != "product":
        action = "block"
    elif failures >= limit:
        action = "block"
    else:
        action = "repair"
    return {
        "phase": phase,
        "action": action,
        "counted_failures": failures,
        "retry_limit": limit,
        "remaining_repairs": max(0, limit - failures),
        "failure_class": latest.get("failure_class"),
    }


def inspect(root: Path, phase: str) -> dict:
    harness = root / ".harness"
    state = read_json(harness / "state.json")
    run_id = state.get("active_run_id")
    if not run_id:
        raise ValueError("No active run")
    return retry_advice(
        read_json(harness / "runs" / run_id / "run.json"),
        read_json(harness / "config.json"),
        phase,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=sorted(PHASE_RESULT_KIND))
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    try:
        print(json.dumps(inspect(Path(args.root), args.phase), indent=2))
        return 0
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
