from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.executor_routes as executor_routes_module
import app.github_publish_resolver as github_publish_resolver_module
from app.core.config import Settings
from app.credential_broker import SecretLease
from app.github_publish_executor import (
    GitHubBranchPublishExecutorAdapter,
    GitHubPublishError,
)
from tests.test_m8_9_reviewed_git_branch import _prepare_repo, setup_execution
from tests.test_m8_10_apply_approved_change import (
    apply_client,
    make_apply_adapter,
    prepare_approved_proposal_and_branch,
)
from tests.test_m8_11_explicit_commit import _apply_approved_change, _create_commit_request
from tests.test_m8_12_publish_branch import _publish_request


REPOSITORY = "douglassnake/test-super-chat-publish"
SECRET = "M8_14_SERVER_ONLY_TOKEN_XYZ"


class FakeBroker:
    def __init__(self, secret: str = SECRET) -> None:
        self.secret = secret
        self.calls: list[str] = []

    def acquire_github_publish_token(self, repository: str) -> SecretLease:
        self.calls.append(repository)
        return SecretLease(self.secret)


class FakePublisher:
    def __init__(self, *, cleanup_fails: bool = False) -> None:
        self.branches: dict[str, str] = {}
        self.cleanup_fails = cleanup_fails
        self.stage_calls = 0
        self.create_calls = 0
        self.delete_calls = 0

    def get_branch_head(self, repository: str, branch: str) -> str | None:
        assert repository == REPOSITORY
        return self.branches.get(branch)

    def stage_exact_commit(
        self,
        source_bare: Path,
        repository: str,
        *,
        commit_sha: str,
        staging_branch: str,
    ) -> None:
        assert repository == REPOSITORY
        assert source_bare.is_dir()
        if staging_branch in self.branches:
            raise GitHubPublishError("staging collision")
        self.stage_calls += 1
        self.branches[staging_branch] = commit_sha

    def create_branch_ref(self, repository: str, *, branch: str, commit_sha: str) -> None:
        assert repository == REPOSITORY
        if branch in self.branches:
            raise GitHubPublishError("branch already exists")
        self.create_calls += 1
        self.branches[branch] = commit_sha

    def delete_branch_ref(self, repository: str, *, branch: str) -> None:
        assert repository == REPOSITORY
        self.delete_calls += 1
        if self.cleanup_fails:
            raise GitHubPublishError("cleanup failed")
        self.branches.pop(branch, None)


def _settings(remote: Path) -> Settings:
    return Settings(
        _env_file=None,
        executor_github_publish_enabled=True,
        executor_github_publish_token=SECRET,
        executor_github_publish_repository=REPOSITORY,
        executor_git_publish_remote=str(remote),
    )


def _setup_m814_stage(
    client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    slug: str,
    branch_name: str,
) -> dict[str, Any]:
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
            "publish_github_branch",
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
    stage: dict[str, Any] = {
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
        "branch_name": branch_name,
    }

    commit_created = _create_commit_request(client, stage, "feat: M8.14 publish candidate")
    assert commit_created.status_code == 201
    commit_id = commit_created.json()["id"]
    assert client.post(f"/executor-requests/{commit_id}/release").status_code == 200
    commit_done = client.post(f"/executor-requests/{commit_id}/execute")
    assert commit_done.status_code == 200
    assert commit_done.json()["status"] == "completed"
    stage["commit_request"] = commit_done.json()
    stage["commit_sha"] = commit_done.json()["result"]["commit_sha"]
    stage["adapter"] = isolated

    local_publish = _publish_request(client, stage)
    assert local_publish.status_code == 201
    local_publish_id = local_publish.json()["id"]
    assert client.post(f"/executor-requests/{local_publish_id}/release").status_code == 200
    local_done = client.post(f"/executor-requests/{local_publish_id}/execute")
    assert local_done.status_code == 200
    assert local_done.json()["status"] == "completed"
    assert local_done.json()["result"]["remote_sha"] == stage["commit_sha"]
    stage["publish_request"] = local_done.json()

    source = client.post(
        f"/projects/{execution['project_id']}/sources",
        json={
            "source_type": "github",
            "external_id": REPOSITORY,
            "url": f"https://github.com/{REPOSITORY}",
            "label": "GitHub publish target test",
            "metadata_json": {"default_branch": "main"},
            "is_active": True,
        },
    )
    assert source.status_code == 201
    stage["source"] = source.json()
    return stage


def _install_github_publish_adapter(
    monkeypatch: pytest.MonkeyPatch,
    stage: dict[str, Any],
    publisher: FakePublisher,
    *,
    broker: FakeBroker | None = None,
) -> tuple[GitHubBranchPublishExecutorAdapter, FakeBroker, list[str]]:
    settings = _settings(stage["remote"])
    monkeypatch.setattr(github_publish_resolver_module, "get_settings", lambda: settings)
    broker = broker or FakeBroker()
    revealed_to_factory: list[str] = []

    def factory(token: str) -> FakePublisher:
        revealed_to_factory.append(token)
        return publisher

    adapter = GitHubBranchPublishExecutorAdapter(
        enabled=True,
        repository=REPOSITORY,
        source_bare=str(stage["remote"]),
        broker=broker,
        publisher_factory=factory,
    )
    monkeypatch.setattr(executor_routes_module, "resolve_executor_adapter", lambda _: adapter)
    return adapter, broker, revealed_to_factory


def _create_github_publish_request(
    client: TestClient,
    stage: dict[str, Any],
    extra: dict[str, Any] | None = None,
):
    payload: dict[str, Any] = {"publish_request_id": stage["publish_request"]["id"]}
    payload.update(extra or {})
    return client.post(
        f"/agent-executions/{stage['execution']['id']}/executor-requests",
        json={
            "action": "publish_github_branch",
            "adapter_type": "github-publish",
            "payload": payload,
        },
    )


def test_publish_github_branch_requires_release_and_keeps_secret_out_of_state(
    apply_client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = apply_client
    stage = _setup_m814_stage(
        client,
        tmp_path,
        monkeypatch,
        slug="github-publish-m8-14",
        branch_name="superchat/github-publish-m8-14",
    )
    publisher = FakePublisher()
    _adapter, broker, revealed = _install_github_publish_adapter(monkeypatch, stage, publisher)

    created = _create_github_publish_request(client, stage)
    assert created.status_code == 201
    request = created.json()
    assert request["payload"]["repository"] == REPOSITORY
    assert request["payload"]["head_sha"] == stage["commit_sha"]
    assert SECRET not in str(request)
    assert str(stage["remote"]) not in str(request)

    assert client.post(f"/executor-requests/{request['id']}/execute").status_code == 409
    assert publisher.create_calls == 0
    assert client.post(f"/executor-requests/{request['id']}/release").status_code == 200
    executed = client.post(f"/executor-requests/{request['id']}/execute")
    assert executed.status_code == 200
    body = executed.json()
    assert body["status"] == "completed"
    result = body["result"]
    assert result["status"] == "github_branch_published"
    assert result["head_sha"] == stage["commit_sha"]
    assert result["temporary_ref_cleaned"] is True
    assert result["pull_request_created"] is False
    assert result["merge_performed"] is False
    assert result["deploy_performed"] is False
    assert publisher.branches[stage["branch_name"]] == stage["commit_sha"]
    assert not any(key.startswith("superchat-staging/") for key in publisher.branches)
    assert broker.calls == [REPOSITORY]
    assert revealed == [SECRET]
    assert SECRET not in str(body)


def test_publish_github_branch_rejects_client_repository_sha_token_and_refspec(
    apply_client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stage = _setup_m814_stage(
        apply_client,
        tmp_path,
        monkeypatch,
        slug="github-publish-injection-m8-14",
        branch_name="superchat/github-publish-injection-m8-14",
    )
    publisher = FakePublisher()
    _install_github_publish_adapter(monkeypatch, stage, publisher)
    response = _create_github_publish_request(
        apply_client,
        stage,
        {
            "repository": "attacker/repo",
            "head_sha": "0" * 40,
            "token": "client-token",
            "refspec": "+HEAD:refs/heads/main",
        },
    )
    assert response.status_code == 409
    assert "only publish_request_id" in str(response.json()).lower()
    assert publisher.stage_calls == 0


def test_publish_github_branch_blocks_local_bare_drift_before_broker_use(
    apply_client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stage = _setup_m814_stage(
        apply_client,
        tmp_path,
        monkeypatch,
        slug="github-publish-local-drift-m8-14",
        branch_name="superchat/github-publish-local-drift-m8-14",
    )
    publisher = FakePublisher()
    _adapter, broker, _revealed = _install_github_publish_adapter(monkeypatch, stage, publisher)
    subprocess.run(
        [
            stage["git"],
            "-C",
            str(stage["remote"]),
            "update-ref",
            f"refs/heads/{stage['branch_name']}",
            stage["base_sha"],
            stage["commit_sha"],
        ],
        check=True,
    )

    created = _create_github_publish_request(apply_client, stage)
    assert created.status_code == 201
    request_id = created.json()["id"]
    apply_client.post(f"/executor-requests/{request_id}/release")
    executed = apply_client.post(f"/executor-requests/{request_id}/execute")
    assert executed.status_code == 200
    assert executed.json()["status"] == "failed"
    assert executed.json()["result"]["status"] == "local_source_drift_detected"
    assert broker.calls == []
    assert publisher.stage_calls == 0


def test_publish_github_branch_refuses_existing_github_target_without_effect(
    apply_client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stage = _setup_m814_stage(
        apply_client,
        tmp_path,
        monkeypatch,
        slug="github-publish-existing-m8-14",
        branch_name="superchat/github-publish-existing-m8-14",
    )
    publisher = FakePublisher()
    publisher.branches[stage["branch_name"]] = "e" * 40
    _install_github_publish_adapter(monkeypatch, stage, publisher)

    created = _create_github_publish_request(apply_client, stage)
    assert created.status_code == 201
    request_id = created.json()["id"]
    apply_client.post(f"/executor-requests/{request_id}/release")
    executed = apply_client.post(f"/executor-requests/{request_id}/execute")
    assert executed.status_code == 200
    assert executed.json()["status"] == "failed"
    assert executed.json()["result"]["status"] == "github_branch_already_exists"
    assert publisher.stage_calls == 0
    assert publisher.create_calls == 0


def test_publish_github_branch_cleanup_failure_requires_manual_reconciliation(
    apply_client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stage = _setup_m814_stage(
        apply_client,
        tmp_path,
        monkeypatch,
        slug="github-publish-cleanup-m8-14",
        branch_name="superchat/github-publish-cleanup-m8-14",
    )
    publisher = FakePublisher(cleanup_fails=True)
    _install_github_publish_adapter(monkeypatch, stage, publisher)

    created = _create_github_publish_request(apply_client, stage)
    assert created.status_code == 201
    request_id = created.json()["id"]
    apply_client.post(f"/executor-requests/{request_id}/release")
    executed = apply_client.post(f"/executor-requests/{request_id}/execute")
    assert executed.status_code == 200
    body = executed.json()
    assert body["status"] == "failed"
    assert body["result"]["status"] == "temporary_ref_cleanup_failed"
    assert body["result"]["manual_reconciliation_required"] is True
    assert body["result"]["final_branch_created"] is True
    assert publisher.branches[stage["branch_name"]] == stage["commit_sha"]
    assert any(key.startswith("superchat-staging/") for key in publisher.branches)
