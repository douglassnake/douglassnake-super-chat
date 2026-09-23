from collections.abc import Generator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.agent_models import AgentHandoff
from app.database import Base, get_db
from app.main import app


@pytest.fixture()
def handoff_client() -> Generator[tuple[TestClient, sessionmaker], None, None]:
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
        yield client, TestingSessionLocal
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def _create_pack(client: TestClient, *, approve: bool) -> dict:
    project = client.post(
        "/projects",
        json={
            "slug": "handoff-project",
            "name": "Handoff Project",
            "status": "implementation",
            "next_action": "Preparar handoff auditável",
        },
    )
    assert project.status_code == 201
    project_id = project.json()["id"]

    context = client.post(
        f"/projects/{project_id}/context-items",
        json={
            "kind": "decision",
            "title": "Handoff explícito",
            "content": "O executor deve respeitar o escopo aprovado. token=context-secret",
            "importance": 1.0,
            "source_type": "manual",
            "source_ref": "manual:handoff",
        },
    )
    assert context.status_code == 201

    created = client.post(
        "/agent-task-packs",
        json={
            "project_id": project_id,
            "objective": "Executar alteração técnica sem merge nem deploy",
            "acceptance_criteria": [
                "Testes devem passar",
                "Resultado deve preservar rastreabilidade",
            ],
            "constraints": ["Não fazer merge ou deploy"],
            "suggested_areas": ["app/handoff_routes.py"],
            "profile": "minimal",
            "query": "handoff executor escopo testes",
        },
    )
    assert created.status_code == 201
    pack = created.json()
    if approve:
        approved = client.post(f"/agent-task-packs/{pack['id']}/approve")
        assert approved.status_code == 200
        pack = approved.json()
    return pack


def test_handoff_requires_approved_pack_and_defaults_to_no_actions(
    handoff_client: tuple[TestClient, sessionmaker],
) -> None:
    client, SessionFactory = handoff_client
    pack = _create_pack(client, approve=False)

    blocked = client.post(
        f"/agent-task-packs/{pack['id']}/handoffs",
        json={"executor_type": "codex"},
    )
    assert blocked.status_code == 409

    approved = client.post(f"/agent-task-packs/{pack['id']}/approve")
    assert approved.status_code == 200
    assert approved.json()["ready_for_handoff"] is True
    assert approved.json()["authorized_for_execution"] is False

    created = client.post(
        f"/agent-task-packs/{pack['id']}/handoffs",
        json={
            "executor_type": "codex",
            "executor_target": "workspace token=target-secret",
            "notes": "Preparar execução. api_key=notes-secret",
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "prepared"
    assert body["execution_released"] is False
    assert body["allowed_actions"] == []
    assert body["pack_fingerprint"] == approved.json()["fingerprint"]
    assert body["pack_snapshot"]["fingerprint"] == approved.json()["fingerprint"]
    assert body["pack_snapshot"]["objective"] == "Executar alteração técnica sem merge nem deploy"
    serialized = str(body).lower()
    assert "target-secret" not in serialized
    assert "notes-secret" not in serialized
    assert "context-secret" not in serialized
    assert "[redacted]" in serialized

    with SessionFactory() as db:
        stored = db.get(AgentHandoff, UUID(body["id"]))
        assert stored is not None
        assert stored.status == "prepared"
        assert stored.allowed_actions_json == []
        assert stored.pack_fingerprint == approved.json()["fingerprint"]


def test_release_complete_and_markdown_are_controlled(
    handoff_client: tuple[TestClient, sessionmaker],
) -> None:
    client, _ = handoff_client
    pack = _create_pack(client, approve=True)

    created = client.post(
        f"/agent-task-packs/{pack['id']}/handoffs",
        json={
            "executor_type": "codex",
            "executor_target": "local-worktree",
            "allowed_actions": [
                "read_repository",
                "modify_worktree",
                "run_tests",
                "create_commit",
            ],
            "notes": "Não criar PR nesta execução.",
        },
    )
    assert created.status_code == 201
    handoff_id = created.json()["id"]

    before_release = client.post(
        f"/agent-handoffs/{handoff_id}/complete",
        json={"result": {"summary": "prematuro"}},
    )
    assert before_release.status_code == 409

    first_markdown = client.get(f"/agent-handoffs/{handoff_id}/markdown")
    second_markdown = client.get(f"/agent-handoffs/{handoff_id}/markdown")
    assert first_markdown.status_code == 200
    assert first_markdown.text == second_markdown.text
    assert "# Agent Handoff" in first_markdown.text
    assert "## Contexto selecionado" in first_markdown.text
    assert "Handoff explícito" in first_markdown.text
    assert "context-secret" not in first_markdown.text
    assert "[REDACTED]" in first_markdown.text
    assert "`run_tests`" in first_markdown.text
    assert "`merge`" in first_markdown.text
    assert "não executa ferramentas externas" in first_markdown.text.lower()

    released = client.post(f"/agent-handoffs/{handoff_id}/release")
    assert released.status_code == 200
    released_body = released.json()
    assert released_body["status"] == "released"
    assert released_body["execution_released"] is True
    assert released_body["released_at"] is not None

    second_release = client.post(f"/agent-handoffs/{handoff_id}/release")
    assert second_release.status_code == 200
    assert second_release.json()["released_at"] == released_body["released_at"]

    completed = client.post(
        f"/agent-handoffs/{handoff_id}/complete",
        json={
            "result": {
                "summary": "Testes concluídos. token=result-secret",
                "commit": "abc123",
                "tests": {"passed": 27},
            }
        },
    )
    assert completed.status_code == 200
    completed_body = completed.json()
    assert completed_body["status"] == "completed"
    assert completed_body["execution_released"] is False
    assert completed_body["completed_at"] is not None
    assert completed_body["result"]["commit"] == "abc123"
    assert "result-secret" not in str(completed_body).lower()
    assert "[redacted]" in str(completed_body).lower()

    repeated = client.post(
        f"/agent-handoffs/{handoff_id}/complete",
        json={"result": {"summary": "não deve sobrescrever"}},
    )
    assert repeated.status_code == 200
    assert repeated.json()["completed_at"] == completed_body["completed_at"]
    assert repeated.json()["result"] == completed_body["result"]

    cancel_completed = client.post(f"/agent-handoffs/{handoff_id}/cancel")
    assert cancel_completed.status_code == 409


def test_invalid_action_fail_and_cancel_transitions(
    handoff_client: tuple[TestClient, sessionmaker],
) -> None:
    client, _ = handoff_client
    pack = _create_pack(client, approve=True)

    invalid = client.post(
        f"/agent-task-packs/{pack['id']}/handoffs",
        json={
            "executor_type": "codex",
            "allowed_actions": ["merge"],
        },
    )
    assert invalid.status_code == 422
    assert "unsupported handoff actions" in str(invalid.json()).lower()

    failing = client.post(
        f"/agent-task-packs/{pack['id']}/handoffs",
        json={
            "executor_type": "codex",
            "allowed_actions": ["read_repository", "run_tests"],
        },
    )
    assert failing.status_code == 201
    failing_id = failing.json()["id"]
    assert client.post(f"/agent-handoffs/{failing_id}/release").status_code == 200

    failed = client.post(
        f"/agent-handoffs/{failing_id}/fail",
        json={
            "error": "Falha de teste. password=failure-secret",
            "result": {"stage": "pytest"},
        },
    )
    assert failed.status_code == 200
    failed_body = failed.json()
    assert failed_body["status"] == "failed"
    assert failed_body["failed_at"] is not None
    assert "failure-secret" not in str(failed_body).lower()
    failed_at = failed_body["failed_at"]

    repeated_fail = client.post(
        f"/agent-handoffs/{failing_id}/fail",
        json={"error": "não sobrescrever", "result": {}},
    )
    assert repeated_fail.status_code == 200
    assert repeated_fail.json()["failed_at"] == failed_at
    assert repeated_fail.json()["error"] == failed_body["error"]

    cancellable = client.post(
        f"/agent-task-packs/{pack['id']}/handoffs",
        json={"executor_type": "manual"},
    )
    assert cancellable.status_code == 201
    cancellable_id = cancellable.json()["id"]

    cancelled = client.post(f"/agent-handoffs/{cancellable_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    cancelled_at = cancelled.json()["cancelled_at"]

    second_cancel = client.post(f"/agent-handoffs/{cancellable_id}/cancel")
    assert second_cancel.status_code == 200
    assert second_cancel.json()["cancelled_at"] == cancelled_at

    release_cancelled = client.post(f"/agent-handoffs/{cancellable_id}/release")
    assert release_cancelled.status_code == 409
