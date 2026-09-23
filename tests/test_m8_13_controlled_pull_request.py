from __future__ import annotations

import subprocess
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.executor_routes as executor_routes_module
import app.github_pr_resolver as github_pr_resolver_module
from app.core.config import Settings
from app.github_pr_executor import GitHubPullRequestExecutorAdapter
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
from tests.test_m8_12_publish_branch import _publish_request


REPOSITORY = "douglassnake/test-super-chat-pr"


class FakeGitHubPRWriter:
    def __init__(self, *, head_sha: str | None, existing: dict[str, Any] | None = None) -> None:
        self.head_sha = head_sha
        self.existing = existing
        self.create_calls = 0
        self.created_number = 101
        self.last_create: dict[str, Any] | None = None

    def get_branch_head(self, repository: str, branch: str) -> str | None:
        assert repository == REPOSITORY
        assert branch.startswith("superchat/")
        return self.head_sha

    def find_open_pull_request(
        self,
        repository: str,
        *,
        base_branch: str,
        head_branch: str,
    ) -> dict[str, Any] | None:
        assert repository == REPOSITORY
        assert base_branch == "main"
        assert head_branch.startswith("superchat/")
        return self.existing

    def create_pull_request(
        self,
        repository: str,
        *,
        title: str,
        body: str,
        base_branch: str,
        head_branch: str,
        draft: bool,
    ) -> dict[str, Any]:
        self.create_calls += 1
        self.last_create = {
            "repository": repository,
            "title": title,
            "body": body,
            "base_branch": base_branch,
            "head_branch": head_branch,
            "draft": draft,
        }
        return {"number": self.created_number}

    def get_pull_request(self, repository: str, number: int) -> dict[str, Any]:
        assert repository == REPOSITORY
        assert number == self.created_number
        assert self.last_create is not None
        return {
            "number": number,
            "draft": self.last_create["draft"],
            "head": {
                "ref": self.last_create["head_branch"],
                "sha": self.head_sha,
            },
            "base": {
                "ref": self.last_create["base_branch"],
                "repo": {"full_name": repository},
            },
        }


def _settings(*, enabled: bool = True, token: str = "SERVER_ONLY_WRITE_TOKEN") -> Settings:
    return Settings(
        _env_file=None,
        executor_github_write_enabled=enabled,
        executor_github_write_token=token,
        executor_github_write_repository=REPOSITORY,
        executor_github_pr_base_branch="main",
        executor_github_pr_draft=True,
    )


def _setup_m813_stage(
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
            "create_pull_request",
        ],
    )
    isolated = make_apply_adapter(root, staging_root)
    isolated.git_publish_remote_raw = str(remote.resolve())
    isolated.git_publish_remote_id = "test-bare"
    monkeypatch.setattr(executor_routes_module, "resolve_executor_adapter", lambda _: isolated)

    _proposal, approval, branch_request = prepare_approved_proposal_and_branch(
        client,
        execution,
        branch_name=branch_name,
    )
    apply_request = _apply_approved_change(client, execution, approval, branch_request)
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

    commit_created = _create_commit_request(client, stage, "feat: M8.13 candidate")
    assert commit_created.status_code == 201
    commit_id = commit_created.json()["id"]
    assert client.post(f"/executor-requests/{commit_id}/release").status_code == 200
    commit_done = client.post(f"/executor-requests/{commit_id}/execute")
    assert commit_done.status_code == 200
    assert commit_done.json()["status"] == "completed"
    stage["commit_request"] = commit_done.json()
    stage["commit_sha"] = commit_done.json()["result"]["commit_sha"]
    stage["adapter"] = isolated

    publish_created = _publish_request(client, stage)
    assert publish_created.status_code == 201
    publish_id = publish_created.json()["id"]
    assert client.post(f"/executor-requests/{publish_id}/release").status_code == 200
    publish_done = client.post(f"/executor-requests/{publish_id}/execute")
    assert publish_done.status_code == 200
    assert publish_done.json()["status"] == "completed"
    assert publish_done.json()["result"]["remote_sha"] == stage["commit_sha"]
    stage["publish_request"] = publish_done.json()

    source = client.post(
        f"/projects/{execution['project_id']}/sources",
        json={
            "source_type": "github",
            "external_id": REPOSITORY,
            "url": f"https://github.com/{REPOSITORY}",
            "label": "GitHub write target test",
            "metadata_json": {"default_branch": "main"},
            "is_active": True,
        },
    )
    assert source.status_code == 201
    stage["source"] = source.json()
    return stage


def _install_pr_adapter(
    monkeypatch: pytest.MonkeyPatch,
    stage: dict,
    writer: FakeGitHubPRWriter | None,
    *,
    enabled: bool = True,
    token: str = "SERVER_ONLY_WRITE_TOKEN",
) -> GitHubPullRequestExecutorAdapter:
    settings = _settings(enabled=enabled, token=token)
    monkeypatch.setattr(github_pr_resolver_module, "get_settings", lambda: settings)
    adapter = GitHubPullRequestExecutorAdapter(
        enabled=enabled,
        repository=REPOSITORY,
        base_branch="main",
        draft=True,
        writer=writer,
    )
    monkeypatch.setattr(executor_routes_module, "resolve_executor_adapter", lambda _: adapter)
    return adapter


def _create_pr_request(client: TestClient, stage: dict, payload_extra: dict[str, Any] | None = None):
    payload: dict[str, Any] = {
        "publish_request_id": stage["publish_request"]["id"],
        "title": "feat: controlled PR",
        "body": "PR criado somente após validação do head publicado.",
    }
    payload.update(payload_extra or {})
    return client.post(
        f"/agent-executions/{stage['execution']['id']}/executor-requests",
        json={
            "action": "create_pull_request",
            "adapter_type": "github-pr",
            "payload": payload,
        },
    )


def test_create_pull_request_requires_release_and_never_serializes_token(
    apply_client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = apply_client
    stage = _setup_m813_stage(
        client,
        tmp_path,
        monkeypatch,
        slug="pr-m8-13",
        branch_name="superchat/pr-m8-13",
    )
    secret = "SERVER_ONLY_WRITE_TOKEN_XYZ"
    writer = FakeGitHubPRWriter(head_sha=stage["commit_sha"])
    _install_pr_adapter(monkeypatch, stage, writer, token=secret)

    created = _create_pr_request(client, stage)
    assert created.status_code == 201
    request = created.json()
    assert request["adapter_type"] == "github-pr"
    assert request["payload"]["repository"] == REPOSITORY
    assert request["payload"]["head_branch"] == "superchat/pr-m8-13"
    assert request["payload"]["head_sha"] == stage["commit_sha"]
    assert secret not in str(request)

    assert client.post(f"/executor-requests/{request['id']}/execute").status_code == 409
    assert writer.create_calls == 0
    assert client.post(f"/executor-requests/{request['id']}/release").status_code == 200
    executed = client.post(f"/executor-requests/{request['id']}/execute")
    assert executed.status_code == 200
    body = executed.json()
    assert body["status"] == "completed"
    result = body["result"]
    assert result["status"] == "pull_request_created"
    assert result["pull_request_number"] == 101
    assert result["pull_request_url"] == f"https://github.com/{REPOSITORY}/pull/101"
    assert result["head_sha"] == stage["commit_sha"]
    assert result["merge_performed"] is False
    assert result["deploy_performed"] is False
    assert writer.create_calls == 1
    assert secret not in str(body)


def test_create_pull_request_fails_closed_when_head_is_not_on_github(
    apply_client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stage = _setup_m813_stage(
        apply_client,
        tmp_path,
        monkeypatch,
        slug="pr-missing-head-m8-13",
        branch_name="superchat/pr-missing-head-m8-13",
    )
    writer = FakeGitHubPRWriter(head_sha=None)
    _install_pr_adapter(monkeypatch, stage, writer)
    created = _create_pr_request(apply_client, stage)
    assert created.status_code == 201
    request_id = created.json()["id"]
    assert apply_client.post(f"/executor-requests/{request_id}/release").status_code == 200
    executed = apply_client.post(f"/executor-requests/{request_id}/execute")
    assert executed.status_code == 200
    assert executed.json()["status"] == "failed"
    assert executed.json()["result"]["status"] == "head_not_published_to_github"
    assert executed.json()["result"]["external_effects"] is False
    assert writer.create_calls == 0


def test_create_pull_request_rejects_head_drift(
    apply_client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stage = _setup_m813_stage(
        apply_client,
        tmp_path,
        monkeypatch,
        slug="pr-drift-m8-13",
        branch_name="superchat/pr-drift-m8-13",
    )
    writer = FakeGitHubPRWriter(head_sha="f" * 40)
    _install_pr_adapter(monkeypatch, stage, writer)
    created = _create_pr_request(apply_client, stage)
    assert created.status_code == 201
    request_id = created.json()["id"]
    apply_client.post(f"/executor-requests/{request_id}/release")
    executed = apply_client.post(f"/executor-requests/{request_id}/execute")
    assert executed.status_code == 200
    assert executed.json()["status"] == "failed"
    assert executed.json()["result"]["status"] == "head_drift_detected"
    assert writer.create_calls == 0


def test_create_pull_request_rejects_client_repository_sha_and_token_injection(
    apply_client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stage = _setup_m813_stage(
        apply_client,
        tmp_path,
        monkeypatch,
        slug="pr-injection-m8-13",
        branch_name="superchat/pr-injection-m8-13",
    )
    writer = FakeGitHubPRWriter(head_sha=stage["commit_sha"])
    _install_pr_adapter(monkeypatch, stage, writer)
    response = _create_pr_request(
        apply_client,
        stage,
        {
            "repository": "attacker/repo",
            "head_sha": "0" * 40,
            "token": "client-secret",
        },
    )
    assert response.status_code == 409
    assert "accepts only" in str(response.json()).lower()
    assert writer.create_calls == 0


def test_create_pull_request_blocks_second_request_for_same_publication(
    apply_client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stage = _setup_m813_stage(
        apply_client,
        tmp_path,
        monkeypatch,
        slug="pr-replay-m8-13",
        branch_name="superchat/pr-replay-m8-13",
    )
    writer = FakeGitHubPRWriter(head_sha=stage["commit_sha"])
    _install_pr_adapter(monkeypatch, stage, writer)
    created = _create_pr_request(apply_client, stage)
    assert created.status_code == 201
    request_id = created.json()["id"]
    apply_client.post(f"/executor-requests/{request_id}/release")
    done = apply_client.post(f"/executor-requests/{request_id}/execute")
    assert done.status_code == 200
    assert done.json()["status"] == "completed"

    second = _create_pr_request(
        apply_client,
        stage,
        {"title": "different title, same publication"},
    )
    assert second.status_code == 409
    assert "already exists" in str(second.json()).lower()
    assert writer.create_calls == 1


def test_create_pull_request_writer_is_disabled_by_default_gate(
    apply_client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stage = _setup_m813_stage(
        apply_client,
        tmp_path,
        monkeypatch,
        slug="pr-disabled-m8-13",
        branch_name="superchat/pr-disabled-m8-13",
    )
    settings = _settings(enabled=False)
    monkeypatch.setattr(github_pr_resolver_module, "get_settings", lambda: settings)
    unavailable = GitHubPullRequestExecutorAdapter(
        enabled=False,
        repository=REPOSITORY,
        base_branch="main",
        draft=True,
        writer=None,
    )
    monkeypatch.setattr(executor_routes_module, "resolve_executor_adapter", lambda _: unavailable)

    created = _create_pr_request(apply_client, stage)
    assert created.status_code == 201
    request_id = created.json()["id"]
    assert apply_client.post(f"/executor-requests/{request_id}/release").status_code == 200
    executed = apply_client.post(f"/executor-requests/{request_id}/execute")
    assert executed.status_code == 409
    assert "not configured" in str(executed.json()).lower()
