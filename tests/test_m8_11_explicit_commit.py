from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess

import pytest
from fastapi.testclient import TestClient

import app.executor_routes as executor_routes_module
from tests.test_m8_9_reviewed_git_branch import _prepare_repo, setup_execution
from tests.test_m8_10_apply_approved_change import (
    apply_client,
    make_apply_adapter,
    prepare_approved_proposal_and_branch,
)


def _apply_approved_change(
    client: TestClient,
    execution: dict,
    approval: dict,
    branch_request: dict,
) -> dict:
    created = client.post(
        f"/agent-executions/{execution['id']}/executor-requests",
        json={
            "action": "apply_git_change",
            "adapter_type": "isolated-local",
            "payload": {
                "approval_id": approval["id"],
                "branch_request_id": branch_request["id"],
            },
        },
    )
    assert created.status_code == 201
    request_id = created.json()["id"]
    assert client.post(f"/executor-requests/{request_id}/release").status_code == 200
    executed = client.post(f"/executor-requests/{request_id}/execute")
    assert executed.status_code == 200
    assert executed.json()["status"] == "completed"
    assert executed.json()["result"]["status"] == "applied_uncommitted"
    return executed.json()


def _setup_commit_stage(
    client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    slug: str,
    branch_name: str,
):
    root = tmp_path / "root"
    staging_root = tmp_path / "staging"
    staging_root.mkdir()
    git, repo, base_sha, current_branch = _prepare_repo(root)
    source_before = (repo / "tracked.txt").read_bytes()
    execution = setup_execution(
        client,
        slug,
        ["modify_worktree", "create_branch", "apply_git_change", "create_commit"],
    )
    adapter = make_apply_adapter(root, staging_root)
    monkeypatch.setattr(
        executor_routes_module,
        "resolve_executor_adapter",
        lambda _: adapter,
    )
    _proposal, approval, branch_request = prepare_approved_proposal_and_branch(
        client,
        execution,
        branch_name=branch_name,
    )
    apply_request = _apply_approved_change(
        client,
        execution,
        approval,
        branch_request,
    )
    staging = staging_root / f"approval-{approval['id']}"
    assert staging.is_dir()
    return {
        "root": root,
        "staging_root": staging_root,
        "git": git,
        "repo": repo,
        "base_sha": base_sha,
        "current_branch": current_branch,
        "source_before": source_before,
        "execution": execution,
        "approval": approval,
        "branch_request": branch_request,
        "apply_request": apply_request,
        "staging": staging,
    }


def _create_commit_request(client: TestClient, stage: dict, message: str = "feat: approved commit"):
    return client.post(
        f"/agent-executions/{stage['execution']['id']}/executor-requests",
        json={
            "action": "create_commit",
            "adapter_type": "isolated-local",
            "payload": {
                "apply_request_id": stage["apply_request"]["id"],
                "commit_message": message,
            },
        },
    )


def test_create_commit_is_separately_released_and_remains_local(
    apply_client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = apply_client
    stage = _setup_commit_stage(
        client,
        tmp_path,
        monkeypatch,
        slug="commit-m8-11",
        branch_name="superchat/m8-11-test",
    )
    git = stage["git"]
    repo = stage["repo"]
    staging = stage["staging"]
    base_sha = stage["base_sha"]

    created = _create_commit_request(client, stage)
    assert created.status_code == 201
    request = created.json()
    assert request["payload"]["branch_name"] == "superchat/m8-11-test"
    assert request["payload"]["base_sha"] == base_sha
    assert request["payload"]["patch_digest"] == stage["approval"]["patch_digest"]
    assert request["payload"]["changed_files"]
    assert "author_name" not in request["payload"]

    before_release = client.post(f"/executor-requests/{request['id']}/execute")
    assert before_release.status_code == 409
    assert subprocess.check_output(
        [git, "-C", str(repo), "rev-parse", "superchat/m8-11-test"], text=True
    ).strip() == base_sha

    assert client.post(f"/executor-requests/{request['id']}/release").status_code == 200
    executed = client.post(f"/executor-requests/{request['id']}/execute")
    assert executed.status_code == 200
    body = executed.json()
    assert body["status"] == "completed"
    result = body["result"]
    assert result["status"] == "committed_local"
    assert result["parent_sha"] == base_sha
    assert result["commit_sha"] != base_sha
    assert result["patch_digest"] == stage["approval"]["patch_digest"]
    assert result["commit_created"] is True
    assert result["push_performed"] is False
    assert result["pull_request_created"] is False
    assert result["author_name"] == "Super Chat Executor"
    assert result["author_email"] == "superchat-executor@localhost"
    assert result["index_policy"] == "temporary_index_approved_paths_only_no_filters"

    commit_sha = result["commit_sha"]
    assert subprocess.check_output(
        [git, "-C", str(repo), "rev-parse", "superchat/m8-11-test"], text=True
    ).strip() == commit_sha
    assert subprocess.check_output(
        [git, "-C", str(staging), "rev-parse", "HEAD"], text=True
    ).strip() == commit_sha
    assert subprocess.check_output(
        [git, "-C", str(staging), "rev-parse", "HEAD^"], text=True
    ).strip() == base_sha
    assert subprocess.check_output(
        [git, "-C", str(staging), "status", "--porcelain"], text=True
    ).strip() == ""
    changed = set(
        subprocess.check_output(
            [git, "-C", str(staging), "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"],
            text=True,
        ).splitlines()
    )
    assert changed == {"tracked.txt", "added.txt"}
    identity = subprocess.check_output(
        [git, "-C", str(staging), "show", "-s", "--format=%an%x00%ae", "HEAD"],
        text=True,
    ).strip().split("\x00")
    assert identity == ["Super Chat Executor", "superchat-executor@localhost"]

    assert (repo / "tracked.txt").read_bytes() == stage["source_before"]
    assert not (repo / "added.txt").exists()
    assert subprocess.check_output(
        [git, "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip() == base_sha
    assert subprocess.check_output(
        [git, "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"], text=True
    ).strip() == stage["current_branch"]


def test_create_commit_rejects_client_snapshot_injection(
    apply_client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stage = _setup_commit_stage(
        apply_client,
        tmp_path,
        monkeypatch,
        slug="commit-injection-m8-11",
        branch_name="superchat/commit-injection-m8-11",
    )
    injected = apply_client.post(
        f"/agent-executions/{stage['execution']['id']}/executor-requests",
        json={
            "action": "create_commit",
            "adapter_type": "isolated-local",
            "payload": {
                "apply_request_id": stage["apply_request"]["id"],
                "commit_message": "feat: approved commit",
                "branch_name": "superchat/evil",
            },
        },
    )
    assert injected.status_code == 409
    assert "accepts only" in str(injected.json()).lower()


def test_create_commit_rejects_extra_staging_file_before_ref_move(
    apply_client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = apply_client
    stage = _setup_commit_stage(
        client,
        tmp_path,
        monkeypatch,
        slug="commit-drift-m8-11",
        branch_name="superchat/commit-drift-m8-11",
    )
    (stage["staging"] / "unapproved.txt").write_text("not approved\n", encoding="utf-8")

    created = _create_commit_request(client, stage)
    assert created.status_code == 201
    request_id = created.json()["id"]
    assert client.post(f"/executor-requests/{request_id}/release").status_code == 200
    executed = client.post(f"/executor-requests/{request_id}/execute")
    assert executed.status_code == 200
    body = executed.json()
    assert body["status"] == "failed"
    assert body["result"]["status"] == "drift_detected"
    assert body["result"]["reason"] == "changed_file_inventory"
    assert subprocess.check_output(
        [stage["git"], "-C", str(stage["repo"]), "rev-parse", "superchat/commit-drift-m8-11"],
        text=True,
    ).strip() == stage["base_sha"]


def test_create_commit_does_not_execute_repository_hook_or_clean_filter(
    apply_client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = apply_client
    stage = _setup_commit_stage(
        client,
        tmp_path,
        monkeypatch,
        slug="commit-hooks-m8-11",
        branch_name="superchat/commit-hooks-m8-11",
    )
    git = stage["git"]
    repo = stage["repo"]

    hook_marker = tmp_path / "hook-ran.txt"
    filter_marker = tmp_path / "filter-ran.txt"
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text(f"#!/bin/sh\necho hook > '{hook_marker}'\nexit 1\n", encoding="utf-8")
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR)

    filter_script = tmp_path / "evil-filter.sh"
    filter_script.write_text(
        f"#!/bin/sh\necho filter > '{filter_marker}'\ncat\n",
        encoding="utf-8",
    )
    filter_script.chmod(filter_script.stat().st_mode | stat.S_IXUSR)
    subprocess.run(
        [git, "-C", str(repo), "config", "filter.evil.clean", str(filter_script)],
        check=True,
    )
    subprocess.run(
        [git, "-C", str(repo), "config", "filter.evil.required", "true"],
        check=True,
    )
    info_attributes = repo / ".git" / "info" / "attributes"
    info_attributes.parent.mkdir(parents=True, exist_ok=True)
    info_attributes.write_text("tracked.txt filter=evil\nadded.txt filter=evil\n", encoding="utf-8")

    created = _create_commit_request(client, stage, "feat: plumbing commit")
    assert created.status_code == 201
    request_id = created.json()["id"]
    client.post(f"/executor-requests/{request_id}/release")
    executed = client.post(f"/executor-requests/{request_id}/execute")
    assert executed.status_code == 200
    assert executed.json()["status"] == "completed"
    assert not hook_marker.exists()
    assert not filter_marker.exists()
