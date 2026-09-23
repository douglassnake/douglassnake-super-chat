from __future__ import annotations

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
from tests.test_m8_11_explicit_commit import (
    _apply_approved_change,
    _create_commit_request,
)


def _setup_publish_candidate(
    client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    slug: str,
    branch_name: str,
) -> dict:
    root = tmp_path / "root"
    staging_root = tmp_path / "staging"
    staging_root.mkdir()
    git, repo, base_sha, current_branch = _prepare_repo(root)

    remote = tmp_path / "remote.git"
    subprocess.run([git, "init", "--bare", "-q", str(remote)], check=True)

    execution = setup_execution(
        client,
        slug,
        [
            "modify_worktree",
            "create_branch",
            "apply_git_change",
            "create_commit",
            "publish_branch",
        ],
    )
    adapter = make_apply_adapter(root, staging_root)
    adapter.git_publish_remote_raw = str(remote.resolve())
    adapter.git_publish_remote_id = "test-bare"
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
    stage = {
        "root": root,
        "staging_root": staging_root,
        "git": git,
        "repo": repo,
        "remote": remote,
        "base_sha": base_sha,
        "current_branch": current_branch,
        "execution": execution,
        "approval": approval,
        "branch_request": branch_request,
        "apply_request": apply_request,
        "staging": staging_root / f"approval-{approval['id']}",
    }

    commit_created = _create_commit_request(client, stage, "feat: publish candidate")
    assert commit_created.status_code == 201
    commit_request_id = commit_created.json()["id"]
    assert client.post(f"/executor-requests/{commit_request_id}/release").status_code == 200
    commit_executed = client.post(f"/executor-requests/{commit_request_id}/execute")
    assert commit_executed.status_code == 200
    assert commit_executed.json()["status"] == "completed"
    assert commit_executed.json()["result"]["status"] == "committed_local"
    stage["commit_request"] = commit_executed.json()
    stage["commit_sha"] = commit_executed.json()["result"]["commit_sha"]
    stage["adapter"] = adapter
    return stage


def _publish_request(client: TestClient, stage: dict, extra: dict | None = None):
    payload = {"commit_request_id": stage["commit_request"]["id"]}
    payload.update(extra or {})
    return client.post(
        f"/agent-executions/{stage['execution']['id']}/executor-requests",
        json={
            "action": "publish_branch",
            "adapter_type": "isolated-local",
            "payload": payload,
        },
    )


def _remote_sha(stage: dict, branch_name: str) -> str | None:
    output = subprocess.check_output(
        [
            stage["git"],
            "ls-remote",
            "--heads",
            str(stage["remote"]),
            f"refs/heads/{branch_name}",
        ],
        text=True,
    ).strip()
    if not output:
        return None
    return output.split()[0]


def test_publish_branch_requires_own_release_and_publishes_exact_commit(
    apply_client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = apply_client
    branch = "superchat/m8-12-test"
    stage = _setup_publish_candidate(
        client,
        tmp_path,
        monkeypatch,
        slug="publish-m8-12",
        branch_name=branch,
    )

    created = _publish_request(client, stage)
    assert created.status_code == 201
    request = created.json()
    assert request["payload"]["branch_name"] == branch
    assert request["payload"]["commit_sha"] == stage["commit_sha"]
    assert "remote_path" not in request["payload"]
    assert "remote_id" not in request["payload"]

    assert _remote_sha(stage, branch) is None
    before_release = client.post(f"/executor-requests/{request['id']}/execute")
    assert before_release.status_code == 409
    assert _remote_sha(stage, branch) is None

    assert client.post(f"/executor-requests/{request['id']}/release").status_code == 200
    executed = client.post(f"/executor-requests/{request['id']}/execute")
    assert executed.status_code == 200
    body = executed.json()
    assert body["status"] == "completed"
    result = body["result"]
    assert result["status"] == "published_remote"
    assert result["remote_id"] == "test-bare"
    assert result["branch_name"] == branch
    assert result["commit_sha"] == stage["commit_sha"]
    assert result["remote_sha"] == stage["commit_sha"]
    assert result["remote_publication_performed"] is True
    assert result["push_performed"] is False
    assert result["receive_pack_used"] is False
    assert result["pull_request_created"] is False
    assert result["force_used"] is False
    assert result["transport"] == "local_bundle_fetch_update_ref_cas"
    assert result["network_policy"] == "local_filesystem_remote_only"
    assert _remote_sha(stage, branch) == stage["commit_sha"]
    assert str(stage["remote"]) not in str(body)


def test_publish_branch_rejects_remote_refspec_force_and_credentials_from_client(
    apply_client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stage = _setup_publish_candidate(
        apply_client,
        tmp_path,
        monkeypatch,
        slug="publish-injection-m8-12",
        branch_name="superchat/publish-injection-m8-12",
    )
    for key, value in (
        ("remote_url", "ssh://example.invalid/repo"),
        ("refspec", "+HEAD:refs/heads/main"),
        ("force", True),
        ("token", "never-accepted"),
    ):
        response = _publish_request(apply_client, stage, {key: value})
        assert response.status_code in {409, 422}
        assert "only commit_request_id" in str(response.json()).lower() or "arbitrary" in str(response.json()).lower()


def test_publish_branch_refuses_existing_remote_ref_without_overwrite(
    apply_client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = apply_client
    branch = "superchat/existing-remote-m8-12"
    stage = _setup_publish_candidate(
        client,
        tmp_path,
        monkeypatch,
        slug="publish-conflict-m8-12",
        branch_name=branch,
    )
    subprocess.run(
        [
            stage["git"],
            "-C",
            str(stage["repo"]),
            "push",
            "-q",
            str(stage["remote"]),
            f"{stage['commit_sha']}:refs/heads/{branch}",
        ],
        check=True,
    )
    before = _remote_sha(stage, branch)
    assert before == stage["commit_sha"]

    created = _publish_request(client, stage)
    assert created.status_code == 201
    request_id = created.json()["id"]
    assert client.post(f"/executor-requests/{request_id}/release").status_code == 200
    executed = client.post(f"/executor-requests/{request_id}/execute")
    assert executed.status_code == 200
    body = executed.json()
    assert body["status"] == "failed"
    assert body["result"]["status"] == "conflict"
    assert body["result"]["external_effects"] is False
    assert _remote_sha(stage, branch) == before


def test_publish_branch_rejects_local_branch_drift_before_remote_effect(
    apply_client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = apply_client
    branch = "superchat/publish-drift-m8-12"
    stage = _setup_publish_candidate(
        client,
        tmp_path,
        monkeypatch,
        slug="publish-drift-m8-12",
        branch_name=branch,
    )
    subprocess.run(
        [
            stage["git"],
            "-C",
            str(stage["repo"]),
            "update-ref",
            f"refs/heads/{branch}",
            stage["base_sha"],
            stage["commit_sha"],
        ],
        check=True,
    )

    created = _publish_request(client, stage)
    assert created.status_code == 201
    request_id = created.json()["id"]
    client.post(f"/executor-requests/{request_id}/release")
    executed = client.post(f"/executor-requests/{request_id}/execute")
    assert executed.status_code == 200
    assert executed.json()["status"] == "failed"
    assert executed.json()["result"]["status"] == "drift_detected"
    assert _remote_sha(stage, branch) is None


def test_publish_branch_does_not_execute_push_receive_or_reference_hooks(
    apply_client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = apply_client
    branch = "superchat/publish-hooks-m8-12"
    stage = _setup_publish_candidate(
        client,
        tmp_path,
        monkeypatch,
        slug="publish-hooks-m8-12",
        branch_name=branch,
    )

    pre_push_marker = tmp_path / "pre-push-ran.txt"
    receive_marker = tmp_path / "pre-receive-ran.txt"
    reference_marker = tmp_path / "reference-transaction-ran.txt"

    pre_push = stage["repo"] / ".git" / "hooks" / "pre-push"
    pre_push.write_text(
        f"#!/bin/sh\necho pre-push > '{pre_push_marker}'\nexit 1\n",
        encoding="utf-8",
    )
    pre_push.chmod(pre_push.stat().st_mode | stat.S_IXUSR)

    pre_receive = stage["remote"] / "hooks" / "pre-receive"
    pre_receive.write_text(
        f"#!/bin/sh\necho pre-receive > '{receive_marker}'\nexit 1\n",
        encoding="utf-8",
    )
    pre_receive.chmod(pre_receive.stat().st_mode | stat.S_IXUSR)

    reference_hook = stage["remote"] / "hooks" / "reference-transaction"
    reference_hook.write_text(
        f"#!/bin/sh\necho reference > '{reference_marker}'\nexit 1\n",
        encoding="utf-8",
    )
    reference_hook.chmod(reference_hook.stat().st_mode | stat.S_IXUSR)

    created = _publish_request(client, stage)
    assert created.status_code == 201
    request_id = created.json()["id"]
    assert client.post(f"/executor-requests/{request_id}/release").status_code == 200
    executed = client.post(f"/executor-requests/{request_id}/execute")
    assert executed.status_code == 200
    assert executed.json()["status"] == "completed"
    result = executed.json()["result"]
    assert result["push_performed"] is False
    assert result["receive_pack_used"] is False
    assert _remote_sha(stage, branch) == stage["commit_sha"]
    assert not pre_push_marker.exists()
    assert not receive_marker.exists()
    assert not reference_marker.exists()
