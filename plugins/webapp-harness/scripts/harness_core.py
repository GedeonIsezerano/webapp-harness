from __future__ import annotations

import hashlib
import json
import re
import subprocess
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = PLUGIN_ROOT / "schemas"
PROMPT_DIR = PLUGIN_ROOT / "prompts"
API_VERSION = "2026-03-10"

ACTIVE_STATES = {"implementing", "verifying", "reviewing", "browser_validating"}
TERMINAL_STATES = {"completed", "cancelled", "superseded"}
ALLOWED_TRANSITIONS = {
    "proposed": {"ready", "blocked", "cancelled", "superseded"},
    "ready": {"implementing", "blocked", "cancelled", "superseded"},
    "implementing": {"verifying", "blocked"},
    "verifying": {"implementing", "reviewing", "blocked"},
    "reviewing": {"implementing", "browser_validating", "completed", "blocked"},
    "browser_validating": {"implementing", "completed", "blocked"},
    "blocked": {"ready", "cancelled", "superseded"},
    "completed": set(),
    "cancelled": set(),
    "superseded": set(),
}

STATUS_LABEL_PREFIX = "harness:status:"
LABELS = {
    "harness:control": ("5319e7", "Webapp Harness configuration authority"),
    "harness:backlog": ("1d76db", "Approved Webapp Harness backlog batch"),
    "harness:task": ("0e8a16", "Task managed by Webapp Harness"),
    "harness:status:proposed": ("d4c5f9", "Confirmed task awaiting promotion"),
    "harness:status:ready": ("2da44e", "Eligible for deterministic selection"),
    "harness:status:implementing": ("fbca04", "Implementation in progress"),
    "harness:status:verifying": ("f9d0c4", "Canonical checks in progress"),
    "harness:status:reviewing": ("c5def5", "Independent logic review in progress"),
    "harness:status:browser_validating": (
        "bfd4f2",
        "Rendered browser validation in progress",
    ),
    "harness:status:blocked": ("d73a4a", "Blocked with recorded evidence"),
    "harness:status:completed": ("0e8a16", "All required gates passed"),
    "harness:status:cancelled": ("6e7781", "Closed without implementation"),
    "harness:status:superseded": ("6e7781", "Replaced by another task"),
}


class HarnessError(ValueError):
    pass


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_run_id(run_id: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", run_id):
        raise HarnessError(f"Invalid run_id: {run_id}")


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HarnessError(f"Missing required file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise HarnessError(f"Invalid JSON in {path}: {exc}") from exc


def git_root(start: Path) -> Path:
    proc = subprocess.run(
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode:
        raise HarnessError(proc.stderr.strip() or f"{start} is not a Git worktree")
    return Path(proc.stdout.strip()).resolve()


def marker(kind: str, payload: dict[str, Any]) -> str:
    rendered = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
    if "-->" in rendered:
        raise HarnessError("Machine marker payload cannot contain '-->'")
    return f"<!-- webapp-harness:{kind}\n{rendered}\n-->"


def extract_marker(body: str | None, kind: str) -> dict[str, Any]:
    pattern = re.compile(
        rf"<!--\s*webapp-harness:{re.escape(kind)}\s*\n(.*?)\n-->", re.DOTALL
    )
    matches = pattern.findall(body or "")
    if len(matches) != 1:
        raise HarnessError(
            f"Expected exactly one webapp-harness:{kind} marker; found {len(matches)}"
        )
    try:
        value = json.loads(matches[0])
    except json.JSONDecodeError as exc:
        raise HarnessError(f"Invalid webapp-harness:{kind} marker JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise HarnessError(f"webapp-harness:{kind} marker must contain an object")
    return value


def validate_config(config: dict[str, Any]) -> None:
    allowed_fields = {
        "schema_version",
        "retry_limits",
        "verification_profiles",
        "app",
        "browser",
        "commit",
    }
    unknown_fields = sorted(set(config) - allowed_fields)
    if unknown_fields:
        raise HarnessError(
            f"Configuration has unknown fields: {', '.join(unknown_fields)}"
        )
    if config.get("schema_version") != 2:
        raise HarnessError("Configuration schema_version must be 2")
    profiles = config.get("verification_profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise HarnessError("Configuration needs at least one verification profile")
    for profile, checks in profiles.items():
        if (
            not isinstance(profile, str)
            or not profile
            or not isinstance(checks, list)
            or not checks
        ):
            raise HarnessError("Every verification profile needs at least one check")
        for check in checks:
            if (
                not isinstance(check, dict)
                or set(check) != {"name", "command"}
                or not check.get("name")
            ):
                raise HarnessError(f"Invalid check in verification profile {profile}")
            command = check.get("command")
            if (
                not isinstance(command, list)
                or not command
                or not all(isinstance(v, str) and v for v in command)
            ):
                raise HarnessError(f"Invalid command in verification profile {profile}")
    retry = config.get("retry_limits")
    if (
        not isinstance(retry, dict)
        or set(retry) != {"verification", "review", "browser"}
        or any(
            not isinstance(retry.get(name), int)
            or isinstance(retry.get(name), bool)
            or retry[name] < 0
            for name in ("verification", "review", "browser")
        )
    ):
        raise HarnessError(
            "retry_limits must define non-negative verification, review, and browser values"
        )
    commit = config.get("commit")
    if not isinstance(commit, dict) or set(commit) != {"subject_format"}:
        raise HarnessError("commit allows only subject_format")
    subject = commit.get("subject_format")
    if not isinstance(subject, str) or not subject:
        raise HarnessError("commit.subject_format is required")
    try:
        subject.format(issue_number=1, title="Task")
    except (KeyError, ValueError) as exc:
        raise HarnessError(f"Invalid commit.subject_format: {exc}") from exc
    app = config.get("app")
    if app is not None and (
        not isinstance(app, dict)
        or not set(app) <= {"start_command", "health_url", "notes"}
    ):
        raise HarnessError("app configuration has unknown fields")
    browser = config.get("browser")
    if browser is not None and (
        not isinstance(browser, dict)
        or not set(browser) <= {"playbook_paths", "fixture_notes", "profile_notes"}
    ):
        raise HarnessError("browser configuration has unknown fields")


def _validate_repository_path(value: str, field: str) -> None:
    if value.startswith("/") or "\\" in value or ".." in Path(value).parts:
        raise HarnessError(f"{field} must be a safe repository-relative path: {value}")


def path_matches_rule(path: str, rule: str) -> bool:
    normalized_path = path.rstrip("/")
    normalized_rule = rule.rstrip("/")
    if normalized_path == normalized_rule:
        return True
    if rule.endswith("/") and normalized_path.startswith(normalized_rule + "/"):
        return True
    if any(token in rule for token in ("*", "?", "[")):
        return fnmatchcase(path, rule) or fnmatchcase(normalized_path, rule)
    return False


def _validate_path_guidance(scope: dict[str, Any], field: str) -> None:
    entries = scope.get(field)
    if not isinstance(entries, list):
        raise HarnessError(f"scope.{field} must be an array")
    for entry in entries:
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("path"), str)
            or not entry["path"]
        ):
            raise HarnessError(f"Every scope.{field} entry needs a path")
        if set(entry) != {"path", "reason"}:
            raise HarnessError(f"Every scope.{field} entry allows only path and reason")
        _validate_repository_path(entry["path"], f"scope.{field}")
        if not isinstance(entry.get("reason"), str) or not entry["reason"]:
            raise HarnessError(f"Every scope.{field} entry needs a reason")


def validate_task(task: dict[str, Any], profile_names: set[str] | None = None) -> None:
    allowed_fields = {
        "schema_version",
        "proposal_key",
        "legacy_id",
        "title",
        "description",
        "priority",
        "dependencies",
        "type",
        "gap_evidence",
        "acceptance_criteria",
        "verification",
        "scope",
    }
    unknown_fields = sorted(set(task) - allowed_fields)
    if unknown_fields:
        raise HarnessError(f"Task has unknown fields: {', '.join(unknown_fields)}")
    required = (
        "proposal_key",
        "title",
        "description",
        "priority",
        "dependencies",
        "gap_evidence",
        "acceptance_criteria",
        "verification",
        "scope",
    )
    if task.get("schema_version") != 2:
        raise HarnessError("Task schema_version must be 2")
    for field in required:
        if field not in task:
            raise HarnessError(f"Task is missing {field}")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", str(task["proposal_key"])):
        raise HarnessError(f"Invalid proposal_key: {task['proposal_key']}")
    if not isinstance(task["title"], str) or not task["title"].strip():
        raise HarnessError(f"Task {task['proposal_key']} title is required")
    if not isinstance(task["description"], str) or not task["description"].strip():
        raise HarnessError(f"Task {task['proposal_key']} description is required")
    if not isinstance(task["priority"], int) or isinstance(task["priority"], bool):
        raise HarnessError(f"Task {task['proposal_key']} priority must be an integer")
    if (
        not isinstance(task["dependencies"], list)
        or not all(isinstance(value, str) and value for value in task["dependencies"])
        or len(task["dependencies"]) != len(set(task["dependencies"]))
    ):
        raise HarnessError(f"Task {task['proposal_key']} dependencies must be unique")
    if not isinstance(task["gap_evidence"], list) or not task["gap_evidence"]:
        raise HarnessError(f"Task {task['proposal_key']} needs gap evidence")
    for item in task["gap_evidence"]:
        if (
            not isinstance(item, dict)
            or set(item) != {"location", "observation"}
            or not isinstance(item.get("location"), str)
            or not item["location"]
            or not isinstance(item.get("observation"), str)
            or not item["observation"]
        ):
            raise HarnessError(f"Task {task['proposal_key']} has invalid gap evidence")
    if (
        not isinstance(task["acceptance_criteria"], list)
        or not task["acceptance_criteria"]
    ):
        raise HarnessError(f"Task {task['proposal_key']} needs acceptance criteria")
    criterion_ids: list[str] = []
    allowed_verification = {
        "unit",
        "integration",
        "command",
        "build",
        "e2e",
        "browser",
        "visual",
        "manual-review",
    }
    for item in task["acceptance_criteria"]:
        verification_kinds = (
            item.get("verification") if isinstance(item, dict) else None
        )
        if (
            not isinstance(item, dict)
            or set(item) != {"id", "description", "verification"}
            or not isinstance(item.get("id"), str)
            or not item["id"]
            or not isinstance(item.get("description"), str)
            or not item["description"]
            or not isinstance(verification_kinds, list)
            or not verification_kinds
            or not all(value in allowed_verification for value in verification_kinds)
            or len(verification_kinds) != len(set(verification_kinds))
        ):
            raise HarnessError(
                f"Task {task['proposal_key']} has invalid acceptance criteria"
            )
        criterion_ids.append(item["id"])
    if len(criterion_ids) != len(set(criterion_ids)):
        raise HarnessError(f"Task {task['proposal_key']} criterion IDs must be unique")
    if "type" in task and task["type"] not in {
        "user-facing",
        "backend",
        "infrastructure",
        "documentation",
    }:
        raise HarnessError(f"Task {task['proposal_key']} type is invalid")
    verification = task["verification"]
    if not isinstance(verification, dict) or set(verification) != {
        "profiles",
        "requires_browser",
    }:
        raise HarnessError(
            f"Task {task['proposal_key']} verification has unknown fields"
        )
    profiles = verification.get("profiles") if isinstance(verification, dict) else None
    if (
        not isinstance(profiles, list)
        or not profiles
        or not all(isinstance(profile, str) and profile for profile in profiles)
        or len(profiles) != len(set(profiles))
    ):
        raise HarnessError(f"Task {task['proposal_key']} needs verification profiles")
    if profile_names is not None:
        unknown = sorted(set(profiles) - profile_names)
        if unknown:
            raise HarnessError(
                f"Task {task['proposal_key']} references unknown profiles: {', '.join(unknown)}"
            )
    if not isinstance(verification.get("requires_browser"), bool):
        raise HarnessError(
            f"Task {task['proposal_key']} requires_browser must be boolean"
        )
    browser_criteria = [
        item
        for item in task["acceptance_criteria"]
        if set(item["verification"]) & {"browser", "visual", "e2e"}
    ]
    if verification["requires_browser"] != bool(browser_criteria):
        raise HarnessError(
            f"Task {task['proposal_key']} browser requirement and criteria disagree"
        )
    scope = task["scope"]
    if not isinstance(scope, dict):
        raise HarnessError(f"Task {task['proposal_key']} scope must be an object")
    _validate_path_guidance(scope, "recommended_paths")
    _validate_path_guidance(scope, "forbidden_paths")
    if set(scope) != {"recommended_paths", "forbidden_paths"}:
        raise HarnessError(f"Task {task['proposal_key']} scope has unknown fields")


def _assert_acyclic(tasks: list[dict[str, Any]]) -> None:
    graph = {task["proposal_key"]: task["dependencies"] for task in tasks}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(key: str) -> None:
        if key in visiting:
            raise HarnessError(f"Proposal dependency cycle includes {key}")
        if key in visited:
            return
        visiting.add(key)
        for dependency in graph[key]:
            visit(dependency)
        visiting.remove(key)
        visited.add(key)

    for key in graph:
        visit(key)


def validate_proposal(proposal: dict[str, Any], config: dict[str, Any]) -> str:
    validate_config(config)
    if set(proposal) != {"schema_version", "title", "tasks"}:
        raise HarnessError("Proposal allows only schema_version, title, and tasks")
    if (
        proposal.get("schema_version") != 2
        or not isinstance(proposal.get("title"), str)
        or not proposal["title"].strip()
    ):
        raise HarnessError("Proposal schema_version must be 2 and title is required")
    tasks = proposal.get("tasks")
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= 100:
        raise HarnessError("Proposal must contain between 1 and 100 tasks")
    keys = [task.get("proposal_key") for task in tasks if isinstance(task, dict)]
    if len(keys) != len(tasks) or len(keys) != len(set(keys)):
        raise HarnessError("Proposal task keys must be present and unique")
    key_set = set(keys)
    for task in tasks:
        validate_task(task, set(config["verification_profiles"]))
        unknown = sorted(set(task["dependencies"]) - key_set)
        if unknown:
            raise HarnessError(
                f"Task {task['proposal_key']} has unknown dependencies: {', '.join(unknown)}"
            )
        if task["proposal_key"] in task["dependencies"]:
            raise HarnessError(f"Task {task['proposal_key']} cannot depend on itself")
    _assert_acyclic(tasks)
    return sha256_json(proposal)


def render_config_body(config: dict[str, Any]) -> str:
    validate_config(config)
    payload = {
        "schema_version": 1,
        "config_sha256": sha256_json(config),
        "configuration": config,
    }
    return (
        "# Webapp Harness configuration\n\nGitHub Issues are the durable lifecycle authority for this repository.\n\n"
        + marker("config", payload)
    )


def parse_config_body(body: str | None) -> dict[str, Any]:
    payload = extract_marker(body, "config")
    config = payload.get("configuration")
    if payload.get("schema_version") != 1 or not isinstance(config, dict):
        raise HarnessError("Invalid harness configuration marker")
    validate_config(config)
    if payload.get("config_sha256") != sha256_json(config):
        raise HarnessError("Harness configuration marker digest is invalid")
    return config


def _path_lines(entries: list[dict[str, str]]) -> str:
    if not entries:
        return "- None"
    return "\n".join(f"- `{entry['path']}` — {entry['reason']}" for entry in entries)


def render_task_body(task: dict[str, Any], proposal_sha256: str) -> str:
    validate_task(task)
    payload = {
        **task,
        "proposal_sha256": proposal_sha256,
        "task_sha256": sha256_json(task),
    }
    evidence = "\n".join(
        f"- `{item['location']}` — {item['observation']}"
        for item in task["gap_evidence"]
    )
    criteria = "\n".join(
        f"- **{item['id']}** {item['description']} ({', '.join(item['verification'])})"
        for item in task["acceptance_criteria"]
    )
    return (
        f"## Description\n\n{task['description']}\n\n"
        f"## Gap evidence\n\n{evidence}\n\n"
        f"## Acceptance criteria\n\n{criteria}\n\n"
        f"## Recommended starting paths\n\n{_path_lines(task['scope']['recommended_paths'])}\n\n"
        f"## Forbidden delegated-worker paths\n\n{_path_lines(task['scope']['forbidden_paths'])}\n\n"
        "The main agent may record an exact task-level executive override when the accepted outcome requires it.\n\n"
        + marker("task", payload)
    )


def parse_task_body(body: str | None) -> dict[str, Any]:
    payload = extract_marker(body, "task")
    task = dict(payload)
    supplied = task.pop("task_sha256", None)
    task.pop("proposal_sha256", None)
    validate_task(task)
    if supplied != sha256_json(task):
        raise HarnessError("Harness task marker digest is invalid")
    return payload


def render_proposal_body(proposal: dict[str, Any], digest: str) -> str:
    payload = {
        "schema_version": 1,
        "proposal_sha256": digest,
        "title": proposal["title"],
        "task_keys": [task["proposal_key"] for task in proposal["tasks"]],
    }
    lines = "\n".join(
        f"- {task['proposal_key']}: {task['title']}"
        for task in sorted(
            proposal["tasks"], key=lambda item: (item["priority"], item["proposal_key"])
        )
    )
    return f"Approved proposal SHA-256: `{digest}`\n\n## Tasks\n\n{lines}\n\n" + marker(
        "proposal", payload
    )


def build_event(
    issue_number: int,
    event: str,
    payload: dict[str, Any],
    existing: list[dict[str, Any]],
    *,
    run_id: str | None = None,
    event_id: str | None = None,
    recorded_at: str | None = None,
) -> dict[str, Any]:
    validate_event_chain(existing, issue_number)
    if run_id is not None:
        validate_run_id(run_id)
    if event_id is not None:
        try:
            uuid.UUID(event_id)
        except ValueError as exc:
            raise HarnessError(f"Invalid event_id: {event_id}") from exc
    if event_id and any(item["event_id"] == event_id for item in existing):
        prior = next(item for item in existing if item["event_id"] == event_id)
        if (
            prior.get("event") != event
            or prior.get("run_id") != run_id
            or prior.get("payload") != payload
        ):
            raise HarnessError(
                f"Event id {event_id} was already used for different data"
            )
        return prior
    value: dict[str, Any] = {
        "schema_version": 1,
        "event_id": event_id or str(uuid.uuid4()),
        "run_id": run_id,
        "issue_number": issue_number,
        "sequence": len(existing) + 1,
        "event": event,
        "recorded_at": recorded_at or utc_now(),
        "actor": "main_agent",
        "previous_event_sha256": existing[-1]["event_sha256"] if existing else None,
        "payload": payload,
    }
    value["event_sha256"] = sha256_json(value)
    return value


def validate_event_chain(events: list[dict[str, Any]], issue_number: int) -> None:
    event_fields = {
        "schema_version",
        "event_id",
        "run_id",
        "issue_number",
        "sequence",
        "event",
        "recorded_at",
        "actor",
        "previous_event_sha256",
        "payload",
        "event_sha256",
    }
    allowed_events = {
        "status_changed",
        "implementation_result",
        "verification_result",
        "review_result",
        "browser_result",
        "scope_override",
        "evidence_uploaded",
        "completed",
        "blocked",
    }
    seen: set[str] = set()
    previous: str | None = None
    for expected_sequence, event in enumerate(events, start=1):
        if (
            set(event) != event_fields
            or event.get("schema_version") != 1
            or event.get("event") not in allowed_events
            or event.get("actor") != "main_agent"
            or not isinstance(event.get("payload"), dict)
            or not isinstance(event.get("recorded_at"), str)
        ):
            raise HarnessError(
                f"Invalid event contract at sequence {expected_sequence}"
            )
        try:
            uuid.UUID(str(event.get("event_id")))
            datetime.fromisoformat(event["recorded_at"])
        except ValueError as exc:
            raise HarnessError(
                f"Invalid event identity or timestamp at sequence {expected_sequence}"
            ) from exc
        if event.get("run_id") is not None:
            validate_run_id(event["run_id"])
        if event.get("issue_number") != issue_number:
            raise HarnessError("Event issue number does not match task issue")
        if event.get("sequence") != expected_sequence:
            raise HarnessError(f"Event sequence gap at {expected_sequence}")
        if event.get("event_id") in seen:
            raise HarnessError(f"Duplicate event id: {event.get('event_id')}")
        if event.get("previous_event_sha256") != previous:
            raise HarnessError(
                f"Broken event hash chain at sequence {expected_sequence}"
            )
        supplied = event.get("event_sha256")
        unsigned = dict(event)
        unsigned.pop("event_sha256", None)
        if supplied != sha256_json(unsigned):
            raise HarnessError(f"Invalid event digest at sequence {expected_sequence}")
        seen.add(event["event_id"])
        previous = supplied


def render_event_comment(event: dict[str, Any]) -> str:
    summary = event["event"].replace("_", " ").title()
    return f"### Harness event {event['sequence']}: {summary}\n\n" + marker(
        "event", event
    )


def events_from_comments(
    comments: Iterable[dict[str, Any]], issue_number: int
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for comment in comments:
        body = comment.get("body") if isinstance(comment, dict) else None
        if "webapp-harness:event" not in (body or ""):
            continue
        events.append(extract_marker(body, "event"))
    events.sort(key=lambda item: item.get("sequence", 0))
    validate_event_chain(events, issue_number)
    return events


def status_from_labels(labels: Iterable[Any]) -> str:
    names = {item.get("name") if isinstance(item, dict) else item for item in labels}
    statuses = sorted(
        name.removeprefix(STATUS_LABEL_PREFIX)
        for name in names
        if isinstance(name, str) and name.startswith(STATUS_LABEL_PREFIX)
    )
    if len(statuses) != 1:
        raise HarnessError(
            f"Expected exactly one harness status label; found {statuses}"
        )
    return statuses[0]


def validate_transition(source: str, target: str) -> None:
    if target not in ALLOWED_TRANSITIONS.get(source, set()):
        raise HarnessError(f"Invalid lifecycle transition: {source} -> {target}")


def status_from_events(events: list[dict[str, Any]]) -> str:
    status = "proposed"
    for event in events:
        if event["event"] not in {"status_changed", "blocked", "completed"}:
            continue
        payload = event["payload"]
        source = payload.get("from", status)
        target = payload.get("to")
        if event["event"] == "completed" and target is None:
            target = "completed"
        if event["event"] == "blocked" and target is None:
            target = "blocked"
        if source != status:
            raise HarnessError(
                f"Lifecycle event {event['sequence']} expected source {status}, found {source}"
            )
        if not isinstance(target, str):
            raise HarnessError(f"Lifecycle event {event['sequence']} has no target")
        if not payload.get("legacy"):
            validate_transition(status, target)
        status = target
    return status


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise HarnessError(f"{field} must be an array of strings")
    return value


def validate_result_payload(
    event_name: str,
    result: dict[str, Any],
    task: dict[str, Any],
    events: list[dict[str, Any]],
    run_id: str,
) -> None:
    if not isinstance(result, dict):
        raise HarnessError("Result must be an object")
    if event_name == "implementation_result":
        required = {
            "issue_number",
            "run_id",
            "summary",
            "files_changed",
            "tests_changed",
            "browser_flows",
            "risks",
        }
        if set(result) != required or not isinstance(result.get("summary"), str):
            raise HarnessError("Implementation result does not match its schema")
        if not result["summary"].strip():
            raise HarnessError("Implementation result summary cannot be empty")
        files = _string_list(result["files_changed"], "files_changed")
        tests = _string_list(result["tests_changed"], "tests_changed")
        _string_list(result["browser_flows"], "browser_flows")
        _string_list(result["risks"], "risks")
        if len(files) != len(set(files)) or len(tests) != len(set(tests)):
            raise HarnessError("Implementation file lists must be unique")
        for path in [*files, *tests]:
            _validate_repository_path(path, "implementation result path")
        forbidden = [entry["path"] for entry in task["scope"]["forbidden_paths"]]
        overrides = [
            event["payload"]
            for event in events
            if event["event"] == "scope_override" and event.get("run_id") == run_id
        ]
        for path in files:
            if not any(path_matches_rule(path, rule) for rule in forbidden):
                continue
            authorized = any(
                any(path_matches_rule(path, rule) for rule in override.get("paths", []))
                and bool(
                    set(override.get("operations", []))
                    & {"modify", "delete", "rename", "generate"}
                )
                for override in overrides
            )
            if not authorized:
                raise HarnessError(
                    f"Implementation changed forbidden path without a main-agent override: {path}"
                )
        return
    if event_name == "verification_result":
        if set(result) != {
            "issue_number",
            "run_id",
            "status",
            "failure_class",
            "checks",
        } or not isinstance(result.get("checks"), list):
            raise HarnessError("Verification result does not match its schema")
        status = result.get("status")
        failure_class = result.get("failure_class")
        if status not in {"PASSED", "FAILED", "INCOMPLETE"}:
            raise HarnessError("Verification result status is invalid")
        if not all(isinstance(check, dict) for check in result["checks"]):
            raise HarnessError("Verification checks must be objects")
        if status == "PASSED" and (failure_class is not None or not result["checks"]):
            raise HarnessError("Passing verification needs checks and no failure class")
        if status != "PASSED" and failure_class not in {
            "product",
            "fixture",
            "profile",
            "tooling",
            "environment",
            "scope",
        }:
            raise HarnessError("Non-passing verification needs a failure class")
        return
    if event_name == "review_result":
        if set(result) != {
            "issue_number",
            "run_id",
            "verdict",
            "findings",
        } or not isinstance(result.get("findings"), list):
            raise HarnessError("Review result does not match its schema")
        if not all(isinstance(finding, dict) for finding in result["findings"]):
            raise HarnessError("Review findings must be objects")
        if result.get("verdict") not in {"APPROVED", "CHANGES_REQUIRED", "INCOMPLETE"}:
            raise HarnessError("Review verdict is invalid")
        return
    if event_name == "browser_result":
        required = {
            "issue_number",
            "run_id",
            "status",
            "failure_class",
            "blocker",
            "tooling",
            "preflight",
            "criteria",
        }
        if set(result) != required or not isinstance(result.get("criteria"), list):
            raise HarnessError("Browser result does not match its schema")
        status = result.get("status")
        failure_class = result.get("failure_class")
        preflight = result.get("preflight")
        if status not in {"PASSED", "FAILED", "INCOMPLETE"}:
            raise HarnessError("Browser result status is invalid")
        if result.get("tooling") not in {
            "browser_use",
            "chrome_control",
            "computer_use",
            "playwright",
            "other",
        }:
            raise HarnessError("Browser tooling is invalid")
        if result.get("blocker") is not None and not isinstance(
            result.get("blocker"), str
        ):
            raise HarnessError("Browser blocker must be a string or null")
        if (
            not isinstance(preflight, dict)
            or set(preflight)
            != {
                "health",
                "fixtures",
                "profiles",
                "tooling",
            }
            or not all(isinstance(value, bool) for value in preflight.values())
        ):
            raise HarnessError("Browser preflight is invalid")
        planned = {
            criterion["id"]
            for criterion in task["acceptance_criteria"]
            if set(criterion["verification"]) & {"browser", "visual", "e2e"}
        }
        criterion_fields = {
            "id",
            "status",
            "steps",
            "observed",
            "expected",
            "evidence",
        }
        criteria_valid = all(
            isinstance(criterion, dict)
            and set(criterion) == criterion_fields
            and isinstance(criterion.get("id"), str)
            and bool(criterion["id"])
            and criterion.get("status") in {"PASSED", "FAILED", "INCOMPLETE"}
            and isinstance(criterion.get("steps"), list)
            and all(isinstance(step, str) and step for step in criterion["steps"])
            and isinstance(criterion.get("observed"), str)
            and isinstance(criterion.get("expected"), str)
            and isinstance(criterion.get("evidence"), list)
            and all(
                isinstance(evidence, str) and evidence
                for evidence in criterion["evidence"]
            )
            for criterion in result["criteria"]
        )
        if not criteria_valid:
            raise HarnessError("Browser result criteria do not match their schema")
        returned_ids = [criterion["id"] for criterion in result["criteria"]]
        if set(returned_ids) != planned or len(returned_ids) != len(set(returned_ids)):
            raise HarnessError(
                "Browser result criterion IDs do not match the task plan"
            )
        if status == "PASSED":
            if (
                failure_class is not None
                or result.get("blocker") is not None
                or result.get("tooling") == "other"
                or not all(preflight.values())
                or not result["criteria"]
                or any(
                    criterion.get("status") != "PASSED" or not criterion.get("evidence")
                    for criterion in result["criteria"]
                )
            ):
                raise HarnessError(
                    "Passing browser result is missing required direct evidence"
                )
        elif failure_class not in {
            "product",
            "fixture",
            "profile",
            "tooling",
            "environment",
            "scope",
        }:
            raise HarnessError("Non-passing browser result needs a failure class")
        return
    if event_name == "evidence_uploaded":
        required = {
            "asset_url",
            "asset_name",
            "sha256",
            "size",
            "file_count",
            "release_id",
        }
        if (
            set(result) != required
            or not isinstance(result.get("asset_url"), str)
            or not re.fullmatch(r"[a-f0-9]{64}", str(result.get("sha256")))
            or not isinstance(result.get("size"), int)
            or not isinstance(result.get("file_count"), int)
        ):
            raise HarnessError("Evidence upload result is invalid")
        return
    raise HarnessError(f"Unsupported result event: {event_name}")


@dataclass
class CommandResult:
    stdout: str
    stderr: str
    returncode: int


class GhClient:
    def __init__(self, repo: str | None = None, runner: Any | None = None):
        self.repo = repo
        self._runner = runner or self._run

    @staticmethod
    def _run(args: list[str], input_text: str | None = None) -> CommandResult:
        proc = subprocess.run(
            args, text=True, input=input_text, capture_output=True, check=False
        )
        return CommandResult(proc.stdout, proc.stderr, proc.returncode)

    def _call(self, args: list[str], input_text: str | None = None) -> str:
        result = self._runner(args, input_text)
        if result.returncode:
            raise HarnessError(
                result.stderr.strip() or f"Command failed: {' '.join(args)}"
            )
        return result.stdout

    def resolve_repo(self) -> dict[str, Any]:
        args = ["gh", "repo", "view"]
        if self.repo:
            args.append(self.repo)
        args.extend(
            [
                "--json",
                "nameWithOwner,url,hasIssuesEnabled,viewerPermission,defaultBranchRef",
            ]
        )
        value = json.loads(self._call(args))
        self.repo = value["nameWithOwner"]
        return value

    def api(
        self, method: str, endpoint: str, payload: dict[str, Any] | None = None
    ) -> Any:
        args = [
            "gh",
            "api",
            "--method",
            method,
            "-H",
            "Accept:application/vnd.github+json",
            "-H",
            f"X-GitHub-Api-Version:{API_VERSION}",
            endpoint,
        ]
        input_text = None
        if payload is not None:
            args.extend(["--input", "-"])
            input_text = json.dumps(payload)
        output = self._call(args, input_text)
        return json.loads(output) if output.strip() else None

    def api_paginated(self, endpoint: str) -> list[Any]:
        args = [
            "gh",
            "api",
            "--paginate",
            "--slurp",
            "-H",
            "Accept:application/vnd.github+json",
            "-H",
            f"X-GitHub-Api-Version:{API_VERSION}",
            endpoint,
        ]
        pages = json.loads(self._call(args))
        return [item for page in pages for item in page]

    def ensure_label(self, name: str, color: str, description: str) -> None:
        assert self.repo
        endpoint = f"repos/{self.repo}/labels/{name.replace(':', '%3A')}"
        try:
            self.api("GET", endpoint)
        except HarnessError:
            self.api(
                "POST",
                f"repos/{self.repo}/labels",
                {"name": name, "color": color, "description": description},
            )

    def list_issues(
        self, *, state: str = "all", label: str | None = None
    ) -> list[dict[str, Any]]:
        assert self.repo
        endpoint = f"repos/{self.repo}/issues?state={state}&per_page=100"
        if label:
            endpoint += f"&labels={label.replace(':', '%3A')}"
        return [
            item for item in self.api_paginated(endpoint) if "pull_request" not in item
        ]

    def create_issue(self, title: str, body: str, labels: list[str]) -> dict[str, Any]:
        assert self.repo
        return self.api(
            "POST",
            f"repos/{self.repo}/issues",
            {"title": title, "body": body, "labels": labels},
        )

    def update_issue(self, number: int, payload: dict[str, Any]) -> dict[str, Any]:
        assert self.repo
        return self.api("PATCH", f"repos/{self.repo}/issues/{number}", payload)

    def get_issue(self, number: int) -> dict[str, Any]:
        assert self.repo
        return self.api("GET", f"repos/{self.repo}/issues/{number}")

    def comments(self, number: int) -> list[dict[str, Any]]:
        assert self.repo
        return self.api_paginated(
            f"repos/{self.repo}/issues/{number}/comments?per_page=100"
        )

    def comment(self, number: int, body: str) -> dict[str, Any]:
        assert self.repo
        return self.api(
            "POST", f"repos/{self.repo}/issues/{number}/comments", {"body": body}
        )

    def add_sub_issue(self, parent_number: int, child_id: int) -> None:
        assert self.repo
        self.api(
            "POST",
            f"repos/{self.repo}/issues/{parent_number}/sub_issues",
            {"sub_issue_id": child_id},
        )

    def add_dependency(self, issue_number: int, blocking_issue_id: int) -> None:
        assert self.repo
        self.api(
            "POST",
            f"repos/{self.repo}/issues/{issue_number}/dependencies/blocked_by",
            {"issue_id": blocking_issue_id},
        )

    def dependencies(self, issue_number: int) -> list[dict[str, Any]]:
        assert self.repo
        return self.api_paginated(
            f"repos/{self.repo}/issues/{issue_number}/dependencies/blocked_by?per_page=100"
        )

    def release_assets(self, release_id: int) -> list[dict[str, Any]]:
        assert self.repo
        return self.api_paginated(
            f"repos/{self.repo}/releases/{release_id}/assets?per_page=100"
        )


def marker_lookup(
    issues: Iterable[dict[str, Any]], kind: str, field: str, value: Any
) -> dict[str, Any] | None:
    found: list[dict[str, Any]] = []
    for issue in issues:
        body = issue.get("body") or ""
        if f"webapp-harness:{kind}" not in body:
            continue
        try:
            payload = extract_marker(body, kind)
        except HarnessError:
            continue
        if payload.get(field) == value:
            found.append(issue)
    if len(found) > 1:
        raise HarnessError(f"Multiple {kind} issues match {field}={value}")
    return found[0] if found else None


class GitHubHarness:
    def __init__(self, client: GhClient):
        self.client = client
        self.repo_info = client.resolve_repo()
        if not self.repo_info.get("hasIssuesEnabled"):
            raise HarnessError("GitHub Issues are disabled for this repository")

    def initialization_plan(self, config: dict[str, Any]) -> dict[str, Any]:
        validate_config(config)
        controls = self.client.list_issues(state="all", label="harness:control")
        if len(controls) > 1:
            raise HarnessError("Multiple harness control issues exist")
        if controls:
            existing = parse_config_body(controls[0].get("body"))
            if controls[0].get("state") != "open":
                operation = "reopen_requires_confirmation"
            else:
                operation = (
                    "reuse"
                    if sha256_json(existing) == sha256_json(config)
                    else "update_requires_confirmation"
                )
        else:
            operation = "create"
        return {
            "repository": self.repo_info["nameWithOwner"],
            "repository_url": self.repo_info["url"],
            "viewer_permission": self.repo_info.get("viewerPermission"),
            "labels_to_ensure": sorted(LABELS),
            "control_issue": operation,
            "config_sha256": sha256_json(config),
            "writes_repository_files": False,
        }

    def initialize(
        self, config: dict[str, Any], *, allow_config_update: bool = False
    ) -> dict[str, Any]:
        plan = self.initialization_plan(config)
        for name, (color, description) in LABELS.items():
            self.client.ensure_label(name, color, description)
        controls = self.client.list_issues(state="all", label="harness:control")
        if len(controls) > 1:
            raise HarnessError("Multiple harness control issues exist")
        body = render_config_body(config)
        if controls:
            control = controls[0]
            existing = parse_config_body(control.get("body"))
            differs = sha256_json(existing) != sha256_json(config)
            closed = control.get("state") != "open"
            if differs or closed:
                if not allow_config_update:
                    raise HarnessError(
                        "Control issue differs or is closed; repair requires --update-existing"
                    )
                control = self.client.update_issue(
                    control["number"], {"body": body, "state": "open"}
                )
        else:
            control = self.client.create_issue(
                "[Harness] Configuration", body, ["harness:control"]
            )
        return {
            **plan,
            "control_issue_number": control["number"],
            "control_issue_url": control["html_url"],
        }

    def config(self) -> tuple[dict[str, Any], dict[str, Any]]:
        controls = self.client.list_issues(state="open", label="harness:control")
        if len(controls) != 1:
            raise HarnessError(
                f"Expected exactly one open harness control issue; found {len(controls)}"
            )
        value = parse_config_body(controls[0].get("body"))
        return controls[0], value

    def proposal_plan(self, proposal: dict[str, Any]) -> dict[str, Any]:
        _, config = self.config()
        digest = validate_proposal(proposal, config)
        existing = self.client.list_issues(state="all", label="harness:task")
        collisions = []
        for task in proposal["tasks"]:
            match = marker_lookup(
                existing, "task", "proposal_key", task["proposal_key"]
            )
            if match:
                collisions.append(
                    {
                        "proposal_key": task["proposal_key"],
                        "issue_number": match["number"],
                    }
                )
        return {
            "repository": self.repo_info["nameWithOwner"],
            "proposal_sha256": digest,
            "task_count": len(proposal["tasks"]),
            "tasks": [
                {
                    "proposal_key": task["proposal_key"],
                    "title": task["title"],
                    "priority": task["priority"],
                    "dependencies": task["dependencies"],
                    "recommended_paths": task["scope"]["recommended_paths"],
                    "forbidden_paths": task["scope"]["forbidden_paths"],
                }
                for task in proposal["tasks"]
            ],
            "existing_task_collisions": collisions,
        }

    def apply_proposal(
        self, proposal: dict[str, Any], expected_sha256: str
    ) -> dict[str, Any]:
        plan = self.proposal_plan(proposal)
        if plan["proposal_sha256"] != expected_sha256:
            raise HarnessError("Proposal SHA-256 does not match the confirmed preview")
        existing_batches = self.client.list_issues(state="all", label="harness:backlog")
        parent = marker_lookup(
            existing_batches, "proposal", "proposal_sha256", expected_sha256
        )
        if not parent:
            parent = self.client.create_issue(
                f"[Harness Backlog] {proposal['title']}",
                render_proposal_body(proposal, expected_sha256),
                ["harness:backlog"],
            )
        existing_tasks = self.client.list_issues(state="all", label="harness:task")
        created: dict[str, dict[str, Any]] = {}
        for task in sorted(
            proposal["tasks"], key=lambda item: (item["priority"], item["proposal_key"])
        ):
            issue = marker_lookup(
                existing_tasks, "task", "proposal_key", task["proposal_key"]
            )
            if issue:
                payload = parse_task_body(issue.get("body"))
                if payload.get("proposal_sha256") != expected_sha256:
                    raise HarnessError(f"Task key collision for {task['proposal_key']}")
            else:
                issue = self.client.create_issue(
                    f"[Harness] {task['title']}",
                    render_task_body(task, expected_sha256),
                    ["harness:task", "harness:status:proposed"],
                )
                existing_tasks.append(issue)
            created[task["proposal_key"]] = issue
            try:
                self.client.add_sub_issue(parent["number"], issue["id"])
            except HarnessError as exc:
                if "already" not in str(exc).lower() and "422" not in str(exc):
                    raise
        for task in proposal["tasks"]:
            issue = created[task["proposal_key"]]
            for dependency in task["dependencies"]:
                blocker = created[dependency]
                try:
                    self.client.add_dependency(issue["number"], blocker["id"])
                except HarnessError as exc:
                    if "already" not in str(exc).lower() and "422" not in str(exc):
                        raise
        return {
            "proposal_sha256": expected_sha256,
            "parent_issue": parent["html_url"],
            "tasks": {key: value["html_url"] for key, value in created.items()},
        }

    def issue_events(self, issue_number: int) -> list[dict[str, Any]]:
        return events_from_comments(self.client.comments(issue_number), issue_number)

    @staticmethod
    def _latest_run_event(
        events: list[dict[str, Any]], event_name: str, run_id: str
    ) -> dict[str, Any] | None:
        matches = [
            event
            for event in events
            if event["event"] == event_name and event.get("run_id") == run_id
        ]
        return matches[-1] if matches else None

    def _validate_evidence_asset(self, payload: dict[str, Any]) -> None:
        release_id = payload.get("release_id")
        if not isinstance(release_id, int) or isinstance(release_id, bool):
            raise HarnessError("Evidence release_id must be an integer")
        matches = [
            asset
            for asset in self.client.release_assets(release_id)
            if asset.get("name") == payload.get("asset_name")
        ]
        if len(matches) != 1:
            raise HarnessError(
                "Evidence release must contain exactly one matching immutable asset"
            )
        asset = matches[0]
        if asset.get("size") != payload.get("size"):
            raise HarnessError("Evidence release asset size differs from its event")
        digest = asset.get("digest")
        if digest is not None and digest != f"sha256:{payload.get('sha256')}":
            raise HarnessError("Evidence release asset digest differs from its event")

    def _validate_task_event_payloads(
        self, issue_number: int, task: dict[str, Any], events: list[dict[str, Any]]
    ) -> None:
        result_events = {
            "implementation_result",
            "verification_result",
            "review_result",
            "browser_result",
            "evidence_uploaded",
        }
        forbidden = [entry["path"] for entry in task["scope"]["forbidden_paths"]]
        for index, event in enumerate(events):
            event_name = event["event"]
            run_id = event.get("run_id")
            if event_name in result_events:
                if run_id is None:
                    raise HarnessError(
                        f"Task #{issue_number} result event is missing a run_id"
                    )
                validate_result_payload(
                    event_name, event["payload"], task, events[:index], run_id
                )
            if event_name == "scope_override":
                payload = event["payload"]
                if (
                    set(payload)
                    != {
                        "paths",
                        "operations",
                        "reason",
                        "authorized_by",
                        "applies_to",
                    }
                    or payload.get("authorized_by") != "main_agent"
                ):
                    raise HarnessError(
                        "Scope override event does not match its contract"
                    )
                paths = _string_list(payload.get("paths"), "scope override paths")
                operations = _string_list(
                    payload.get("operations"), "scope override operations"
                )
                if (
                    not paths
                    or not operations
                    or not isinstance(payload.get("reason"), str)
                    or not payload["reason"].strip()
                    or payload.get("applies_to") != "current_run"
                    or not set(operations) <= {"modify", "delete", "rename", "generate"}
                ):
                    raise HarnessError(
                        "Scope override event does not match its contract"
                    )
                for path in paths:
                    _validate_repository_path(path, "scope override path")
                    if path.endswith("/") or any(
                        token in path for token in ("*", "?", "[")
                    ):
                        raise HarnessError("Scope override path is not an exact file")
                    if not any(path_matches_rule(path, rule) for rule in forbidden):
                        raise HarnessError(
                            "Scope override path is not task-level forbidden"
                        )
            if event_name == "evidence_uploaded":
                preceding_browser = self._latest_run_event(
                    events[:index], "browser_result", str(run_id)
                )
                if (
                    not preceding_browser
                    or preceding_browser["payload"].get("status") != "PASSED"
                ):
                    raise HarnessError(
                        "Evidence event does not follow a passing browser result"
                    )
                self._validate_evidence_asset(event["payload"])

    def retry_decision(
        self, issue_number: int, phase: str, run_id: str
    ) -> dict[str, Any]:
        if phase not in {"verification", "review", "browser"}:
            raise HarnessError(f"Unknown retry phase: {phase}")
        _control, config = self.config()
        issue = self.client.get_issue(issue_number)
        task = parse_task_body(issue.get("body"))
        events = self.issue_events(issue_number)
        self._validate_task_event_payloads(issue_number, task, events)
        event_name = {
            "verification": "verification_result",
            "review": "review_result",
            "browser": "browser_result",
        }[phase]
        results = [
            event["payload"]
            for event in events
            if event["event"] == event_name and event.get("run_id") == run_id
        ]
        if not results:
            raise HarnessError(f"No {phase} result exists for run {run_id}")
        latest = results[-1]
        if phase == "review":
            if latest.get("verdict") == "APPROVED":
                return {"decision": "advance", "phase": phase, "counted_failures": 0}
            if latest.get("verdict") == "INCOMPLETE":
                return {
                    "decision": "block",
                    "phase": phase,
                    "failure_class": "environment",
                    "counted_failures": 0,
                }
            failures = sum(
                result.get("verdict") == "CHANGES_REQUIRED" for result in results
            )
            failure_class = "product"
        else:
            if latest.get("status") == "PASSED":
                return {"decision": "advance", "phase": phase, "counted_failures": 0}
            failure_class = latest.get("failure_class")
            if failure_class != "product":
                return {
                    "decision": "block",
                    "phase": phase,
                    "failure_class": failure_class,
                    "counted_failures": 0,
                }
            failures = sum(
                result.get("status") != "PASSED"
                and result.get("failure_class") == "product"
                for result in results
            )
        limit = config["retry_limits"][phase]
        return {
            "decision": "repair" if failures < limit else "block",
            "phase": phase,
            "failure_class": failure_class,
            "counted_failures": failures,
            "retry_limit": limit,
        }

    def _validate_transition_gates(
        self,
        issue: dict[str, Any],
        task: dict[str, Any],
        events: list[dict[str, Any]],
        source: str,
        target: str,
        reason: str,
        run_id: str | None,
    ) -> None:
        if source in ACTIVE_STATES or target in ACTIVE_STATES or target == "completed":
            if not run_id:
                raise HarnessError(f"Transition {source} -> {target} requires --run-id")
        else:
            return
        if source == "ready" and target == "implementing":
            return
        assert run_id is not None
        active_events = [
            event
            for event in events
            if event["event"] == "status_changed"
            and event["payload"].get("to") in ACTIVE_STATES
        ]
        if active_events and active_events[-1].get("run_id") != run_id:
            raise HarnessError("Transition run_id does not match the active run")
        latest_implementation = self._latest_run_event(
            events, "implementation_result", run_id
        )
        latest_verification = self._latest_run_event(
            events, "verification_result", run_id
        )
        latest_review = self._latest_run_event(events, "review_result", run_id)
        latest_browser = self._latest_run_event(events, "browser_result", run_id)
        latest_evidence = self._latest_run_event(events, "evidence_uploaded", run_id)
        if (
            source == "implementing"
            and target == "verifying"
            and not latest_implementation
        ):
            raise HarnessError(
                "Cannot verify before recording an implementation result"
            )
        if source == "implementing" and target == "verifying":
            entered_implementation = active_events[-1] if active_events else None
            if (
                entered_implementation
                and latest_implementation
                and latest_implementation["sequence"]
                < entered_implementation["sequence"]
            ):
                raise HarnessError(
                    "Implementation result is stale relative to the current implementation phase"
                )
        if source == "verifying" and target == "reviewing":
            if (
                not latest_verification
                or latest_verification["payload"].get("status") != "PASSED"
            ):
                raise HarnessError("Cannot review before a passing verification result")
            if not latest_implementation:
                raise HarnessError("Cannot review before an implementation result")
            if latest_verification["sequence"] < latest_implementation["sequence"]:
                raise HarnessError(
                    "Verification result is stale relative to implementation"
                )
        if source == "reviewing" and target in {"browser_validating", "completed"}:
            if (
                not latest_review
                or latest_review["payload"].get("verdict") != "APPROVED"
            ):
                raise HarnessError("Cannot advance before an approved review result")
            if (
                not latest_implementation
                or not latest_verification
                or latest_verification["payload"].get("status") != "PASSED"
            ):
                raise HarnessError(
                    "Cannot advance without current implementation and verification results"
                )
            if latest_verification["sequence"] < latest_implementation["sequence"]:
                raise HarnessError(
                    "Verification result is stale relative to implementation"
                )
            if latest_review["sequence"] < latest_verification["sequence"]:
                raise HarnessError("Review result is stale relative to verification")
            requires_browser = task["verification"]["requires_browser"]
            if target == "browser_validating" and not requires_browser:
                raise HarnessError("Task does not require browser validation")
            if target == "completed" and requires_browser:
                raise HarnessError("Browser-required task cannot complete from review")
        if source == "browser_validating" and target == "completed":
            if (
                not latest_browser
                or latest_browser["payload"].get("status") != "PASSED"
            ):
                raise HarnessError("Cannot complete before a passing browser result")
            if (
                not latest_evidence
                or latest_evidence["sequence"] < latest_browser["sequence"]
            ):
                raise HarnessError(
                    "Cannot complete before uploading current browser evidence"
                )
            if (
                not latest_implementation
                or not latest_verification
                or latest_verification["payload"].get("status") != "PASSED"
                or not latest_review
                or latest_review["payload"].get("verdict") != "APPROVED"
                or not (
                    latest_implementation["sequence"]
                    < latest_verification["sequence"]
                    < latest_review["sequence"]
                    < latest_browser["sequence"]
                )
            ):
                raise HarnessError(
                    "Cannot complete without fresh ordered implementation, verification, review, and browser evidence"
                )
            self._validate_evidence_asset(latest_evidence["payload"])
        if target == "completed" and not re.fullmatch(r"[0-9a-fA-F]{7,40}", reason):
            raise HarnessError("Completion reason must be the final task commit SHA")
        if target == "implementing" and source in {
            "verifying",
            "reviewing",
            "browser_validating",
        }:
            phase = {
                "verifying": "verification",
                "reviewing": "review",
                "browser_validating": "browser",
            }[source]
            decision = self.retry_decision(issue["number"], phase, run_id)
            if decision["decision"] != "repair":
                raise HarnessError(
                    f"Retry decision is {decision['decision']}, not repair"
                )

    def transition(
        self,
        issue_number: int,
        target: str,
        reason: str,
        *,
        run_id: str | None = None,
        event_id: str | None = None,
    ) -> dict[str, Any]:
        issue = self.client.get_issue(issue_number)
        task = parse_task_body(issue.get("body"))
        source = status_from_labels(issue.get("labels", []))
        events = self.issue_events(issue_number)
        self._validate_task_event_payloads(issue_number, task, events)
        event_status = status_from_events(events)
        lifecycle_events = [
            item
            for item in events
            if item["event"] in {"status_changed", "blocked", "completed"}
        ]
        latest_lifecycle = lifecycle_events[-1] if lifecycle_events else None

        def matches_requested_transition(event: dict[str, Any] | None) -> bool:
            return bool(
                event
                and event["payload"].get("to") == target
                and event["payload"].get("reason") == reason
                and event.get("run_id") == run_id
            )

        if event_status != source:
            if event_status != target or not matches_requested_transition(
                latest_lifecycle
            ):
                raise HarnessError(
                    f"Task label status {source} disagrees with event status {event_status}"
                )
            event = latest_lifecycle
        elif source == target:
            if not matches_requested_transition(latest_lifecycle):
                raise HarnessError(
                    f"Task is already {target}, but the latest lifecycle event does not match this request"
                )
            event = latest_lifecycle
        else:
            validate_transition(source, target)
            self._validate_transition_gates(
                issue, task, events, source, target, reason, run_id
            )
            event = build_event(
                issue_number,
                "status_changed" if target != "blocked" else "blocked",
                {"from": source, "to": target, "reason": reason},
                events,
                run_id=run_id,
                event_id=event_id,
            )
            if event not in events:
                self.client.comment(issue_number, render_event_comment(event))
        labels = [
            item.get("name") if isinstance(item, dict) else item
            for item in issue.get("labels", [])
        ]
        labels = [
            name
            for name in labels
            if isinstance(name, str) and not name.startswith(STATUS_LABEL_PREFIX)
        ]
        labels.append(f"{STATUS_LABEL_PREFIX}{target}")
        close_payload: dict[str, Any] = {"labels": labels}
        if target in TERMINAL_STATES:
            close_payload.update(
                {
                    "state": "closed",
                    "state_reason": "completed"
                    if target == "completed"
                    else "not_planned",
                }
            )
        self.client.update_issue(issue_number, close_payload)
        return event

    def post_result(
        self,
        issue_number: int,
        event_name: str,
        result: dict[str, Any],
        *,
        run_id: str,
        event_id: str | None = None,
    ) -> dict[str, Any]:
        allowed = {
            "implementation_result",
            "verification_result",
            "review_result",
            "browser_result",
            "evidence_uploaded",
        }
        if event_name not in allowed:
            raise HarnessError(f"Unsupported result event: {event_name}")
        issue = self.client.get_issue(issue_number)
        task = parse_task_body(issue.get("body"))
        source = status_from_labels(issue.get("labels", []))
        expected_source = {
            "implementation_result": "implementing",
            "verification_result": "verifying",
            "review_result": "reviewing",
            "browser_result": "browser_validating",
            "evidence_uploaded": "browser_validating",
        }[event_name]
        if source != expected_source:
            raise HarnessError(
                f"Cannot record {event_name} while task status is {source}"
            )
        if result.get("issue_number", issue_number) != issue_number:
            raise HarnessError("Result issue_number does not match task issue")
        if result.get("run_id", run_id) != run_id:
            raise HarnessError("Result run_id does not match active run")
        events = self.issue_events(issue_number)
        self._validate_task_event_payloads(issue_number, task, events)
        active_events = [
            event
            for event in events
            if event["event"] == "status_changed"
            and event["payload"].get("to") in ACTIVE_STATES
        ]
        if not active_events or active_events[-1].get("run_id") != run_id:
            raise HarnessError("Result run_id does not match the active run event")
        validate_result_payload(event_name, result, task, events, run_id)
        if event_name == "evidence_uploaded":
            browser = self._latest_run_event(events, "browser_result", run_id)
            if not browser or browser["payload"].get("status") != "PASSED":
                raise HarnessError(
                    "Evidence upload must follow a passing browser result"
                )
            self._validate_evidence_asset(result)
        if event_id is None:
            active_sequence = active_events[-1]["sequence"]
            event_id = str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"{self.client.repo}/issues/{issue_number}/runs/{run_id}/{event_name}/{active_sequence}/{sha256_json(result)}",
                )
            )
        event = build_event(
            issue_number, event_name, result, events, run_id=run_id, event_id=event_id
        )
        if event not in events:
            self.client.comment(issue_number, render_event_comment(event))
        return event

    def scope_override(
        self,
        issue_number: int,
        paths: list[str],
        operations: list[str],
        reason: str,
        *,
        run_id: str,
        applies_to: str = "current_run",
    ) -> dict[str, Any]:
        if not paths or not operations or not reason.strip():
            raise HarnessError("Scope override needs paths, operations, and reason")
        if applies_to != "current_run":
            raise HarnessError(
                "Scope overrides currently apply only to the current run"
            )
        allowed_operations = {"modify", "delete", "rename", "generate"}
        if not set(operations) <= allowed_operations:
            raise HarnessError(
                f"Scope override operations must be one of: {', '.join(sorted(allowed_operations))}"
            )
        for path in paths:
            _validate_repository_path(path, "scope override path")
            if path.endswith("/") or any(token in path for token in ("*", "?", "[")):
                raise HarnessError(
                    "Scope overrides require exact repository-relative file paths"
                )
        issue = self.client.get_issue(issue_number)
        status = status_from_labels(issue.get("labels", []))
        if status not in ACTIVE_STATES:
            raise HarnessError("Scope overrides require an active task")
        task = parse_task_body(issue.get("body"))
        forbidden = [entry["path"] for entry in task["scope"]["forbidden_paths"]]
        unknown = sorted(
            path
            for path in set(paths)
            if not any(path_matches_rule(path, rule) for rule in forbidden)
        )
        if unknown:
            raise HarnessError(
                f"Scope override paths are not task-level forbidden paths: {', '.join(unknown)}"
            )
        events = self.issue_events(issue_number)
        self._validate_task_event_payloads(issue_number, task, events)
        active_events = [
            event
            for event in events
            if event["event"] == "status_changed"
            and event["payload"].get("to") in ACTIVE_STATES
        ]
        if not active_events or active_events[-1].get("run_id") != run_id:
            raise HarnessError("Scope override run_id does not match the active run")
        override_payload = {
            "paths": sorted(set(paths)),
            "operations": sorted(set(operations)),
            "reason": reason,
            "authorized_by": "main_agent",
            "applies_to": applies_to,
        }
        event_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"{self.client.repo}/issues/{issue_number}/runs/{run_id}/scope/{active_events[-1]['sequence']}/{sha256_json(override_payload)}",
            )
        )
        event = build_event(
            issue_number,
            "scope_override",
            override_payload,
            events,
            run_id=run_id,
            event_id=event_id,
        )
        if event not in events:
            self.client.comment(issue_number, render_event_comment(event))
        return event

    def status(self) -> dict[str, Any]:
        issues = self.client.list_issues(state="open", label="harness:task")
        rows = []
        for issue in issues:
            task = parse_task_body(issue.get("body"))
            status = status_from_labels(issue.get("labels", []))
            if status in TERMINAL_STATES:
                raise HarnessError(
                    f"Open issue #{issue['number']} has terminal status {status}"
                )
            rows.append(
                {
                    "issue_number": issue["number"],
                    "url": issue["html_url"],
                    "title": issue["title"],
                    "proposal_key": task["proposal_key"],
                    "priority": task["priority"],
                    "status": status,
                }
            )
        active = [row for row in rows if row["status"] in ACTIVE_STATES]
        if len(active) > 1:
            raise HarnessError(
                f"Multiple active harness tasks: {[row['issue_number'] for row in active]}"
            )
        dependency_stalled = []
        eligible = []
        for row in rows:
            if row["status"] != "ready":
                continue
            blockers = self.client.dependencies(row["issue_number"])
            incomplete = [
                {
                    "issue_number": item["number"],
                    "url": item["html_url"],
                    "state": item["state"],
                }
                for item in blockers
                if item.get("state") != "closed"
                or item.get("state_reason") != "completed"
            ]
            if incomplete:
                dependency_stalled.append({**row, "blocked_by": incomplete})
            else:
                eligible.append(row)
        ready = sorted(eligible, key=lambda row: (row["priority"], row["issue_number"]))
        if active:
            next_action = "resume_active"
        elif ready:
            next_action = "select_next"
        elif any(row["status"] == "proposed" for row in rows):
            next_action = "wait_for_promotion"
        elif any(row["status"] == "blocked" for row in rows) or dependency_stalled:
            next_action = "stalled"
        else:
            next_action = "complete"
        return {
            "repository": self.repo_info["nameWithOwner"],
            "next_action": next_action,
            "active": active,
            "ready": ready,
            "dependency_stalled": dependency_stalled,
            "tasks": rows,
        }

    def validate(self) -> dict[str, Any]:
        control, _config = self.config()
        issues = self.client.list_issues(state="all", label="harness:task")
        validated = []
        active = []
        for issue in issues:
            task = parse_task_body(issue.get("body"))
            status = status_from_labels(issue.get("labels", []))
            state = issue.get("state")
            if status in TERMINAL_STATES and state != "closed":
                raise HarnessError(
                    f"Terminal task #{issue['number']} must be a closed issue"
                )
            if status not in TERMINAL_STATES and state != "open":
                raise HarnessError(
                    f"Non-terminal task #{issue['number']} must be an open issue"
                )
            if status == "completed" and issue.get("state_reason") != "completed":
                raise HarnessError(
                    f"Completed task #{issue['number']} needs completed state reason"
                )
            if (
                status in {"cancelled", "superseded"}
                and issue.get("state_reason") != "not_planned"
            ):
                raise HarnessError(
                    f"Retired task #{issue['number']} needs not_planned state reason"
                )
            events = self.issue_events(issue["number"])
            self._validate_task_event_payloads(issue["number"], task, events)
            derived_status = status_from_events(events)
            if status != derived_status:
                raise HarnessError(
                    f"Task #{issue['number']} label status {status} disagrees with event status {derived_status}"
                )
            if status in ACTIVE_STATES:
                active.append(issue["number"])
            validated.append(
                {
                    "issue_number": issue["number"],
                    "status": status,
                    "events": len(events),
                }
            )
        if len(active) > 1:
            raise HarnessError(f"Multiple active harness tasks: {active}")
        status_report = self.status()
        return {
            "repository": self.repo_info["nameWithOwner"],
            "control_issue": control["html_url"],
            "task_count": len(validated),
            "validated": validated,
            "next_action": status_report["next_action"],
            "active": status_report["active"],
            "ready": status_report["ready"],
            "dependency_stalled": status_report["dependency_stalled"],
        }

    def context(self, issue_number: int) -> dict[str, Any]:
        control, config = self.config()
        issue = self.client.get_issue(issue_number)
        task = parse_task_body(issue.get("body"))
        status = status_from_labels(issue.get("labels", []))
        events = self.issue_events(issue_number)
        self._validate_task_event_payloads(issue_number, task, events)
        overrides = [event for event in events if event["event"] == "scope_override"]
        return {
            "repository": self.repo_info["nameWithOwner"],
            "control_issue_url": control["html_url"],
            "task_issue": {
                "number": issue_number,
                "url": issue["html_url"],
                "title": issue["title"],
                "status": status,
            },
            "task": task,
            "configuration": config,
            "events": events,
            "effective_scope_overrides": overrides,
            "resources": {
                "prompts": {
                    path.name: str(path) for path in sorted(PROMPT_DIR.glob("*.md"))
                },
                "schemas": {
                    path.name: str(path) for path in sorted(SCHEMA_DIR.glob("*.json"))
                },
            },
        }
