from __future__ import annotations

from collections.abc import Generator
import os
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.executor_routes as executor_routes_module
from app.database import Base, get_db
from app.git_branch_worker import _git_env
from app.isolated_executor import IsolatedLocalExecutorAdapter
from app.main import app


@pytest.fixture()
def git_stage_client() -> Generator[TestClient, None, None]:
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


def make_adapter(root) -> IsolatedLocalExecutorAdapter:
    return IsolatedLocalExecutorAdapter(
        enabled=True,
        worktree_root=str(root),
        timeout_seconds=5,
        max_timeout_seconds=10,
        output_max_bytes=8192,
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


def setup_execution(client: TestClient, slug: str, allowed_actions: list[str]) -> dict:
    project = client.post(
        "/projects",
        json={
            "slug": slug,
            "name": f"Project {slug}",
            "status": "implementation",
            "next_action": "Validar M8.9",
        },
    )
    assert project.status_code == 201
    project_id = project.json()["id"]
    context = client.post(
        f"/projects/{project_id}/context-items",
        json={
            "kind": "decision",
            "title": "M8.9 policy",
            "content": "Git effects require independent authorization.",
            "importance": 1.0,
            "source_type": "manual",
            "source_ref": f"manual:{slug}",
        },
    )
    assert context.status_code == 201
    pack = client.post(
        "/agent-task-packs",
        json={
            "project_id": project_id,
            "objective": "Validar gate Git",
            "acceptance_criteria": ["Nenhum efeito Git implícito"],
            "constraints": ["Não fazer commit, push, PR, merge ou deploy"],
            "profile": "minimal",
            "query": "M8.9 git approval branch",
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
            "allowed_actions": allowed_actions,
        },
    )
    assert handoff.status_code == 201
    released = client.post(f"/agent-handoffs/{handoff.json()['id']}/release")
    assert released.status_code == 200
    execution = client.post(f"/agent-handoffs/{released.json()['id']}/execution")
    assert execution.status_code == 201
    return execution.json()


def _prepare_repo(root):
    git = shutil.which("git")
    if git is None:
        pytest.skip("git executable is unavailable")
    repo = root / "repo"
    repo.mkdir(parents=True)
    subprocess.run([git, "init", "-q", str(repo)], check=True)
    subprocess.run([git, "-C", str(repo), "config", "user.email", "tests@example.invalid"], check=True)
    subprocess.run([git, "-C", str(repo), "config", "user.name", "Super Chat Tests"], check=True)
    (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
    subprocess.run([git, "-C", str(repo), "add", "tracked.txt"], check=True)
    subprocess.run([git, "-C", str(repo), "commit", "-q", "-m", "initial"], check=True)
    head = subprocess.check_output([git, "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    current = subprocess.check_output(
        [git, "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"],
        text=True,
    ).strip()
    return git, repo, head, current


def test_patch_digest_approval_is_explicit_and_has_no_git_effect(
    git_stage_client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    git, repo, head, current_branch = _prepare_repo(root)
    client = git_stage_client
    execution = setup_execution(client, "approval-m8-9", ["modify_worktree"])
    monkeypatch.setattr(
        executor_routes_module,
        "resolve_executor_adapter",
        lambda _: make_adapter(root),
    )

    request = client.post(
        f"/agent-executions/{execution['id']}/executor-requests",
        json={
            "action": "modify_worktree",
            "adapter_type": "isolated-local",
            "payload": {
                "worktree": "repo",
                "operations": [
                    {"op": "write_text", "path": "tracked.txt", "content": "proposal\n"}
                ],
            },
        },
    )
    assert request.status_code == 201
    request_id = request.json()["id"]
    assert client.post(f"/executor-requests/{request_id}/release").status_code == 200
    executed = client.post(f"/executor-requests/{request_id}/execute")
    assert executed.status_code == 200
    proposal = executed.json()["result"]
    digest = proposal["patch_digest"]

    prepared = client.post(f"/executor-requests/{request_id}/git-change-approval")
    assert prepared.status_code == 201
    approval = prepared.json()
    assert approval["status"] == "pending"
    assert approval["patch_digest"] == digest

    wrong = client.post(
        f"/git-change-approvals/{approval['id']}/approve",
        json={"patch_digest": "0" * 64},
    )
    assert wrong.status_code == 409

    approved = client.post(
        f"/git-change-approvals/{approval['id']}/approve",
        json={"patch_digest": digest},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    assert (repo / "tracked.txt").read_text(encoding="utf-8") == "base\n"
    assert subprocess.check_output([git, "-C", str(repo), "rev-parse", "HEAD"], text=True).strip() == head
    assert subprocess.check_output(
        [git, "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"], text=True
    ).strip() == current_branch
    branches = subprocess.check_output([git, "-C", str(repo), "branch", "--format=%(refname:short)"], text=True)
    assert "superchat/" not in branches


def test_create_branch_requires_separate_release_and_does_not_checkout(
    git_stage_client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    git, repo, head, current_branch = _prepare_repo(root)
    original_bytes = (repo / "tracked.txt").read_bytes()
    client = git_stage_client
    execution = setup_execution(client, "branch-m8-9", ["create_branch"])
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
            "payload": {"worktree": "repo", "branch_name": "superchat/m8-9-test"},
        },
    )
    assert request.status_code == 201
    request_id = request.json()["id"]

    before_release = client.post(f"/executor-requests/{request_id}/execute")
    assert before_release.status_code == 409
    assert "superchat/m8-9-test" not in subprocess.check_output(
        [git, "-C", str(repo), "branch", "--format=%(refname:short)"], text=True
    )

    assert client.post(f"/executor-requests/{request_id}/release").status_code == 200
    executed = client.post(f"/executor-requests/{request_id}/execute")
    assert executed.status_code == 200
    body = executed.json()
    assert body["status"] == "completed"
    result = body["result"]
    assert result["status"] == "created"
    assert result["branch_name"] == "superchat/m8-9-test"
    assert result["base_sha"] == head
    assert result["checkout_performed"] is False
    assert result["push_performed"] is False
    assert result["worktree_files_changed"] is False
    assert result["external_effects"] is True

    assert (repo / "tracked.txt").read_bytes() == original_bytes
    assert subprocess.check_output(
        [git, "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"], text=True
    ).strip() == current_branch
    assert subprocess.check_output(
        [git, "-C", str(repo), "rev-parse", "superchat/m8-9-test"], text=True
    ).strip() == head


def test_create_branch_rejects_names_outside_namespace(
    git_stage_client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    git, repo, _head, current_branch = _prepare_repo(root)
    client = git_stage_client
    execution = setup_execution(client, "invalid-branch-m8-9", ["create_branch"])
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
            "payload": {"worktree": "repo", "branch_name": "feature/not-allowed"},
        },
    )
    assert request.status_code == 201
    request_id = request.json()["id"]
    assert client.post(f"/executor-requests/{request_id}/release").status_code == 200
    executed = client.post(f"/executor-requests/{request_id}/execute")
    assert executed.status_code == 200
    assert executed.json()["status"] == "failed"
    assert "restricted namespace" in (executed.json()["error"] or "").lower()
    assert subprocess.check_output(
        [git, "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"], text=True
    ).strip() == current_branch


def test_git_worker_environment_does_not_inherit_parent_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "should-not-cross-boundary")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "should-not-cross-boundary")
    env = _git_env()
    assert "GITHUB_TOKEN" not in env
    assert "AWS_SECRET_ACCESS_KEY" not in env
    assert env["GIT_TERMINAL_PROMPT"] == "0"
