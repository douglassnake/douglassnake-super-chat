from __future__ import annotations

from collections.abc import Generator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.executor_routes as executor_routes_module
from app.database import Base, get_db
from app.isolated_executor import IsolatedLocalExecutorAdapter
from app.main import app
from app.worker_client import ProcessWorkerClient
from app.worker_runtime import WorkerJob, WorkerLimits


@pytest.fixture()
def modify_client() -> Generator[TestClient, None, None]:
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


def setup_modify_execution(client: TestClient) -> dict:
    project = client.post(
        "/projects",
        json={
            "slug": "m8-8-project",
            "name": "M8.8 Project",
            "status": "implementation",
            "next_action": "Gerar diff efêmero",
        },
    )
    assert project.status_code == 201
    project_id = project.json()["id"]
    context = client.post(
        f"/projects/{project_id}/context-items",
        json={
            "kind": "decision",
            "title": "M8.8 policy",
            "content": "Alterações devem existir somente no workspace temporário.",
            "importance": 1.0,
            "source_type": "manual",
            "source_ref": "manual:m8-8",
        },
    )
    assert context.status_code == 201
    pack = client.post(
        "/agent-task-packs",
        json={
            "project_id": project_id,
            "objective": "Propor alteração revisável",
            "acceptance_criteria": ["O original não pode ser alterado"],
            "constraints": ["Não criar commit, PR, merge ou deploy"],
            "profile": "minimal",
            "query": "diff efêmero",
        },
    )
    assert pack.status_code == 201
    approved = client.post(f"/agent-task-packs/{pack.json()['id']}/approve")
    assert approved.status_code == 200
    handoff = client.post(
        f"/agent-task-packs/{approved.json()['id']}/handoffs",
        json={
            "executor_type": "controlled",
            "executor_target": "isolated-local",
            "allowed_actions": ["modify_worktree"],
        },
    )
    assert handoff.status_code == 201
    released = client.post(f"/agent-handoffs/{handoff.json()['id']}/release")
    assert released.status_code == 200
    execution = client.post(f"/agent-handoffs/{released.json()['id']}/execution")
    assert execution.status_code == 201
    return execution.json()


def make_adapter(root) -> IsolatedLocalExecutorAdapter:
    return IsolatedLocalExecutorAdapter(
        enabled=True,
        worktree_root=str(root),
        timeout_seconds=5,
        max_timeout_seconds=10,
        output_max_bytes=4096,
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
    )


def test_modify_worktree_returns_reviewable_patch_without_mutating_source(
    modify_client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    repo = root / "repo"
    repo.mkdir(parents=True)
    (repo / "config.txt").write_text("mode=old\n", encoding="utf-8")
    (repo / "obsolete.txt").write_text("remove me\n", encoding="utf-8")

    client = modify_client
    execution = setup_modify_execution(client)
    adapter = make_adapter(root)
    monkeypatch.setattr(
        executor_routes_module,
        "resolve_executor_adapter",
        lambda _: adapter,
    )

    created = client.post(
        f"/agent-executions/{execution['id']}/executor-requests",
        json={
            "action": "modify_worktree",
            "adapter_type": "isolated-local",
            "payload": {
                "worktree": "repo",
                "operations": [
                    {"op": "write_text", "path": "config.txt", "content": "mode=new\n"},
                    {"op": "write_text", "path": "added.txt", "content": "new file\n"},
                    {"op": "delete_file", "path": "obsolete.txt"},
                ],
            },
        },
    )
    assert created.status_code == 201
    request_id = created.json()["id"]
    assert client.post(f"/executor-requests/{request_id}/release").status_code == 200
    executed = client.post(f"/executor-requests/{request_id}/execute")
    assert executed.status_code == 200
    body = executed.json()
    assert body["status"] == "completed"
    result = body["result"]
    assert result["status"] == "proposed"
    assert result["external_effects"] is False
    assert result["workspace_persistence"] == "ephemeral_only"
    assert len(result["patch_digest"]) == 64
    assert result["patch_bytes"] > 0
    assert {item["status"] for item in result["changed_files"]} == {
        "added",
        "modified",
        "deleted",
    }
    assert "a/config.txt" in result["patch"]
    assert "b/added.txt" in result["patch"]
    assert "a/obsolete.txt" in result["patch"]

    assert (repo / "config.txt").read_text(encoding="utf-8") == "mode=old\n"
    assert (repo / "obsolete.txt").read_text(encoding="utf-8") == "remove me\n"
    assert not (repo / "added.txt").exists()

    attempts = client.get(f"/executor-requests/{request_id}/worker-attempts").json()
    assert len(attempts) == 1
    assert attempts[0]["status"] == "completed"
    assert len(attempts[0]["job_digest"]) == 64
    assert len(attempts[0]["result_digest"]) == 64


def _job(root, operations, *, policy=None) -> WorkerJob:
    return WorkerJob(
        request_id=str(uuid4()),
        action="modify_worktree",
        worktree_root=str(root),
        worktree="repo",
        payload={
            "operations": operations,
            "policy": policy
            or {
                "max_files": 10,
                "max_operations": 20,
                "max_total_write_bytes": 8192,
                "max_patch_bytes": 8192,
            },
        },
        limits=WorkerLimits(timeout_seconds=5, output_max_bytes=4096),
        backend="subprocess-sandbox",
    )


def test_modify_worker_rejects_traversal_and_detectable_secret(tmp_path) -> None:
    root = tmp_path / "root"
    repo = root / "repo"
    repo.mkdir(parents=True)
    (repo / "safe.txt").write_text("safe\n", encoding="utf-8")

    traversal = ProcessWorkerClient().execute(
        _job(root, [{"op": "write_text", "path": "../escape.txt", "content": "x\n"}])
    )
    assert traversal.ok is False
    assert "unsafe modification path" in (traversal.error or "").lower()
    assert not (root / "escape.txt").exists()

    secret = ProcessWorkerClient().execute(
        _job(
            root,
            [
                {
                    "op": "write_text",
                    "path": "safe.txt",
                    "content": "api_key=super-secret-value\n",
                }
            ],
        )
    )
    assert secret.ok is False
    assert "secret-like" in (secret.error or "").lower()
    assert (repo / "safe.txt").read_text(encoding="utf-8") == "safe\n"


def test_deleted_secret_is_redacted_from_review_patch(tmp_path) -> None:
    root = tmp_path / "root"
    repo = root / "repo"
    repo.mkdir(parents=True)
    (repo / "legacy.env").write_text(
        "api_key=do-not-persist-this-value\nregular=value\n",
        encoding="utf-8",
    )

    outcome = ProcessWorkerClient().execute(
        _job(root, [{"op": "delete_file", "path": "legacy.env"}])
    )
    assert outcome.ok is True
    patch = outcome.result["patch"]
    assert "do-not-persist-this-value" not in patch
    assert "[REDACTED]" in patch
    assert outcome.result["patch_redacted"] is True
    assert (repo / "legacy.env").exists()


def test_modify_worker_enforces_server_policy_limits(tmp_path) -> None:
    root = tmp_path / "root"
    repo = root / "repo"
    repo.mkdir(parents=True)

    outcome = ProcessWorkerClient().execute(
        _job(
            root,
            [
                {"op": "write_text", "path": "one.txt", "content": "1\n"},
                {"op": "write_text", "path": "two.txt", "content": "2\n"},
            ],
            policy={
                "max_files": 1,
                "max_operations": 20,
                "max_total_write_bytes": 8192,
                "max_patch_bytes": 8192,
            },
        )
    )
    assert outcome.ok is False
    assert "changed-file count" in (outcome.error or "").lower()
    assert list(repo.iterdir()) == []
