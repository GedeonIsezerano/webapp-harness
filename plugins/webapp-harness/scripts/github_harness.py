from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import tempfile
import urllib.parse
import uuid
import zipfile
from pathlib import Path
from typing import Any

from harness_core import (
    PROMPT_DIR,
    SCHEMA_DIR,
    GhClient,
    GitHubHarness,
    HarnessError,
    git_root,
    parse_task_body,
    read_json,
    sha256_file,
)

RESULT_EVENTS = {
    "implementation": "implementation_result",
    "verification": "verification_result",
    "review": "review_result",
    "browser": "browser_result",
}
SENSITIVE_NAMES = {
    ".env",
    ".env.local",
    "dev-credentials.local.json",
    "credentials.json",
}


def json_output(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def require_apply_confirmation(args: argparse.Namespace) -> None:
    if args.apply and not args.confirmed:
        raise HarnessError("--apply requires --confirmed")


def harness(args: argparse.Namespace) -> GitHubHarness:
    git_root(Path(args.root).resolve())
    return GitHubHarness(GhClient(args.repo))


def initialize_command(args: argparse.Namespace) -> dict[str, Any]:
    require_apply_confirmation(args)
    value = harness(args)
    config = read_json(Path(args.config).resolve())
    return (
        value.initialize(config, allow_config_update=args.update_existing)
        if args.apply
        else value.initialization_plan(config)
    )


def proposal_command(args: argparse.Namespace) -> dict[str, Any]:
    require_apply_confirmation(args)
    value = harness(args)
    proposal = read_json(Path(args.proposal).resolve())
    if args.apply:
        if not args.expected_sha256:
            raise HarnessError("Proposal --apply requires --expected-sha256")
        return value.apply_proposal(proposal, args.expected_sha256)
    return value.proposal_plan(proposal)


def transition_command(args: argparse.Namespace) -> dict[str, Any]:
    return harness(args).transition(
        args.issue,
        args.to,
        args.reason,
        run_id=args.run_id,
        event_id=args.event_id,
    )


def result_command(args: argparse.Namespace) -> dict[str, Any]:
    payload = read_json(Path(args.result).resolve())
    if payload.get("issue_number") != args.issue:
        raise HarnessError("Result issue_number does not match --issue")
    if payload.get("run_id") != args.run_id:
        raise HarnessError("Result run_id does not match --run-id")
    return harness(args).post_result(
        args.issue,
        RESULT_EVENTS[args.kind],
        payload,
        run_id=args.run_id,
        event_id=args.event_id,
    )


def scope_override_command(args: argparse.Namespace) -> dict[str, Any]:
    return harness(args).scope_override(
        args.issue,
        args.path,
        args.operation,
        args.reason,
        run_id=args.run_id,
        applies_to=args.applies_to,
    )


def _safe_evidence_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        raise HarnessError(f"Evidence directory does not exist: {directory}")
    files = sorted(path for path in directory.rglob("*") if path.is_file())
    if not files:
        raise HarnessError("Evidence directory is empty")
    for path in files:
        if path.is_symlink() or stat.S_ISLNK(path.lstat().st_mode):
            raise HarnessError(f"Evidence cannot contain symlinks: {path}")
        if path.name.lower() in SENSITIVE_NAMES or any(
            token in path.name.lower() for token in ("credential", "secret", "token")
        ):
            raise HarnessError(
                f"Evidence contains a sensitive-looking filename: {path.name}"
            )
    return files


def _write_deterministic_zip(directory: Path, files: list[Path], target: Path) -> None:
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            relative = path.relative_to(directory).as_posix()
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100600 << 16
            archive.writestr(info, path.read_bytes())


def evidence_command(args: argparse.Namespace) -> dict[str, Any]:
    value = harness(args)
    issue = value.client.get_issue(args.issue)
    parse_task_body(issue.get("body"))
    files = _safe_evidence_files(Path(args.directory).resolve())
    tag = "harness-evidence-v1"
    release_endpoint = f"repos/{value.client.repo}/releases/tags/{tag}"
    try:
        release = value.client.api("GET", release_endpoint)
    except HarnessError:
        default_branch = (value.repo_info.get("defaultBranchRef") or {}).get("name")
        if not default_branch:
            raise HarnessError(
                "Cannot create evidence release without a default branch"
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
    with tempfile.TemporaryDirectory(prefix="webapp-harness-evidence-") as temporary:
        archive = Path(temporary) / "evidence.zip"
        _write_deterministic_zip(Path(args.directory).resolve(), files, archive)
        digest = sha256_file(archive)
        asset_name = f"issue-{args.issue}--run-{args.run_id}--{digest[:12]}.zip"
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
                    f"Existing evidence asset digest differs: {asset_name}"
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
        encoded = urllib.parse.quote(asset_name)
        url = f"{value.repo_info['url']}/releases/download/{tag}/{encoded}"
        event_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"{value.client.repo}/issues/{args.issue}/runs/{args.run_id}/evidence/{digest}",
            )
        )
        event = value.post_result(
            args.issue,
            "evidence_uploaded",
            {
                "asset_url": url,
                "asset_name": asset_name,
                "sha256": digest,
                "size": upload_path.stat().st_size,
                "file_count": len(files),
                "release_id": release["id"],
            },
            run_id=args.run_id,
            event_id=event_id,
        )
    return event


def validate_command(args: argparse.Namespace) -> dict[str, Any]:
    return harness(args).validate()


def resources_command(_: argparse.Namespace) -> dict[str, Any]:
    return {
        "schemas": {path.name: str(path) for path in sorted(SCHEMA_DIR.glob("*.json"))},
        "prompts": {path.name: str(path) for path in sorted(PROMPT_DIR.glob("*.md"))},
    }


def common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--root", default=".", help="Path inside the target Git worktree"
    )
    parser.add_argument(
        "--repo", help="GitHub OWNER/REPO; defaults to the worktree's GitHub repository"
    )


def apply_arguments(parser: argparse.ArgumentParser) -> None:
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--confirmed", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Operate the GitHub issue-backed Webapp Harness"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    initialize = commands.add_parser(
        "initialize", help="Plan or create GitHub harness configuration"
    )
    common_arguments(initialize)
    initialize.add_argument(
        "--config",
        required=True,
        help="Temporary configuration JSON outside the repository",
    )
    initialize.add_argument(
        "--update-existing",
        action="store_true",
        help="With confirmed apply, replace a differing control-issue configuration",
    )
    apply_arguments(initialize)
    initialize.set_defaults(handler=initialize_command)

    proposal = commands.add_parser(
        "proposal", help="Validate or create a confirmed issue backlog"
    )
    common_arguments(proposal)
    proposal.add_argument(
        "--proposal",
        required=True,
        help="Temporary proposal JSON outside the repository",
    )
    proposal.add_argument("--expected-sha256")
    apply_arguments(proposal)
    proposal.set_defaults(handler=proposal_command)

    status = commands.add_parser(
        "status", help="Derive deterministic backlog status from GitHub"
    )
    common_arguments(status)
    status.set_defaults(handler=lambda args: harness(args).status())

    retry = commands.add_parser(
        "retry-status", help="Derive the deterministic retry decision"
    )
    common_arguments(retry)
    retry.add_argument("--issue", type=int, required=True)
    retry.add_argument("--run-id", required=True)
    retry.add_argument(
        "--phase", choices=["verification", "review", "browser"], required=True
    )
    retry.set_defaults(
        handler=lambda args: harness(args).retry_decision(
            args.issue, args.phase, args.run_id
        )
    )

    context = commands.add_parser(
        "context", help="Return a validated task, config, event, and resource snapshot"
    )
    common_arguments(context)
    context.add_argument("--issue", type=int, required=True)
    context.set_defaults(handler=lambda args: harness(args).context(args.issue))

    transition = commands.add_parser("transition", help="Record a lifecycle transition")
    common_arguments(transition)
    transition.add_argument("--issue", type=int, required=True)
    transition.add_argument("--to", required=True)
    transition.add_argument("--reason", required=True)
    transition.add_argument("--run-id")
    transition.add_argument("--event-id")
    transition.set_defaults(handler=transition_command)

    result = commands.add_parser(
        "record-result", help="Record a validated worker or phase result"
    )
    common_arguments(result)
    result.add_argument("--issue", type=int, required=True)
    result.add_argument("--run-id", required=True)
    result.add_argument("--kind", choices=sorted(RESULT_EVENTS), required=True)
    result.add_argument("--result", required=True)
    result.add_argument("--event-id")
    result.set_defaults(handler=result_command)

    override = commands.add_parser(
        "scope-override", help="Record a main-agent executive scope override"
    )
    common_arguments(override)
    override.add_argument("--issue", type=int, required=True)
    override.add_argument("--run-id", required=True)
    override.add_argument("--path", action="append", required=True)
    override.add_argument("--operation", action="append", required=True)
    override.add_argument("--reason", required=True)
    override.add_argument("--applies-to", default="current_run")
    override.set_defaults(handler=scope_override_command)

    evidence = commands.add_parser(
        "upload-evidence", help="Upload an immutable evidence bundle and record it"
    )
    common_arguments(evidence)
    evidence.add_argument("--issue", type=int, required=True)
    evidence.add_argument("--run-id", required=True)
    evidence.add_argument("--directory", required=True)
    evidence.set_defaults(handler=evidence_command)

    validate = commands.add_parser(
        "validate", help="Validate remote issue markers, labels, and event chains"
    )
    common_arguments(validate)
    validate.set_defaults(handler=validate_command)

    resources = commands.add_parser(
        "resources", help="Print installed prompt and schema paths"
    )
    resources.set_defaults(handler=resources_command)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        json_output(args.handler(args))
        return 0
    except HarnessError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
