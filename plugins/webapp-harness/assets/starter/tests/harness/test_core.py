import json
import shutil
import subprocess
from pathlib import Path

import pytest

from archive_completed_tasks import archive_completed
from backlog_status import backlog_status
from check_repo_clean import check as check_repo_clean
from collect_diff import collect
from common import latest_result, priority_sort_key
from conftest import write_json
from create_task_commit import assert_task_scope, commit_subject, create
from lifecycle import can_transition
from merge_backlog_proposal import apply as apply_proposal
from merge_backlog_proposal import preview as preview_proposal
from migrate_v0_0_10 import apply_migration, migration_plan
from record_result import record
from reprioritize import reprioritize
from retry_status import inspect as retry_status
from select_next_task import select
from update_task_state import transition
from update_task_dependencies import update_dependencies
from validate_state import validate
from verify_task import verify


def fixture(tmp_path):
    shutil.copytree(Path(__file__).parents[2] / ".harness", tmp_path / ".harness")
    config = json.loads((tmp_path / ".harness/config.json").read_text())
    config["verification_profiles"] = {
        "unit": [
            {
                "name": "Unit tests",
                "command": ["python", "-c", 'print("ok")'],
            }
        ]
    }
    write_json(tmp_path / ".harness/config.json", config)
    return tmp_path


def task(task_id, status="ready", priority=1, deps=None):
    return {
        "id": task_id,
        "title": "Task " + task_id,
        "description": "A test task",
        "status": status,
        "priority": priority,
        "dependencies": deps or [],
        "type": "backend",
        "acceptance_criteria": [
            {
                "id": "AC-1",
                "description": "Works",
                "verification": ["unit"],
            }
        ],
        "verification": {"profiles": ["unit"], "requires_browser": False},
        "scope": {"allowed_paths": ["src/"], "forbidden_paths": []},
    }


def proposed_task(task_id="GAP-001", deps=None):
    proposed = task(task_id, status="proposed", deps=deps)
    proposed["gap_evidence"] = [
        {
            "location": "src/example.py:1",
            "observation": "Required behavior is missing.",
        }
    ]
    return proposed


def browser_task(status="ready"):
    selected = task("A-001", status=status)
    selected["verification"]["requires_browser"] = True
    selected["acceptance_criteria"][0]["verification"] = ["unit", "browser"]
    return selected


def implementation_result(run_id):
    return {
        "task_id": "A-001",
        "run_id": run_id,
        "files_changed": ["src/a.py"],
        "summary": "Implemented.",
        "tests_changed": ["tests/test_a.py"],
        "browser_flows": [],
        "risks": [],
    }


def review_result(run_id, verdict="APPROVED"):
    return {
        "task_id": "A-001",
        "run_id": run_id,
        "verdict": verdict,
        "findings": (
            []
            if verdict == "APPROVED"
            else [
                {
                    "severity": "blocking",
                    "criterion_id": "AC-1",
                    "location": "src/a.py:1",
                    "failure_mode": "Broken",
                    "recommendation": "Repair it",
                }
            ]
        ),
    }


def browser_result(
    run_id,
    screenshots=None,
    surface="playwright",
    status="PASSED",
    failure_class=None,
):
    return {
        "task_id": "A-001",
        "run_id": run_id,
        "status": status,
        "failure_class": failure_class,
        "blocker": None if status == "PASSED" else "Exact browser blocker.",
        "preflight": {
            "app_healthy": True,
            "fixtures_ready": True,
            "profiles_ready": True,
            "tooling_ready": True,
        },
        "tooling": {"surface": surface},
        "criteria": [
            {
                "criterion_id": "AC-1",
                "result": "PASS" if status == "PASSED" else "FAIL",
                "steps": ["step"],
                "observed": "observed",
                "expected": "expected",
                "url": "http://localhost",
                "console_errors": [],
                "network_errors": [],
                "screenshots": screenshots or [],
            }
        ],
    }


def record_json(root, kind, payload, filename):
    path = root / filename
    write_json(path, payload)
    return record(root, kind, path)


def write_diff_snapshot(root, run_id):
    run_path = root / ".harness/runs" / run_id / "run.json"
    run = json.loads(run_path.read_text())
    diff_path = root / ".harness/runs" / run_id / "task.diff"
    diff_path.write_text("diff --git a/src/a.py b/src/a.py\n")
    run["diff_snapshot"] = {
        "path": str(diff_path.relative_to(root)),
        "collected_at": "2026-07-25T00:00:00Z",
        "after_event_sequence": run["event_counter"],
    }
    write_json(run_path, run)


def enter_verifying(root, run_id):
    record_json(
        root,
        "implementation-result",
        implementation_result(run_id),
        "implementation-input.json",
    )
    transition(root, "A-001", "verifying", "implementation_finished")


def enter_reviewing(root, run_id):
    enter_verifying(root, run_id)
    assert verify(root)["status"] == "PASSED"
    transition(root, "A-001", "reviewing", "verification_passed")
    write_diff_snapshot(root, run_id)


def enter_browser_validation(root, run_id):
    enter_reviewing(root, run_id)
    record_json(root, "review", review_result(run_id), "review-input.json")
    transition(root, "A-001", "browser_validating", "review_approved")


def test_lifecycle_orders_review_before_browser():
    assert can_transition("verifying", "reviewing")
    assert can_transition("reviewing", "browser_validating")
    assert not can_transition("verifying", "browser_validating")


def test_deterministic_selection(tmp_path):
    root = fixture(tmp_path)
    write_json(
        root / ".harness/backlog.json",
        {
            "schema_version": 1,
            "tasks": [
                task("Z-001", priority=1),
                task("A-001", priority=1),
                task("B-001", priority=5),
            ],
        },
    )
    assert select(root)["task_id"] == "A-001"


def test_priority_sort_key_orders_low_values_first():
    assert priority_sort_key({"id": "A-002", "priority": 1}) < priority_sort_key(
        {"id": "A-001", "priority": 2}
    )
    assert priority_sort_key({"id": "A-001"}) > priority_sort_key(
        {"id": "Z-099", "priority": 999}
    )


def test_dependency_blocks_selection(tmp_path):
    root = fixture(tmp_path)
    write_json(
        root / ".harness/backlog.json",
        {
            "schema_version": 1,
            "tasks": [
                task("A-001", deps=["B-001"]),
                task("B-001"),
            ],
        },
    )
    assert select(root)["task_id"] == "B-001"


def test_archiving_cold_stores_run_and_preserves_completion_record(tmp_path):
    root = fixture(tmp_path)
    completed = task("DONE-001", status="completed")
    dependent = task("NEXT-001", deps=["DONE-001"])
    write_json(
        root / ".harness/backlog.json",
        {"schema_version": 1, "tasks": [completed, dependent]},
    )
    run_dir = root / ".harness/runs/DONE-001-run"
    run_dir.mkdir(parents=True)
    write_json(
        run_dir / "run.json",
        {
            "task_id": "DONE-001",
            "status": "completed",
            "result_commit": "abc123",
            "completed_at": "2026-07-25T00:00:00Z",
        },
    )
    result = archive_completed(root)
    assert result["archived_task_ids"] == ["DONE-001"]
    assert not run_dir.exists()
    assert (root / ".harness/archive/runs/DONE-001-run/run.json").is_file()
    backlog = json.loads((root / ".harness/backlog.json").read_text())
    assert [entry["id"] for entry in backlog["tasks"]] == ["NEXT-001"]
    completion = json.loads((root / ".harness/completed-tasks.json").read_text())[
        "completed_tasks"
    ][0]
    assert completion["run_id"] == "DONE-001-run"
    assert completion["archive_path"].endswith("DONE-001-run")
    assert not validate(root)
    assert select(root)["task_id"] == "NEXT-001"


def test_archiving_requires_committed_run_and_dry_run_is_read_only(tmp_path):
    root = fixture(tmp_path)
    write_json(
        root / ".harness/backlog.json",
        {"schema_version": 1, "tasks": [task("DONE-001", status="completed")]},
    )
    with pytest.raises(ValueError, match="result commit"):
        archive_completed(root)
    run_dir = root / ".harness/runs/DONE-001-run"
    run_dir.mkdir(parents=True)
    write_json(
        run_dir / "run.json",
        {
            "task_id": "DONE-001",
            "status": "completed",
            "result_commit": "abc123",
            "completed_at": "2026-07-25T00:00:00Z",
        },
    )
    assert archive_completed(root, dry_run=True)["archived_run_ids"] == [
        "DONE-001-run"
    ]
    assert run_dir.exists()
    assert not (root / ".harness/archive/completed-tasks.jsonl").exists()


def test_selection_writes_current_task_and_browser_plan(tmp_path):
    root = fixture(tmp_path)
    write_json(
        root / ".harness/backlog.json",
        {"schema_version": 1, "tasks": [browser_task()]},
    )
    selected = select(root)
    current = json.loads((root / ".harness/current-task.json").read_text())
    assert current["run_id"] == selected["run_id"]
    assert current["task"]["status"] == "implementing"
    plan = json.loads(
        (
            root
            / ".harness/runs"
            / selected["run_id"]
            / "browser-plan.json"
        ).read_text()
    )
    assert [entry["criterion_id"] for entry in plan["criteria"]] == ["AC-1"]
    assert plan["execution_policy"]["shared_screenshots_allowed"] is True


def test_selection_rejects_dependency_stalled_task(tmp_path):
    root = fixture(tmp_path)
    write_json(
        root / ".harness/backlog.json",
        {
            "schema_version": 1,
            "tasks": [task("A-001", deps=["B-001"]), task("B-001")],
        },
    )
    with pytest.raises(ValueError, match="not eligible"):
        select(root, "A-001")


def test_duplicate_ids_and_cycles_fail_validation(tmp_path):
    root = fixture(tmp_path)
    write_json(
        root / ".harness/backlog.json",
        {"schema_version": 1, "tasks": [task("A-001"), task("A-001")]},
    )
    assert any("unique" in error for error in validate(root))
    write_json(
        root / ".harness/backlog.json",
        {
            "schema_version": 1,
            "tasks": [
                task("A-001", deps=["B-001"]),
                task("B-001", deps=["A-001"]),
            ],
        },
    )
    assert any("cycle" in error for error in validate(root))


def test_zero_check_verification_is_incomplete_and_non_product(tmp_path):
    root = fixture(tmp_path)
    selected_task = task("A-001")
    selected_task["verification"]["profiles"] = []
    write_json(
        root / ".harness/backlog.json",
        {"schema_version": 1, "tasks": [selected_task]},
    )
    selected = select(root)
    enter_verifying(root, selected["run_id"])
    result = verify(root)
    assert result["status"] == "INCOMPLETE"
    assert result["failure_class"] == "environment"
    assert retry_status(root, "verification")["action"] == "block"


def test_transition_updates_active_run_and_cold_transition_log(tmp_path):
    root = fixture(tmp_path)
    write_json(
        root / ".harness/backlog.json",
        {"schema_version": 1, "tasks": [task("A-001")]},
    )
    selected = select(root)
    enter_verifying(root, selected["run_id"])
    run = json.loads(
        (root / ".harness/runs" / selected["run_id"] / "run.json").read_text()
    )
    assert run["status"] == "verifying"
    assert run["transitions"][-1]["to"] == "verifying"
    state = json.loads((root / ".harness/state.json").read_text())
    assert set(state) == {
        "schema_version",
        "active_task_id",
        "active_run_id",
        "pending_commit_task_id",
    }
    assert (root / ".harness/archive/transitions.jsonl").is_file()


def test_validate_rejects_run_status_mismatch(tmp_path):
    root = fixture(tmp_path)
    write_json(
        root / ".harness/backlog.json",
        {"schema_version": 1, "tasks": [task("A-001")]},
    )
    selected = select(root)
    run_path = root / ".harness/runs" / selected["run_id"] / "run.json"
    run = json.loads(run_path.read_text())
    run["status"] = "reviewing"
    write_json(run_path, run)
    assert any("run status" in error for error in validate(root))


def test_commit_scope_rejects_unrelated_paths(tmp_path):
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "harness@example.test"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Harness Test"],
        cwd=tmp_path,
        check=True,
    )
    (tmp_path / "baseline.txt").write_text("baseline\n")
    subprocess.run(["git", "add", "baseline.txt"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "baseline"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    scoped = task("A-001")
    scoped["scope"] = {
        "allowed_paths": ["hello.txt"],
        "forbidden_paths": ["secrets/"],
    }
    (tmp_path / "hello.txt").write_text("hello\n")
    assert_task_scope(tmp_path, scoped)
    (tmp_path / "other.txt").write_text("other\n")
    with pytest.raises(ValueError, match="outside allowed paths"):
        assert_task_scope(tmp_path, scoped)


def test_commit_subject_format_is_effective():
    selected = task("A-001")
    config = {"commit": {"subject_format": "feat({task_id}): {title}"}}
    assert commit_subject(config, selected) == "feat(A-001): Task A-001"
    with pytest.raises(ValueError, match="Invalid"):
        commit_subject(
            {"commit": {"subject_format": "{unknown}"}},
            selected,
        )


def test_full_non_browser_cycle_creates_configured_task_commit(tmp_path):
    root = fixture(tmp_path)
    selected_task = task("A-001")
    write_json(
        root / ".harness/backlog.json",
        {"schema_version": 1, "tasks": [selected_task]},
    )
    config = json.loads((root / ".harness/config.json").read_text())
    config["commit"]["subject_format"] = "feat({task_id}): {title}"
    write_json(root / ".harness/config.json", config)
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "harness@example.test"],
        cwd=root,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Harness Test"],
        cwd=root,
        check=True,
    )
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(
        ["git", "commit", "-m", "baseline"],
        cwd=root,
        check=True,
        capture_output=True,
    )

    selected = select(root)
    (root / "src").mkdir()
    (root / "src/a.py").write_text("VALUE = 1\n")
    enter_reviewing(root, selected["run_id"])
    collect(root)
    record_json(
        root,
        "review",
        review_result(selected["run_id"]),
        "review-input.json",
    )
    (root / "implementation-input.json").unlink()
    (root / "review-input.json").unlink()
    transition(root, "A-001", "completed", "review_approved")
    sha = create(root)

    subject = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"],
        cwd=root,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    assert subject == "feat(A-001): Task A-001"
    run = json.loads(
        (
            root
            / ".harness/runs"
            / selected["run_id"]
            / "run.json"
        ).read_text()
    )
    assert "result_commit" not in run
    state = json.loads((root / ".harness/state.json").read_text())
    assert state["active_run_id"] is None
    assert state["pending_commit_task_id"] is None
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=root,
        check=True,
        text=True,
        capture_output=True,
    ).stdout
    assert status == ""
    check_repo_clean(root)
    archived = archive_completed(root)
    assert archived["archived_run_ids"] == [selected["run_id"]]
    completion = json.loads(
        (root / ".harness/completed-tasks.json").read_text()
    )["completed_tasks"][0]
    assert completion["commit"] == sha
    with pytest.raises(ValueError, match="clean worktree"):
        check_repo_clean(root)


def test_backlog_proposal_preview_confirmation_and_apply(tmp_path):
    root = fixture(tmp_path)
    proposal = root / "proposal.json"
    write_json(proposal, {"schema_version": 1, "tasks": [proposed_task()]})
    before = (root / ".harness/backlog.json").read_text()
    plan = preview_proposal(root, proposal)
    assert plan["task_count"] == 1 and len(plan["proposal_sha256"]) == 64
    assert (root / ".harness/backlog.json").read_text() == before
    with pytest.raises(ValueError, match="--confirmed"):
        apply_proposal(root, proposal, plan["proposal_sha256"], False)
    result = apply_proposal(root, proposal, plan["proposal_sha256"], True)
    assert result["appended_task_ids"] == ["GAP-001"]


def test_backlog_proposal_rejects_duplicates_unknown_profiles_and_cycles(tmp_path):
    root = fixture(tmp_path)
    proposal = root / "proposal.json"
    first = proposed_task("GAP-001", deps=["GAP-002"])
    second = proposed_task("GAP-002", deps=["GAP-001"])
    second["verification"]["profiles"] = ["missing"]
    write_json(
        proposal,
        {"schema_version": 1, "tasks": [first, second, proposed_task("GAP-001")]},
    )
    with pytest.raises(ValueError) as captured:
        preview_proposal(root, proposal)
    message = str(captured.value)
    assert "repeat" in message
    assert "unknown verification profiles" in message
    write_json(
        proposal,
        {"schema_version": 1, "tasks": [first, proposed_task("GAP-002", deps=["GAP-001"])]},
    )
    with pytest.raises(ValueError, match="cycle"):
        preview_proposal(root, proposal)


def test_backlog_status_reports_order_stalls_and_archived_counts(tmp_path):
    root = fixture(tmp_path)
    tasks = [
        task("LOW-001", priority=10),
        task("HIGH-002", priority=1),
        task("HIGH-001", priority=1),
        task("WAIT-001", deps=["BLOCK-001"]),
        task("BLOCK-001", status="blocked"),
        task("IDEA-001", status="proposed"),
    ]
    write_json(
        root / ".harness/backlog.json",
        {"schema_version": 1, "tasks": tasks},
    )
    status = backlog_status(root)
    assert status["eligible_task_ids"] == ["HIGH-001", "HIGH-002", "LOW-001"]
    assert status["unresolved"] == {
        "proposed": ["IDEA-001"],
        "blocked": ["BLOCK-001"],
        "dependency_stalled": ["WAIT-001"],
    }
    write_json(root / ".harness/backlog.json", {"schema_version": 1, "tasks": []})
    write_json(
        root / ".harness/completed-tasks.json",
        {
            "schema_version": 1,
            "completed_tasks": [
                {
                    "task_id": "DONE-001",
                    "commit": "abc123",
                    "completed_at": "2026-07-25T00:00:00Z",
                }
            ],
        },
    )
    status = backlog_status(root)
    assert status["next_action"] == "complete"
    assert status["live_task_count"] == 0
    assert status["archived_completed_task_count"] == 1


def test_review_precedes_browser_validation(tmp_path):
    root = fixture(tmp_path)
    write_json(
        root / ".harness/backlog.json",
        {"schema_version": 1, "tasks": [browser_task()]},
    )
    selected = select(root)
    enter_reviewing(root, selected["run_id"])
    with pytest.raises(ValueError, match="passed review"):
        transition(root, "A-001", "browser_validating", "premature")
    record_json(
        root,
        "review",
        review_result(selected["run_id"]),
        "review-input.json",
    )
    transition(root, "A-001", "browser_validating", "review_approved")


def test_non_browser_task_completes_after_review(tmp_path):
    root = fixture(tmp_path)
    write_json(
        root / ".harness/backlog.json",
        {"schema_version": 1, "tasks": [task("A-001")]},
    )
    selected = select(root)
    enter_reviewing(root, selected["run_id"])
    record_json(
        root,
        "review",
        review_result(selected["run_id"]),
        "review-input.json",
    )
    transition(root, "A-001", "completed", "review_approved")
    state = json.loads((root / ".harness/state.json").read_text())
    assert state["pending_commit_task_id"] == "A-001"


def test_results_are_append_only_in_run_without_duplicate_files(tmp_path):
    root = fixture(tmp_path)
    write_json(
        root / ".harness/backlog.json",
        {"schema_version": 1, "tasks": [task("A-001")]},
    )
    selected = select(root)
    record_json(
        root,
        "implementation-result",
        implementation_result(selected["run_id"]),
        "implementation-input.json",
    )
    run_dir = root / ".harness/runs" / selected["run_id"]
    run = json.loads((run_dir / "run.json").read_text())
    assert len(run["results"]["implementation"]) == 1
    assert latest_result(run, "implementation")["summary"] == "Implemented."
    assert not (run_dir / "implementation-result.json").exists()


def test_record_browser_result_requires_in_run_screenshot(tmp_path):
    root = fixture(tmp_path)
    write_json(
        root / ".harness/backlog.json",
        {"schema_version": 1, "tasks": [browser_task()]},
    )
    selected = select(root)
    enter_browser_validation(root, selected["run_id"])
    run_id = selected["run_id"]
    screenshot = f".harness/runs/{run_id}/evidence/ac1.png"
    payload = browser_result(run_id, screenshots=[screenshot])
    with pytest.raises(ValueError, match="Missing screenshot"):
        record_json(root, "browser-result", payload, "browser-input.json")
    evidence = root / ".harness/runs" / run_id / "evidence"
    evidence.mkdir()
    (evidence / "ac1.png").write_bytes(b"png")
    record_json(root, "browser-result", payload, "browser-input.json")
    run = json.loads((evidence.parent / "run.json").read_text())
    assert latest_result(run, "browser_validation")["status"] == "PASSED"
    assert not (evidence.parent / "browser-result.json").exists()


@pytest.mark.parametrize(
    "surface",
    ["browser_use", "chrome_control", "computer_use", "playwright"],
)
def test_passed_browser_result_accepts_supported_surfaces(tmp_path, surface):
    root = fixture(tmp_path)
    write_json(
        root / ".harness/backlog.json",
        {"schema_version": 1, "tasks": [browser_task()]},
    )
    selected = select(root)
    enter_browser_validation(root, selected["run_id"])
    run_id = selected["run_id"]
    evidence = root / ".harness/runs" / run_id / "evidence"
    evidence.mkdir()
    (evidence / "shot.png").write_bytes(b"png")
    screenshot = f".harness/runs/{run_id}/evidence/shot.png"
    record_json(
        root,
        "browser-result",
        browser_result(run_id, [screenshot], surface=surface),
        "browser-input.json",
    )


def test_non_product_browser_blocker_does_not_consume_retry(tmp_path):
    root = fixture(tmp_path)
    write_json(
        root / ".harness/backlog.json",
        {"schema_version": 1, "tasks": [browser_task()]},
    )
    selected = select(root)
    enter_browser_validation(root, selected["run_id"])
    payload = browser_result(
        selected["run_id"],
        status="INCOMPLETE",
        failure_class="tooling",
    )
    payload["preflight"]["tooling_ready"] = False
    payload["criteria"] = []
    record_json(root, "browser-result", payload, "browser-input.json")
    advice = retry_status(root, "browser")
    assert advice["action"] == "block"
    assert advice["counted_failures"] == 0
    with pytest.raises(ValueError, match="repair is not allowed"):
        transition(root, "A-001", "implementing", "retry")
    transition(root, "A-001", "blocked", "tooling preflight unavailable")
    assert backlog_status(root)["next_action"] == "stalled"
    state = json.loads((root / ".harness/state.json").read_text())
    assert state["active_task_id"] is None
    assert state["active_run_id"] is None


def test_browser_repair_requires_fresh_verification_and_review(tmp_path):
    root = fixture(tmp_path)
    write_json(
        root / ".harness/backlog.json",
        {"schema_version": 1, "tasks": [browser_task()]},
    )
    selected = select(root)
    enter_browser_validation(root, selected["run_id"])
    run_id = selected["run_id"]
    evidence = root / ".harness/runs" / run_id / "evidence"
    evidence.mkdir()
    (evidence / "failed.png").write_bytes(b"png")
    payload = browser_result(
        run_id,
        [f".harness/runs/{run_id}/evidence/failed.png"],
        status="FAILED",
        failure_class="product",
    )
    record_json(root, "browser-result", payload, "browser-input.json")
    assert retry_status(root, "browser")["action"] == "repair"
    transition(root, "A-001", "implementing", "browser_product_failure")
    record_json(
        root,
        "implementation-result",
        implementation_result(run_id),
        "repair-input.json",
    )
    transition(root, "A-001", "verifying", "repair_finished")
    verify(root)
    transition(root, "A-001", "reviewing", "verification_passed")
    with pytest.raises(ValueError, match="newer"):
        transition(root, "A-001", "browser_validating", "stale_review")
    with pytest.raises(ValueError, match="diff collected"):
        record_json(
            root,
            "review",
            review_result(run_id),
            "stale-diff-review-input.json",
        )
    write_diff_snapshot(root, run_id)
    record_json(
        root,
        "review",
        review_result(run_id),
        "fresh-review-input.json",
    )
    transition(root, "A-001", "browser_validating", "fresh_review_approved")


def test_migration_compacts_v1_state_and_exact_duplicate_results(tmp_path):
    root = fixture(tmp_path)
    state = {
        "schema_version": 1,
        "active_task_id": None,
        "active_run_id": None,
        "last_completed_task_id": "A-001",
        "last_completed_commit": "abc",
        "transition_history": [
            {
                "task_id": "A-001",
                "from": "ready",
                "to": "implementing",
                "reason": "selected",
                "timestamp": "2026-07-25T00:00:00Z",
            }
        ],
        "updated_at": "2026-07-25T00:00:00Z",
    }
    write_json(root / ".harness/state.json", state)
    config = json.loads((root / ".harness/config.json").read_text())
    config["repository"] = {"allowed_dirty_paths": [".harness/"]}
    config["commit"]["required"] = True
    write_json(root / ".harness/config.json", config)
    write_json(
        root / ".harness/completed-tasks.json",
        {
            "schema_version": 1,
            "completed_tasks": [
                {
                    "task_id": "A-001",
                    "commit": "abc",
                    "completed_at": "2026-07-25T00:00:00Z",
                }
            ],
        },
    )
    run_dir = root / ".harness/runs/A-001-old"
    run_dir.mkdir(parents=True)
    result = implementation_result("A-001-old")
    write_json(
        run_dir / "run.json",
        {
            "schema_version": 1,
            "run_id": "A-001-old",
            "task_id": "A-001",
            "status": "blocked",
            "started_at": "2026-07-25T00:00:00Z",
            "implementation": result,
        },
    )
    write_json(run_dir / "implementation-result.json", result)
    write_json(root / ".harness/plugin-install.json", {"plugin": "webapp-harness"})
    plan = migration_plan(root)
    assert plan["clean_lifecycle_boundary"] is True
    assert plan["state_migration_required"] is True
    assert len(plan["redundant_result_files"]) == 1
    assert plan["completed_run_directories_to_cold_store"] == [
        ".harness/runs/A-001-old"
    ]
    assert plan["unresolved_run_directories_retained"] == []
    assert plan["unused_plugin_metadata"] == [".harness/plugin-install.json"]
    assert plan["deprecated_config_fields_to_remove"] == [
        "repository",
        "commit.required",
    ]
    apply_migration(root, confirmed=True)
    archived_run = root / ".harness/archive/runs/A-001-old"
    migrated = json.loads((archived_run / "run.json").read_text())
    assert migrated["schema_version"] == 2
    assert latest_result(migrated, "implementation") == result
    assert not run_dir.exists()
    assert not (archived_run / "implementation-result.json").exists()
    assert not (root / ".harness/plugin-install.json").exists()
    assert json.loads((root / ".harness/state.json").read_text())[
        "schema_version"
    ] == 2
    migrated_config = json.loads((root / ".harness/config.json").read_text())
    assert "repository" not in migrated_config
    assert "required" not in migrated_config["commit"]


def test_reprioritize_assigns_order_and_rejects_unknown_ids(tmp_path):
    root = fixture(tmp_path)
    write_json(
        root / ".harness/backlog.json",
        {
            "schema_version": 1,
            "tasks": [
                task("A-001", priority=7),
                task("B-001", priority=3),
            ],
        },
    )
    assert reprioritize(root, ["B-001", "A-001"]) == {
        "B-001": 1,
        "A-001": 2,
    }
    with pytest.raises(ValueError, match="Unknown task IDs"):
        reprioritize(root, ["NOPE-1"])


def test_dependency_update_is_validated_and_audited(tmp_path):
    root = fixture(tmp_path)
    write_json(
        root / ".harness/backlog.json",
        {
            "schema_version": 1,
            "tasks": [
                task("A-001", deps=["B-001"]),
                task("B-001"),
            ],
        },
    )
    event = update_dependencies(root, "A-001", [], "dependency removed")
    assert event["before"] == ["B-001"] and event["after"] == []
    assert (root / ".harness/archive/task-events.jsonl").is_file()
    with pytest.raises(ValueError, match="cycle"):
        update_dependencies(root, "A-001", ["B-001"], "restore")
        update_dependencies(root, "B-001", ["A-001"], "create cycle")


def test_schema_files_are_valid_json():
    for path in (Path(__file__).parents[2] / ".harness/schema").glob("*.json"):
        json.loads(path.read_text())
