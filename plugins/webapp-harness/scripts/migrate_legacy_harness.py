from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import urllib.parse
from pathlib import Path
from typing import Any

from github_harness import SENSITIVE_NAMES, _write_deterministic_zip
from harness_core import (
    GhClient,
    GitHubHarness,
    HarnessError,
    build_event,
    git_root,
    marker_lookup,
    read_json,
    render_event_comment,
    sha256_file,
    sha256_json,
    status_from_labels,
    utc_now,
    validate_proposal,
)

LEGACY_ACTIVE = {"implementing", "verifying", "reviewing", "browser_validating"}


def convert_config(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "retry_limits": value.get(
            "retry_limits", {"verification": 2, "review": 2, "browser": 2}
        ),
        "verification_profiles": value.get("verification_profiles", {}),
        **({"app": value["app"]} if isinstance(value.get("app"), dict) else {}),
        **(
            {"browser": value["browser"]}
            if isinstance(value.get("browser"), dict)
            else {}
        ),
        "commit": {
            "subject_format": (value.get("commit") or {})
            .get("subject_format", "[#{issue_number}] {title}")
            .replace("{task_id}", "#{issue_number}"),
        },
    }


def _guidance(values: Any, reason: str) -> list[dict[str, str]]:
    if not isinstance(values, list):
        return []
    return [
        {"path": value, "reason": reason}
        for value in values
        if isinstance(value, str) and value
    ]


def convert_task(value: dict[str, Any], fallback_profile: str) -> dict[str, Any]:
    legacy_id = str(value.get("id") or value.get("proposal_key") or "legacy-task")
    verification = (
        value.get("verification") if isinstance(value.get("verification"), dict) else {}
    )
    profiles = (
        verification.get("profiles")
        if isinstance(verification.get("profiles"), list)
        else []
    )
    if not profiles:
        profiles = [fallback_profile]
    scope = value.get("scope") if isinstance(value.get("scope"), dict) else {}
    gap = value.get("gap_evidence")
    if not isinstance(gap, list) or not gap:
        gap = [
            {
                "location": ".harness/backlog.json",
                "observation": "Imported from the legacy harness backlog.",
            }
        ]
    criteria = value.get("acceptance_criteria")
    if not isinstance(criteria, list) or not criteria:
        criteria = [
            {
                "id": f"{legacy_id}-legacy",
                "description": "Preserve the legacy task contract recorded in the uploaded archive.",
                "verification": ["manual-review"],
            }
        ]
    return {
        "schema_version": 2,
        "proposal_key": legacy_id,
        "legacy_id": legacy_id,
        "title": str(value.get("title") or legacy_id),
        "description": str(value.get("description") or "Imported legacy harness task."),
        "priority": int(value.get("priority"))
        if isinstance(value.get("priority"), int)
        else 1_000_000,
        "dependencies": [str(item) for item in value.get("dependencies", [])],
        **(
            {"type": value["type"]}
            if value.get("type")
            in {"user-facing", "backend", "infrastructure", "documentation"}
            else {}
        ),
        "gap_evidence": gap,
        "acceptance_criteria": criteria,
        "verification": {
            "profiles": profiles,
            "requires_browser": bool(verification.get("requires_browser", False)),
        },
        "scope": {
            "recommended_paths": _guidance(
                scope.get("allowed_paths") or scope.get("recommended_paths"),
                "Legacy allowed path converted to a non-exclusive recommended starting point.",
            ),
            "forbidden_paths": _guidance(
                scope.get("forbidden_paths"),
                "Legacy delegated-worker prohibition retained; the main agent may record an executive override.",
            ),
        },
    }


def completed_index(root: Path) -> list[dict[str, Any]]:
    path = root / ".harness" / "completed-tasks.json"
    if not path.exists():
        return []
    value = read_json(path)
    return value.get("completed_tasks", []) if isinstance(value, dict) else []


def legacy_tree_manifest(root: Path) -> list[dict[str, Any]]:
    harness_dir = root / ".harness"
    if not harness_dir.is_dir():
        raise HarnessError(f"No legacy .harness directory at {root}")
    rows = []
    for path in legacy_archive_files(root):
        if path.is_symlink():
            raise HarnessError(f"Legacy archive cannot contain symlinks: {path}")
        rows.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return rows


def _sensitive_legacy_path(path: Path) -> bool:
    name = path.name.lower()
    return name in SENSITIVE_NAMES or any(
        token in name for token in ("credential", "secret", "token")
    )


def legacy_archive_files(root: Path) -> list[Path]:
    harness_dir = root / ".harness"
    if not harness_dir.is_dir():
        raise HarnessError(f"No legacy .harness directory at {root}")
    files = []
    for path in sorted(item for item in harness_dir.rglob("*") if item.is_file()):
        if path.is_symlink():
            raise HarnessError(f"Legacy archive cannot contain symlinks: {path}")
        if not _sensitive_legacy_path(path):
            files.append(path)
    return files


def excluded_legacy_files(root: Path) -> list[str]:
    harness_dir = root / ".harness"
    return [
        path.relative_to(root).as_posix()
        for path in sorted(item for item in harness_dir.rglob("*") if item.is_file())
        if _sensitive_legacy_path(path)
    ]


def migration_material(root: Path) -> dict[str, Any]:
    config = convert_config(read_json(root / ".harness" / "config.json"))
    profiles = list(config["verification_profiles"])
    if not profiles:
        raise HarnessError("Legacy configuration has no usable verification profile")
    backlog = read_json(root / ".harness" / "backlog.json")
    raw_tasks = backlog.get("tasks", []) if isinstance(backlog, dict) else []
    tasks = [convert_task(task, profiles[0]) for task in raw_tasks]
    task_keys = {task["proposal_key"] for task in tasks}
    completed = completed_index(root)
    completed_ids = {
        str(entry.get("task_id"))
        for entry in completed
        if isinstance(entry, dict) and entry.get("task_id")
    }
    referenced = {dependency for task in tasks for dependency in task["dependencies"]}
    missing_completed = sorted((referenced - task_keys) & completed_ids)
    unknown = sorted(referenced - task_keys - completed_ids)
    if unknown:
        raise HarnessError(
            f"Legacy tasks reference unknown dependencies: {', '.join(unknown)}"
        )
    for legacy_id in missing_completed:
        tasks.append(
            {
                "schema_version": 2,
                "proposal_key": legacy_id,
                "legacy_id": legacy_id,
                "title": f"Imported completed task {legacy_id}",
                "description": "Closed dependency stub imported from the legacy completion index.",
                "priority": 1_000_000,
                "dependencies": [],
                "type": "documentation",
                "gap_evidence": [
                    {
                        "location": ".harness/completed-tasks.json",
                        "observation": "Legacy completion index entry required by an unresolved dependency.",
                    }
                ],
                "acceptance_criteria": [
                    {
                        "id": f"{legacy_id}-import",
                        "description": "Preserve the completed dependency relationship.",
                        "verification": ["manual-review"],
                    }
                ],
                "verification": {"profiles": [profiles[0]], "requires_browser": False},
                "scope": {"recommended_paths": [], "forbidden_paths": []},
            }
        )
    statuses = {
        str(task.get("id") or task.get("proposal_key")): str(
            task.get("status") or "proposed"
        )
        for task in raw_tasks
    }
    statuses.update({legacy_id: "completed" for legacy_id in missing_completed})
    proposal = {
        "schema_version": 2,
        "title": "Legacy .harness migration",
        "tasks": tasks,
    }
    validate_proposal(proposal, config)
    active = sorted(key for key, status in statuses.items() if status in LEGACY_ACTIVE)
    if len(active) > 1:
        raise HarnessError(
            f"Legacy state has multiple active tasks: {', '.join(active)}"
        )
    tree = legacy_tree_manifest(root)
    plan_payload = {
        "schema_version": 1,
        "configuration": config,
        "proposal": proposal,
        "legacy_statuses": statuses,
        "archive_manifest": tree,
        "excluded_sensitive_files": excluded_legacy_files(root),
    }
    return {**plan_payload, "migration_sha256": sha256_json(plan_payload)}


def migration_plan(root: Path, repo: str | None) -> dict[str, Any]:
    material = migration_material(root)
    return {
        "repository_root": str(root),
        "target_repository": repo,
        "migration_sha256": material["migration_sha256"],
        "task_issue_count": len(material["proposal"]["tasks"]),
        "completed_dependency_stubs": sum(
            status == "completed"
            and key
            not in {
                str(task.get("id") or task.get("proposal_key"))
                for task in read_json(root / ".harness" / "backlog.json").get(
                    "tasks", []
                )
            }
            for key, status in material["legacy_statuses"].items()
        ),
        "archive_file_count": len(material["archive_manifest"]),
        "archive_bytes": sum(item["size"] for item in material["archive_manifest"]),
        "excluded_sensitive_files": material["excluded_sensitive_files"],
        "deletes_local_files": False,
    }


def _ensure_release(value: GitHubHarness) -> tuple[str, dict[str, Any]]:
    tag = "harness-evidence-v1"
    try:
        release = value.client.api(
            "GET", f"repos/{value.client.repo}/releases/tags/{tag}"
        )
    except HarnessError:
        default_branch = (value.repo_info.get("defaultBranchRef") or {}).get("name")
        if not default_branch:
            raise HarnessError(
                "Cannot create legacy archive release without a default branch"
            )
        release = value.client.api(
            "POST",
            f"repos/{value.client.repo}/releases",
            {
                "tag_name": tag,
                "target_commitish": default_branch,
                "name": "Harness evidence",
                "body": "Immutable evidence bundles referenced by Webapp Harness task issues.",
                "prerelease": True,
            },
        )
    return tag, release


def apply_migration(root: Path, repo: str | None, expected: str) -> dict[str, Any]:
    material = migration_material(root)
    if material["migration_sha256"] != expected:
        raise HarnessError("Migration SHA-256 does not match the confirmed preview")
    value = GitHubHarness(GhClient(repo))
    initialized = value.initialize(material["configuration"], allow_config_update=True)
    proposal = material["proposal"]
    proposal_digest = sha256_json(proposal)
    applied = value.apply_proposal(proposal, proposal_digest)
    task_issues = value.client.list_issues(state="all", label="harness:task")
    mapping: dict[str, dict[str, Any]] = {}
    for task in proposal["tasks"]:
        issue = marker_lookup(task_issues, "task", "proposal_key", task["proposal_key"])
        if not issue:
            raise HarnessError(
                f"Missing migrated task issue for {task['proposal_key']}"
            )
        mapping[task["proposal_key"]] = issue
    for key, target in material["legacy_statuses"].items():
        issue = mapping[key]
        current = status_from_labels(issue.get("labels", []))
        if current == target:
            continue
        if current != "proposed":
            raise HarnessError(
                f"Migrated issue for {key} has unexpected status {current}; expected proposed or {target}"
            )
        if target == "proposed":
            continue
        if target not in {
            "ready",
            "blocked",
            "implementing",
            "verifying",
            "reviewing",
            "browser_validating",
            "completed",
            "cancelled",
            "superseded",
        }:
            raise HarnessError(f"Unsupported legacy status for {key}: {target}")
        run_id = f"legacy-{key}" if target in LEGACY_ACTIVE else None
        events = value.issue_events(issue["number"])
        event = build_event(
            issue["number"],
            "completed"
            if target == "completed"
            else ("blocked" if target == "blocked" else "status_changed"),
            {
                "from": "proposed",
                "to": target,
                "reason": "legacy_import",
                "legacy": True,
            },
            events,
            run_id=run_id,
            recorded_at=utc_now(),
        )
        value.client.comment(issue["number"], render_event_comment(event))
        payload: dict[str, Any] = {
            "labels": ["harness:task", f"harness:status:{target}"]
        }
        if target in {"completed", "cancelled", "superseded"}:
            payload.update(
                {
                    "state": "closed",
                    "state_reason": "completed"
                    if target == "completed"
                    else "not_planned",
                }
            )
        value.client.update_issue(issue["number"], payload)

    files = legacy_archive_files(root)
    if not files:
        raise HarnessError("No non-sensitive legacy files are available to archive")
    tag, release = _ensure_release(value)
    with tempfile.TemporaryDirectory(prefix="webapp-harness-legacy-") as temporary:
        archive = Path(temporary) / "legacy-harness.zip"
        _write_deterministic_zip(root / ".harness", files, archive)
        digest = sha256_file(archive)
        asset_name = f"legacy-harness--{expected[:12]}--{digest[:12]}.zip"
        upload_path = Path(temporary) / asset_name
        os.replace(archive, upload_path)
        matching_assets = [
            asset
            for asset in value.client.release_assets(release["id"])
            if asset.get("name") == asset_name
        ]
        if matching_assets:
            existing_digest = matching_assets[0].get("digest")
            if existing_digest not in {None, f"sha256:{digest}"}:
                raise HarnessError(
                    f"Existing legacy archive digest differs: {asset_name}"
                )
        else:
            value.client._call(
                [
                    "gh",
                    "release",
                    "upload",
                    tag,
                    str(upload_path),
                    "--repo",
                    str(value.client.repo),
                ]
            )
        asset_url = f"{value.repo_info['url']}/releases/download/{tag}/{urllib.parse.quote(asset_name)}"
    control_number = initialized["control_issue_number"]
    existing_comments = value.client.comments(control_number)
    if not any(
        expected in (comment.get("body") or "") for comment in existing_comments
    ):
        value.client.comment(
            control_number,
            "### Legacy migration imported\n\n"
            + f"Migration SHA-256: `{expected}`\n\n"
            + f"Legacy archive: {asset_url}\n\n"
            + f"Archive SHA-256: `{digest}`\n\n"
            + "Local `.harness` files were preserved and require separate cleanup authorization.",
        )
    return {
        "migration_sha256": expected,
        "control_issue": initialized["control_issue_url"],
        "backlog_issue": applied["parent_issue"],
        "tasks": applied["tasks"],
        "legacy_archive_url": asset_url,
        "legacy_archive_sha256": digest,
        "release_id": release["id"],
        "deleted_local_files": [],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plan or apply a non-destructive legacy .harness migration"
    )
    parser.add_argument("--root", default=".")
    parser.add_argument("--repo")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--confirmed", action="store_true")
    parser.add_argument("--expected-sha256")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        root = git_root(Path(args.root).resolve())
        if args.plan:
            result = migration_plan(root, args.repo)
        else:
            if not args.confirmed or not args.expected_sha256:
                raise HarnessError("--apply requires --confirmed and --expected-sha256")
            result = apply_migration(root, args.repo, args.expected_sha256)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except HarnessError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
