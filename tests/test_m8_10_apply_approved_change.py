from __future__ import annotations

from collections.abc import Generator
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.executor_routes as executor_routes_module
from app.database import Base, get_db
from app.isolated_executor import IsolatedLocalExecutorAdapter
from app.main import app
from tests.test_m8_9_reviewed_git_branch import _prepare_repo, setup_execution


@pytest.fixture()
def apply_client() -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    Base.metadata.create_all(bind=engine)

    def override_get_db() -> Generator[Session, None, None]:
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def make_apply_adapter(root, staging_root) -> IsolatedLocalExecutorAdapter:
    return IsolatedLocalExecutorAdapter(
        enabled=True,
        worktree_root=str(root),
        timeout_seconds=8,
        max_timeout_seconds=15,
        output_max_bytes=16_384,
        env_allowlist="",
        worker_backend="subprocess-sandbox",
        worker_cpu_seconds=30,
        worker_memory_mb=512,
        worker_pids=64,
        worker_nofile=128,
        worker_file_size_mb=16,
        modify_max_files=10,
        modify_max_operations=20,
        modify_max_total_write_bytes=8192,
        modify_max_patch_bytes=8192,
        git_staging_root=str(staging_root),
    )


def prepare_approved_proposal_and_branch(
    client: TestClient,
    execution: dict,
    *,
    branch_name: str = "superchat/m8-10-test",
) -> tuple[dict, dict, dict]:
    proposal_request = client.post(
        f"/agent-executions/{execution['id']}/executor-requests",
        json={
            "action": "modify_worktree",
            "adapter_type": "isolated-local",
            "payload": {
                "worktree": "repo",
                "operations": [
                    {
                        "op": "write_text",
                        "path": "tracked.txt",
                        "content": "approved-change\n",
                    },
                    {
                        "op": "write_text",
                        "path": "added.txt",
                        "content": "new approved file\n",
                    },
                ],
            },
        },
    )
    assert proposal_request.status_code == 201
    proposal_id = proposal_request.json()["id"]
    assert client.post(f"/executor-requests/{proposal_id}/release").status_code == 200
    proposed = client.post(f"/executor-requests/{proposal_id}/execute")
    assert proposed.status_code == 200
    assert proposed.json()["status"] == "completed"

    prepared = client.post(f"/executor-requests/{proposal_id}/git-change-approval")
    assert prepared.status_code == 201
    approval = prepared.json()
    approved = client.post(
        f"/git-change-approvals/{approval['id']}/approve",
        json={"patch_digest": approval["patch_digest"]},
    )
    assert approved.status_code == 200

    branch_request = client.post(
        f"/agent-executions/{execution['id']}/executor-requests",
        json={
            "action": "create_branch",
            "adapter_type": "isolated-local",
            "payload": {"worktree": "repo", "branch_name": branch_name},
        },
    )
    assert branch_request.status_code == 201
    branch_id = branch_request.json()["id"]
    assert client.post(f"/executor-requests/{branch_id}/release").status_code == 200
    branch_done = client.post(f"/executor-requests/{branch_id}/execute")
    assert branch_done.status_code == 200
    assert branch_done.json()["status"] == "completed"
    return proposed.json(), approved.json(), branch_done.json()


def test_apply_approved_change_only_mutates_dedicated_staging_worktree(
    apply_client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    staging_root = tmp_path / "staging"
    staging_root.mkdir()
    git, repo, base_sha, current_branch = _prepare_repo(root)
    source_before = (repo / "tracked.txt").read_bytes()

    client = apply_client
    execution = setup_execution(
        client,
        "apply-m8-10",
        ["modify_worktree", "create_branch", "apply_git_change"],
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
    )

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
    request = created.json()
    assert request["payload"]["patch_digest"] == approval["patch_digest"]
    assert request["payload"]["branch_name"] == "superchat/m8-10-test"
    assert request["payload"]["base_sha"] == base_sha
    assert request["payload"]["operations"]

    assert client.post(f"/executor-requests/{request['id']}/release").status_code == 200
    executed = client.post(f"/executor-requests/{request['id']}/execute")
    assert executed.status_code == 200
    body = executed.json()
    assert body["status"] == "completed"
    result = body["result"]
    assert result["status"] == "applied_uncommitted"
    assert result["patch_digest"] == approval["patch_digest"]
    assert result["base_sha"] == base_sha
    assert result["commit_created"] is False
    assert result["push_performed"] is False
    assert result["pull_request_created"] is False
    assert result["source_content_changed"] is False
    assert result["git_status"]

    staging = staging_root / f"approval-{approval['id']}"
    assert staging.is_dir()
    assert (staging / "tracked.txt").read_text(encoding="utf-8") == "approved-change\n"
    assert (staging / "added.txt").read_text(encoding="utf-8") == "new approved file\n"
    assert subprocess.check_output(
        [git, "-C", str(staging), "rev-parse", "HEAD"], text=True
    ).strip() == base_sha
    assert subprocess.check_output(
        [git, "-C", str(repo), "rev-parse", "superchat/m8-10-test"], text=True
    ).strip() == base_sha

    assert (repo / "tracked.txt").read_bytes() == source_before
    assert not (repo / "added.txt").exists()
    assert subprocess.check_output(
        [git, "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"], text=True
    ).strip() == current_branch
    assert subprocess.check_output(
        [git, "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip() == base_sha


def test_apply_request_rejects_pending_approval_and_client_injection(
    apply_client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    staging_root = tmp_path / "staging"
    staging_root.mkdir()
    _git, _repo, _base, _current = _prepare_repo(root)
    client = apply_client
    execution = setup_execution(
        client,
        "pending-m8-10",
        ["modify_worktree", "create_branch", "apply_git_change"],
    )
    monkeypatch.setattr(
        executor_routes_module,
        "resolve_executor_adapter",
        lambda _: make_apply_adapter(root, staging_root),
    )

    proposal_request = client.post(
        f"/agent-executions/{execution['id']}/executor-requests",
        json={
            "action": "modify_worktree",
            "adapter_type": "isolated-local",
            "payload": {
                "worktree": "repo",
                "operations": [
                    {"op": "write_text", "path": "tracked.txt", "content": "pending\n"}
                ],
            },
        },
    ).json()
    client.post(f"/executor-requests/{proposal_request['id']}/release")
    client.post(f"/executor-requests/{proposal_request['id']}/execute")
    approval = client.post(
        f"/executor-requests/{proposal_request['id']}/git-change-approval"
    ).json()

    branch_request = client.post(
        f"/agent-executions/{execution['id']}/executor-requests",
        json={
            "action": "create_branch",
            "adapter_type": "isolated-local",
            "payload": {"worktree": "repo", "branch_name": "superchat/pending-m8-10"},
        },
    ).json()
    client.post(f"/executor-requests/{branch_request['id']}/release")
    branch_done = client.post(f"/executor-requests/{branch_request['id']}/execute").json()

    pending = client.post(
        f"/agent-executions/{execution['id']}/executor-requests",
        json={
            "action": "apply_git_change",
            "adapter_type": "isolated-local",
            "payload": {
                "approval_id": approval["id"],
                "branch_request_id": branch_done["id"],
            },
        },
    )
    assert pending.status_code == 409
    assert "approved is required" in str(pending.json()).lower()

    client.post(
        f"/git-change-approvals/{approval['id']}/approve",
        json={"patch_digest": approval["patch_digest"]},
    )
    injected = client.post(
        f"/agent-executions/{execution['id']}/executor-requests",
        json={
            "action": "apply_git_change",
            "adapter_type": "isolated-local",
            "payload": {
                "approval_id": approval["id"],
                "branch_request_id": branch_done["id"],
                "operations": [{"op": "write_text", "path": "evil.txt", "content": "x"}],
            },
        },
    )
    assert injected.status_code == 409
    assert "accepts only" in str(injected.json()).lower()


def test_apply_detects_branch_drift_before_staging_content_write(
    apply_client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    staging_root = tmp_path / "staging"
    staging_root.mkdir()
    git, repo, original_base, _current = _prepare_repo(root)
    client = apply_client
    execution = setup_execution(
        client,
        "drift-m8-10",
        ["modify_worktree", "create_branch", "apply_git_change"],
    )
    monkeypatch.setattr(
        executor_routes_module,
        "resolve_executor_adapter",
        lambda _: make_apply_adapter(root, staging_root),
    )
    _proposal, approval, branch_request = prepare_approved_proposal_and_branch(
        client,
        execution,
        branch_name="superchat/drift-m8-10",
    )

    (repo / "unrelated.txt").write_text("new base\n", encoding="utf-8")
    subprocess.run([git, "-C", str(repo), "add", "unrelated.txt"], check=True)
    subprocess.run([git, "-C", str(repo), "commit", "-q", "-m", "drift"], check=True)
    drift_sha = subprocess.check_output(
        [git, "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()
    assert drift_sha != original_base
    subprocess.run(
        [git, "-C", str(repo), "branch", "-f", "superchat/drift-m8-10", drift_sha],
        check=True,
    )

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
    assert executed.json()["status"] == "failed"
    assert executed.json()["result"]["status"] == "drift_detected"
    assert not any(staging_root.iterdir())
