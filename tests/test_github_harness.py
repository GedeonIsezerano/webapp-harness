from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import jsonschema
import pytest

ROOT = Path(__file__).parents[1]
PLUGIN = ROOT / "plugins" / "webapp-harness"
SCRIPTS = PLUGIN / "scripts"
sys.path.insert(0, str(SCRIPTS))

from github_harness import _safe_evidence_files, _write_deterministic_zip
from harness_core import (
    GitHubHarness,
    HarnessError,
    build_event,
    events_from_comments,
    extract_marker,
    marker,
    parse_task_body,
    render_event_comment,
    sha256_file,
    status_from_labels,
    validate_event_chain,
    validate_proposal,
)
from migrate_legacy_harness import (
    convert_config,
    convert_task,
    migration_material,
)


def config() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "retry_limits": {"verification": 2, "review": 2, "browser": 2},
        "verification_profiles": {
            "unit": [{"name": "Unit", "command": ["npm", "test"]}]
        },
        "commit": {"subject_format": "[#{issue_number}] {title}"},
    }


def task(
    key: str,
    *,
    dependencies: list[str] | None = None,
    requires_browser: bool = False,
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "proposal_key": key,
        "title": f"Task {key}",
        "description": "Implement the observed behavior.",
        "priority": 1,
        "dependencies": dependencies or [],
        "type": "user-facing",
        "gap_evidence": [
            {"location": "src/app.ts", "observation": "Behavior is missing."}
        ],
        "acceptance_criteria": [
            {
                "id": f"{key}-1",
                "description": "Behavior works.",
                "verification": ["unit", "browser"] if requires_browser else ["unit"],
            }
        ],
        "verification": {"profiles": ["unit"], "requires_browser": requires_browser},
        "scope": {
            "recommended_paths": [
                {"path": "src/", "reason": "Primary implementation area."}
            ],
            "forbidden_paths": [
                {
                    "path": "migrations/",
                    "reason": "Delegated workers cannot rewrite migration history.",
                }
            ],
        },
    }


def implementation_result(issue: int = 3, run_id: str = "run-1") -> dict[str, Any]:
    return {
        "issue_number": issue,
        "run_id": run_id,
        "summary": "Implemented the accepted behavior.",
        "files_changed": ["src/app.ts"],
        "tests_changed": ["tests/app.test.ts"],
        "browser_flows": [],
        "risks": [],
    }


def verification_result(
    status: str = "PASSED",
    failure_class: str | None = None,
    issue: int = 3,
    run_id: str = "run-1",
) -> dict[str, Any]:
    return {
        "issue_number": issue,
        "run_id": run_id,
        "status": status,
        "failure_class": failure_class,
        "checks": [{"name": "Unit", "status": status}],
    }


def review_result(
    verdict: str = "APPROVED", issue: int = 3, run_id: str = "run-1"
) -> dict[str, Any]:
    return {
        "issue_number": issue,
        "run_id": run_id,
        "verdict": verdict,
        "findings": [],
    }


def browser_result(issue: int = 3, run_id: str = "run-1") -> dict[str, Any]:
    return {
        "issue_number": issue,
        "run_id": run_id,
        "status": "PASSED",
        "failure_class": None,
        "blocker": None,
        "tooling": "chrome_control",
        "preflight": {
            "health": True,
            "fixtures": True,
            "profiles": True,
            "tooling": True,
        },
        "criteria": [
            {
                "id": "one-1",
                "status": "PASSED",
                "steps": ["Open the affected flow."],
                "observed": "The accepted behavior rendered and persisted.",
                "expected": "The accepted behavior renders and persists.",
                "evidence": ["shot.png"],
            }
        ],
    }


def evidence_uploaded() -> dict[str, Any]:
    return {
        "asset_url": "https://github.com/owner/repo/releases/download/harness-evidence-v1/evidence.zip",
        "asset_name": "evidence.zip",
        "sha256": "a" * 64,
        "size": 123,
        "file_count": 1,
        "release_id": 1,
    }


class FakeClient:
    def __init__(self) -> None:
        self.repo = "owner/repo"
        self.labels: set[str] = set()
        self.issues: list[dict[str, Any]] = []
        self.issue_comments: dict[int, list[dict[str, Any]]] = {}
        self.blocked_by: dict[int, list[int]] = {}
        self.subissues: dict[int, list[int]] = {}
        self.release_asset_rows: dict[int, list[dict[str, Any]]] = {
            1: [
                {
                    "name": "evidence.zip",
                    "digest": f"sha256:{'a' * 64}",
                    "size": 123,
                }
            ]
        }

    def resolve_repo(self) -> dict[str, Any]:
        return {
            "nameWithOwner": self.repo,
            "url": "https://github.com/owner/repo",
            "hasIssuesEnabled": True,
            "viewerPermission": "ADMIN",
            "defaultBranchRef": {"name": "main"},
        }

    def ensure_label(self, name: str, _color: str, _description: str) -> None:
        self.labels.add(name)

    def list_issues(
        self, *, state: str = "all", label: str | None = None
    ) -> list[dict[str, Any]]:
        values = self.issues
        if state != "all":
            values = [issue for issue in values if issue["state"] == state]
        if label:
            values = [issue for issue in values if label in issue["labels"]]
        return values.copy()

    def create_issue(self, title: str, body: str, labels: list[str]) -> dict[str, Any]:
        number = len(self.issues) + 1
        issue = {
            "id": 1000 + number,
            "number": number,
            "title": title,
            "body": body,
            "labels": labels.copy(),
            "state": "open",
            "state_reason": None,
            "html_url": f"https://github.com/owner/repo/issues/{number}",
        }
        self.issues.append(issue)
        self.issue_comments[number] = []
        return issue

    def update_issue(self, number: int, payload: dict[str, Any]) -> dict[str, Any]:
        issue = self.get_issue(number)
        issue.update(payload)
        return issue

    def get_issue(self, number: int) -> dict[str, Any]:
        return next(issue for issue in self.issues if issue["number"] == number)

    def comments(self, number: int) -> list[dict[str, Any]]:
        return self.issue_comments[number].copy()

    def comment(self, number: int, body: str) -> dict[str, Any]:
        value = {"id": len(self.issue_comments[number]) + 1, "body": body}
        self.issue_comments[number].append(value)
        return value

    def add_sub_issue(self, parent_number: int, child_id: int) -> None:
        values = self.subissues.setdefault(parent_number, [])
        if child_id not in values:
            values.append(child_id)

    def add_dependency(self, issue_number: int, blocking_issue_id: int) -> None:
        values = self.blocked_by.setdefault(issue_number, [])
        if blocking_issue_id not in values:
            values.append(blocking_issue_id)

    def dependencies(self, issue_number: int) -> list[dict[str, Any]]:
        ids = self.blocked_by.get(issue_number, [])
        return [issue for issue in self.issues if issue["id"] in ids]

    def release_assets(self, release_id: int) -> list[dict[str, Any]]:
        return self.release_asset_rows.get(release_id, []).copy()


def initialized() -> tuple[GitHubHarness, FakeClient]:
    client = FakeClient()
    value = GitHubHarness(client)  # type: ignore[arg-type]
    value.initialize(config())
    return value, client


def test_release_versions_are_synchronized() -> None:
    manifest_version = json.loads((PLUGIN / ".codex-plugin/plugin.json").read_text())[
        "version"
    ]
    project_version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"][
        "version"
    ]
    assert {manifest_version, project_version} == {"0.1.0"}


def test_plugin_contains_no_repository_starter_or_python_cache() -> None:
    assert not [
        path for path in (PLUGIN / "assets" / "starter").rglob("*") if path.is_file()
    ]
    tracked = subprocess.run(
        ["git", "ls-files", str(PLUGIN.relative_to(ROOT))],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.splitlines()
    assert not [
        path for path in tracked if "__pycache__" in path or path.endswith(".pyc")
    ]


def test_plugin_python_sources_compile() -> None:
    for source in PLUGIN.rglob("*.py"):
        compile(source.read_text(encoding="utf-8"), str(source), "exec")


def test_all_json_schemas_are_valid() -> None:
    for path in (PLUGIN / "schemas").glob("*.json"):
        schema = json.loads(path.read_text())
        jsonschema.validators.validator_for(schema).check_schema(schema)


def test_task_schema_replaces_allowed_paths_with_recommendations() -> None:
    schema = json.loads((PLUGIN / "schemas" / "task.schema.json").read_text())
    jsonschema.validate(task("one"), schema)
    invalid = task("one")
    invalid["scope"] = {"allowed_paths": ["src/"], "forbidden_paths": []}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(invalid, schema)


def test_proposal_validation_hashes_and_checks_dependencies() -> None:
    proposal = {
        "schema_version": 2,
        "title": "Batch",
        "tasks": [task("one"), task("two", dependencies=["one"])],
    }
    digest = validate_proposal(proposal, config())
    assert len(digest) == 64
    proposal["tasks"][1]["dependencies"] = ["missing"]
    with pytest.raises(HarnessError, match="unknown dependencies"):
        validate_proposal(proposal, config())


def test_machine_marker_requires_exactly_one_object() -> None:
    body = "Human\n\n" + marker("task", task("one"))
    assert extract_marker(body, "task")["proposal_key"] == "one"
    with pytest.raises(HarnessError, match="exactly one"):
        extract_marker(body + "\n" + marker("task", task("two")), "task")


def test_task_marker_digest_detects_contract_edit() -> None:
    value, client = initialized()
    proposal = {"schema_version": 2, "title": "Batch", "tasks": [task("one")]}
    digest = value.proposal_plan(proposal)["proposal_sha256"]
    value.apply_proposal(proposal, digest)
    issue = client.get_issue(3)
    payload = extract_marker(issue["body"], "task")
    payload["description"] = "Manually edited contract"
    issue["body"] = marker("task", payload)
    with pytest.raises(HarnessError, match="task marker digest"):
        parse_task_body(issue["body"])


def test_event_chain_detects_tampering() -> None:
    first = build_event(
        1,
        "status_changed",
        {"from": "proposed", "to": "ready"},
        [],
        event_id="00000000-0000-0000-0000-000000000001",
    )
    second = build_event(
        1,
        "status_changed",
        {"from": "ready", "to": "implementing"},
        [first],
        event_id="00000000-0000-0000-0000-000000000002",
    )
    validate_event_chain([first, second], 1)
    second["payload"]["to"] = "completed"
    with pytest.raises(HarnessError, match="Invalid event digest"):
        validate_event_chain([first, second], 1)


def test_events_round_trip_through_comments() -> None:
    event = build_event(7, "scope_override", {"paths": ["migrations/"]}, [])
    comments = [{"body": "Human comment"}, {"body": render_event_comment(event)}]
    assert events_from_comments(comments, 7) == [event]


def test_transition_recovers_comment_written_before_label_projection() -> None:
    value, client = initialized()
    proposal = {"schema_version": 2, "title": "Batch", "tasks": [task("one")]}
    digest = value.proposal_plan(proposal)["proposal_sha256"]
    value.apply_proposal(proposal, digest)
    value.transition(3, "ready", "user_approved")
    value.transition(3, "implementing", "selected", run_id="run-1")
    event_count = len(client.comments(3))
    client.get_issue(3)["labels"] = ["harness:task", "harness:status:ready"]
    value.transition(3, "implementing", "selected", run_id="run-1")
    assert len(client.comments(3)) == event_count
    assert status_from_labels(client.get_issue(3)["labels"]) == "implementing"


def test_completed_transition_retry_is_idempotent() -> None:
    value, _client = initialized()
    proposal = {"schema_version": 2, "title": "Batch", "tasks": [task("one")]}
    digest = value.proposal_plan(proposal)["proposal_sha256"]
    value.apply_proposal(proposal, digest)
    value.transition(3, "ready", "user_approved")
    value.transition(3, "implementing", "selected", run_id="run-1")
    value.post_result(
        3, "implementation_result", implementation_result(), run_id="run-1"
    )
    value.transition(3, "verifying", "implemented", run_id="run-1")
    value.post_result(3, "verification_result", verification_result(), run_id="run-1")
    value.transition(3, "reviewing", "verified", run_id="run-1")
    value.post_result(3, "review_result", review_result(), run_id="run-1")
    first = value.transition(3, "completed", "abcdef1", run_id="run-1")
    second = value.transition(3, "completed", "abcdef1", run_id="run-1")
    assert first == second


def test_identical_result_retry_is_idempotent_within_phase() -> None:
    value, _client = initialized()
    proposal = {"schema_version": 2, "title": "Batch", "tasks": [task("one")]}
    digest = value.proposal_plan(proposal)["proposal_sha256"]
    value.apply_proposal(proposal, digest)
    value.transition(3, "ready", "user_approved")
    value.transition(3, "implementing", "selected", run_id="run-1")
    result = implementation_result()
    first = value.post_result(3, "implementation_result", result, run_id="run-1")
    second = value.post_result(3, "implementation_result", result, run_id="run-1")
    assert first == second
    assert (
        len(
            [
                event
                for event in value.issue_events(3)
                if event["event"] == "implementation_result"
            ]
        )
        == 1
    )


def test_initialize_creates_only_remote_configuration_objects() -> None:
    value, client = initialized()
    plan = value.initialization_plan(config())
    assert plan["writes_repository_files"] is False
    assert len(client.issues) == 1
    assert client.issues[0]["labels"] == ["harness:control"]
    assert "harness:task" in client.labels


def test_configuration_update_requires_explicit_override() -> None:
    value, client = initialized()
    changed = config()
    changed["retry_limits"]["review"] = 3
    assert (
        value.initialization_plan(changed)["control_issue"]
        == "update_requires_confirmation"
    )
    with pytest.raises(HarnessError, match="--update-existing"):
        value.initialize(changed)
    value.initialize(changed, allow_config_update=True)
    assert "config_sha256" in extract_marker(client.get_issue(1)["body"], "config")


def test_confirmed_proposal_creates_parent_subissues_and_native_dependency() -> None:
    value, client = initialized()
    proposal = {
        "schema_version": 2,
        "title": "Batch",
        "tasks": [task("one"), task("two", dependencies=["one"])],
    }
    digest = value.proposal_plan(proposal)["proposal_sha256"]
    applied = value.apply_proposal(proposal, digest)
    assert applied["parent_issue"].endswith("/2")
    assert len(client.issues) == 4
    assert client.subissues[2] == [1003, 1004]
    assert client.blocked_by[4] == [1003]
    assert status_from_labels(client.get_issue(3)["labels"]) == "proposed"


def test_proposal_apply_is_idempotent() -> None:
    value, client = initialized()
    proposal = {"schema_version": 2, "title": "Batch", "tasks": [task("one")]}
    digest = value.proposal_plan(proposal)["proposal_sha256"]
    first = value.apply_proposal(proposal, digest)
    second = value.apply_proposal(proposal, digest)
    assert first == second
    assert len(client.issues) == 3


def test_dependency_blocks_ready_selection_until_completed() -> None:
    value, client = initialized()
    proposal = {
        "schema_version": 2,
        "title": "Batch",
        "tasks": [task("one"), task("two", dependencies=["one"])],
    }
    digest = value.proposal_plan(proposal)["proposal_sha256"]
    value.apply_proposal(proposal, digest)
    value.transition(3, "ready", "user_approved")
    value.transition(4, "ready", "user_approved")
    report = value.status()
    assert [row["issue_number"] for row in report["ready"]] == [3]
    assert report["dependency_stalled"][0]["issue_number"] == 4
    client.get_issue(3).update(
        {
            "state": "closed",
            "state_reason": "completed",
            "labels": ["harness:task", "harness:status:completed"],
        }
    )
    assert [row["issue_number"] for row in value.status()["ready"]] == [4]


def test_main_agent_scope_override_requires_a_task_forbidden_path() -> None:
    value, _client = initialized()
    proposal = {"schema_version": 2, "title": "Batch", "tasks": [task("one")]}
    digest = value.proposal_plan(proposal)["proposal_sha256"]
    value.apply_proposal(proposal, digest)
    value.transition(3, "ready", "user_approved")
    value.transition(3, "implementing", "selected", run_id="run-1")
    event = value.scope_override(
        3,
        ["migrations/new.sql"],
        ["modify"],
        "Required by accepted behavior",
        run_id="run-1",
    )
    assert event["payload"]["authorized_by"] == "main_agent"
    assert event["payload"]["paths"] == ["migrations/new.sql"]
    with pytest.raises(HarnessError, match="not task-level forbidden"):
        value.scope_override(
            3, ["secrets/value.json"], ["modify"], "No", run_id="run-1"
        )
    with pytest.raises(HarnessError, match="exact repository-relative file paths"):
        value.scope_override(
            3, ["migrations/"], ["modify"], "Too broad", run_id="run-1"
        )


def test_forbidden_implementation_change_requires_recorded_override() -> None:
    value, _client = initialized()
    proposal = {"schema_version": 2, "title": "Batch", "tasks": [task("one")]}
    digest = value.proposal_plan(proposal)["proposal_sha256"]
    value.apply_proposal(proposal, digest)
    value.transition(3, "ready", "user_approved")
    value.transition(3, "implementing", "selected", run_id="run-1")
    result = implementation_result()
    result["files_changed"] = ["migrations/new.sql"]
    with pytest.raises(HarnessError, match="without a main-agent override"):
        value.post_result(3, "implementation_result", result, run_id="run-1")
    value.scope_override(
        3,
        ["migrations/new.sql"],
        ["modify"],
        "The accepted implementation requires this exact migration.",
        run_id="run-1",
    )
    value.post_result(3, "implementation_result", result, run_id="run-1")


def test_phase_transitions_require_current_ordered_results() -> None:
    value, _client = initialized()
    proposal = {"schema_version": 2, "title": "Batch", "tasks": [task("one")]}
    digest = value.proposal_plan(proposal)["proposal_sha256"]
    value.apply_proposal(proposal, digest)
    value.transition(3, "ready", "user_approved")
    value.transition(3, "implementing", "selected", run_id="run-1")
    with pytest.raises(HarnessError, match="implementation result"):
        value.transition(3, "verifying", "implementation_finished", run_id="run-1")
    value.post_result(
        3,
        "implementation_result",
        implementation_result(),
        run_id="run-1",
    )
    value.transition(3, "verifying", "implementation_finished", run_id="run-1")
    with pytest.raises(HarnessError, match="passing verification"):
        value.transition(3, "reviewing", "verification_passed", run_id="run-1")
    value.post_result(
        3,
        "verification_result",
        verification_result(),
        run_id="run-1",
    )
    value.transition(3, "reviewing", "verification_passed", run_id="run-1")
    value.post_result(
        3,
        "review_result",
        review_result(),
        run_id="run-1",
    )
    value.transition(3, "completed", "abcdef1", run_id="run-1")
    assert status_from_labels(_client.get_issue(3)["labels"]) == "completed"


def test_retry_decision_counts_only_product_failures() -> None:
    value, _client = initialized()
    proposal = {"schema_version": 2, "title": "Batch", "tasks": [task("one")]}
    digest = value.proposal_plan(proposal)["proposal_sha256"]
    value.apply_proposal(proposal, digest)
    value.transition(3, "ready", "user_approved")
    value.transition(3, "implementing", "selected", run_id="run-1")
    value.post_result(
        3,
        "implementation_result",
        implementation_result(),
        run_id="run-1",
    )
    value.transition(3, "verifying", "implementation_finished", run_id="run-1")
    value.post_result(
        3,
        "verification_result",
        verification_result("FAILED", "product"),
        run_id="run-1",
    )
    assert value.retry_decision(3, "verification", "run-1")["decision"] == "repair"
    value.transition(3, "implementing", "verification_product_failure", run_id="run-1")
    with pytest.raises(HarnessError, match="stale relative"):
        value.transition(3, "verifying", "repair_finished", run_id="run-1")


def test_non_product_failure_blocks_without_repair() -> None:
    value, _client = initialized()
    proposal = {"schema_version": 2, "title": "Batch", "tasks": [task("one")]}
    digest = value.proposal_plan(proposal)["proposal_sha256"]
    value.apply_proposal(proposal, digest)
    value.transition(3, "ready", "user_approved")
    value.transition(3, "implementing", "selected", run_id="run-1")
    value.post_result(
        3,
        "implementation_result",
        implementation_result(),
        run_id="run-1",
    )
    value.transition(3, "verifying", "implementation_finished", run_id="run-1")
    value.post_result(
        3,
        "verification_result",
        verification_result("INCOMPLETE", "environment"),
        run_id="run-1",
    )
    assert value.retry_decision(3, "verification", "run-1")["decision"] == "block"
    with pytest.raises(HarnessError, match="not repair"):
        value.transition(3, "implementing", "retry", run_id="run-1")


def test_browser_task_requires_current_uploaded_evidence_before_completion() -> None:
    value, client = initialized()
    proposal = {
        "schema_version": 2,
        "title": "Batch",
        "tasks": [task("one", requires_browser=True)],
    }
    digest = value.proposal_plan(proposal)["proposal_sha256"]
    value.apply_proposal(proposal, digest)
    value.transition(3, "ready", "user_approved")
    value.transition(3, "implementing", "selected", run_id="run-1")
    value.post_result(
        3,
        "implementation_result",
        implementation_result(),
        run_id="run-1",
    )
    value.transition(3, "verifying", "implemented", run_id="run-1")
    value.post_result(
        3,
        "verification_result",
        verification_result(),
        run_id="run-1",
    )
    value.transition(3, "reviewing", "verified", run_id="run-1")
    value.post_result(
        3,
        "review_result",
        review_result(),
        run_id="run-1",
    )
    value.transition(3, "browser_validating", "review_approved", run_id="run-1")
    value.post_result(
        3,
        "browser_result",
        browser_result(),
        run_id="run-1",
    )
    with pytest.raises(HarnessError, match="uploading current browser evidence"):
        value.transition(3, "completed", "abcdef1", run_id="run-1")
    value.post_result(
        3,
        "evidence_uploaded",
        evidence_uploaded(),
        run_id="run-1",
    )
    uploaded_assets = client.release_asset_rows[1]
    client.release_asset_rows[1] = []
    with pytest.raises(HarnessError, match="matching immutable asset"):
        value.transition(3, "completed", "abcdef1", run_id="run-1")
    client.release_asset_rows[1] = uploaded_assets
    value.transition(3, "completed", "abcdef1", run_id="run-1")
    assert client.get_issue(3)["state_reason"] == "completed"


def test_multiple_active_tasks_are_rejected() -> None:
    value, client = initialized()
    proposal = {
        "schema_version": 2,
        "title": "Batch",
        "tasks": [task("one"), task("two")],
    }
    digest = value.proposal_plan(proposal)["proposal_sha256"]
    value.apply_proposal(proposal, digest)
    for number in (3, 4):
        client.get_issue(number)["labels"] = [
            "harness:task",
            "harness:status:implementing",
        ]
    with pytest.raises(HarnessError, match="Multiple active"):
        value.status()


def test_evidence_zip_is_deterministic_and_rejects_sensitive_names(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "shot.png").write_bytes(b"png")
    files = _safe_evidence_files(evidence)
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    _write_deterministic_zip(evidence, files, first)
    _write_deterministic_zip(evidence, files, second)
    assert sha256_file(first) == sha256_file(second)
    (evidence / "credentials.json").write_text("{}")
    with pytest.raises(HarnessError, match="sensitive-looking"):
        _safe_evidence_files(evidence)


def test_legacy_conversion_changes_allowed_to_recommended() -> None:
    legacy = task("legacy")
    legacy.update({"id": "LEGACY-1", "status": "ready"})
    legacy["scope"] = {"allowed_paths": ["src/"], "forbidden_paths": ["migrations/"]}
    converted = convert_task(legacy, "unit")
    assert converted["scope"]["recommended_paths"][0]["path"] == "src/"
    assert converted["scope"]["forbidden_paths"][0]["path"] == "migrations/"


def test_legacy_migration_plan_is_non_destructive_and_hash_bound(
    tmp_path: Path,
) -> None:
    harness = tmp_path / ".harness"
    harness.mkdir()
    legacy_config = {
        "schema_version": 1,
        "retry_limits": {"verification": 1, "review": 1, "browser": 1},
        "verification_profiles": {
            "unit": [{"name": "Unit", "command": ["npm", "test"]}]
        },
        "commit": {"subject_format": "[{task_id}] {title}"},
    }
    (harness / "config.json").write_text(json.dumps(legacy_config))
    legacy_task = task("legacy")
    legacy_task.update({"id": "LEGACY-1", "status": "ready"})
    legacy_task["scope"] = {"allowed_paths": ["src/"], "forbidden_paths": []}
    (harness / "backlog.json").write_text(json.dumps({"tasks": [legacy_task]}))
    (harness / "completed-tasks.json").write_text(json.dumps({"completed_tasks": []}))
    (harness / "dev-credentials.local.json").write_text('{"secret": true}')
    material = migration_material(tmp_path)
    assert len(material["migration_sha256"]) == 64
    assert material["legacy_statuses"] == {"LEGACY-1": "ready"}
    assert material["excluded_sensitive_files"] == [
        ".harness/dev-credentials.local.json"
    ]
    assert all("credential" not in row["path"] for row in material["archive_manifest"])
    assert (harness / "backlog.json").exists()


def test_convert_config_updates_commit_placeholder() -> None:
    old = {
        "verification_profiles": {
            "unit": [{"name": "Unit", "command": ["npm", "test"]}]
        },
        "retry_limits": {"verification": 1, "review": 1, "browser": 1},
        "commit": {"subject_format": "[{task_id}] {title}"},
    }
    assert (
        convert_config(old)["commit"]["subject_format"] == "[#{issue_number}] {title}"
    )


def test_orchestration_and_backlog_skills_reference_github_not_local_state() -> None:
    for name in ("generate-backlog", "orchestrate-development-cycle"):
        body = (PLUGIN / "skills" / name / "SKILL.md").read_text()
        assert "GitHub" in body
        assert ".harness/current-task.json" not in body
        assert "scripts/harness/" not in body
