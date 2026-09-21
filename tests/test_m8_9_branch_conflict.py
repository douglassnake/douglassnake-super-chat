from __future__ import annotations

import subprocess

import pytest
from fastapi.testclient import TestClient

import app.executor_routes as executor_routes_module
from tests.test_m8_9_reviewed_git_branch import (
    _prepare_repo,
    make_adapter,
    setup_execution,
)


def test_existing_superchat_branch_is_never_overwritten(
    git_stage_client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    git, repo, head, current_branch = _prepare_repo(root)
    existing_name = "superchat/already-there"
    subprocess.run(
        [git, "-C", str(repo), "branch", existing_name, head],
        check=True,
    )
    before_sha = subprocess.check_output(
        [git, "-C", str(repo), "rev-parse", existing_name],
        text=True,
    ).strip()

    client = git_stage_client
    execution = setup_execution(client, "branch-conflict-m8-9", ["create_branch"])
    monkeypatch.setattr(
        executor_routes_module,
        "resolve_executor_adapter",
        lambda _: make_adapter(root),
    )

    request = client.post(
        f"/agent-executions/{execution['id']}/executor-requests",
        json={
            "action": "create_branch",
            "adapter_type": "isolated-local",
            "payload": {"worktree": "repo", "branch_name": existing_name},
        },
    )
    assert request.status_code == 201
    request_id = request.json()["id"]
    assert client.post(f"/executor-requests/{request_id}/release").status_code == 200

    executed = client.post(f"/executor-requests/{request_id}/execute")
    assert executed.status_code == 200
    body = executed.json()
    assert body["status"] == "failed"
    assert "already exists" in (body["error"] or "").lower()

    after_sha = subprocess.check_output(
        [git, "-C", str(repo), "rev-parse", existing_name],
        text=True,
    ).strip()
    assert after_sha == before_sha == head
    assert subprocess.check_output(
        [git, "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"],
        text=True,
    ).strip() == current_branch
