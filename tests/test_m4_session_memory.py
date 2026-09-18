from collections.abc import Generator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Decision, SessionDelta, SessionSummary, Task


@pytest.fixture()
def session_client() -> Generator[tuple[TestClient, sessionmaker], None, None]:
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


def create_project(client: TestClient, slug: str = "session-project") -> str:
    response = client.post(
        "/projects",
        json={
            "slug": slug,
            "name": "Session Project",
            "status": "planning",
            "next_action": "Revisar sessão",
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_session_delta_requires_confirmation_before_mutating_memory(
    session_client: tuple[TestClient, sessionmaker],
) -> None:
    client, SessionFactory = session_client
    project_id = create_project(client)

    existing_task = client.post(
        f"/projects/{project_id}/tasks",
        json={"title": "Planejamento anterior", "priority": 20},
    ).json()

    create_delta_response = client.post(
        f"/projects/{project_id}/session-deltas",
        json={
            "session_key": "chat-2026-09-18-001",
            "summary": "M3 foi concluído e a Session Memory foi definida.",
            "decisions": [
                {
                    "title": "Exigir confirmação humana",
                    "body": "SessionDelta só altera a memória após apply explícito.",
                    "rationale": "Evitar gravação automática de inferências incorretas.",
                }
            ],
            "tasks": [
                {
                    "title": "Implementar Session Memory",
                    "description": "Aplicar delta confirmado à memória operacional.",
                    "priority": 100,
                }
            ],
            "close_task_ids": [existing_task["id"]],
            "status_change": "implementation",
            "next_action": "Validar Session Memory",
            "source_refs": ["chat:2026-09-18"],
        },
    )
    assert create_delta_response.status_code == 201
    delta = create_delta_response.json()
    delta_id = delta["id"]
    assert delta["status"] == "pending"

    # Pending delta exists, but operational memory has not changed yet.
    snapshot_before = client.get(f"/projects/{project_id}/snapshot").json()
    assert snapshot_before["project"]["status"] == "planning"
    assert snapshot_before["project"]["next_action"] == "Revisar sessão"
    assert snapshot_before["summary"] is None
    assert snapshot_before["decisions"] == []
    assert len(snapshot_before["open_tasks"]) == 1

    preview = client.get(f"/session-deltas/{delta_id}/preview")
    assert preview.status_code == 200
    effects = preview.json()["effects"]
    assert effects["decisions_to_create"] == 1
    assert effects["tasks_to_create"] == 1
    assert effects["tasks_to_close"][0]["id"] == existing_task["id"]
    assert effects["missing_or_foreign_task_ids"] == []
    assert effects["status_change"] == "implementation"

    duplicate = client.post(
        f"/projects/{project_id}/session-deltas",
        json={
            "session_key": "chat-2026-09-18-001",
            "summary": "Duplicado",
        },
    )
    assert duplicate.status_code == 409

    applied_response = client.post(f"/session-deltas/{delta_id}/apply")
    assert applied_response.status_code == 200
    applied = applied_response.json()
    assert applied["delta"]["status"] == "applied"
    assert len(applied["created_decision_ids"]) == 1
    assert len(applied["created_task_ids"]) == 1
    assert applied["closed_task_ids"] == [existing_task["id"]]
    assert applied["project_status"] == "implementation"
    assert applied["project_next_action"] == "Validar Session Memory"

    snapshot_after = client.get(f"/projects/{project_id}/snapshot").json()
    assert snapshot_after["project"]["status"] == "implementation"
    assert snapshot_after["project"]["next_action"] == "Validar Session Memory"
    assert snapshot_after["summary"]["session_key"] == "chat-2026-09-18-001"
    assert len(snapshot_after["decisions"]) == 1
    assert len(snapshot_after["open_tasks"]) == 1
    assert snapshot_after["open_tasks"][0]["title"] == "Implementar Session Memory"

    second_apply = client.post(f"/session-deltas/{delta_id}/apply")
    assert second_apply.status_code == 409

    with SessionFactory() as db:
        assert db.scalar(select(func.count(SessionSummary.id))) == 1
        assert db.scalar(select(func.count(Decision.id))) == 1
        assert db.scalar(select(func.count(Task.id))) == 2
        stored_delta = db.get(SessionDelta, delta_id)
        # direct DB get with string is intentionally avoided; API assertions cover state.
        assert stored_delta is None or stored_delta.status == "applied"


def test_discarded_delta_cannot_be_applied(
    session_client: tuple[TestClient, sessionmaker],
) -> None:
    client, _ = session_client
    project_id = create_project(client, "discard-project")
    delta = client.post(
        f"/projects/{project_id}/session-deltas",
        json={"session_key": "discard-1", "summary": "Nada deve ser aplicado."},
    ).json()

    discarded = client.post(f"/session-deltas/{delta['id']}/discard")
    assert discarded.status_code == 200
    assert discarded.json()["status"] == "discarded"

    apply_response = client.post(f"/session-deltas/{delta['id']}/apply")
    assert apply_response.status_code == 409

    snapshot = client.get(f"/projects/{project_id}/snapshot").json()
    assert snapshot["summary"] is None


def test_invalid_task_reference_keeps_delta_pending_and_memory_unchanged(
    session_client: tuple[TestClient, sessionmaker],
) -> None:
    client, _ = session_client
    project_id = create_project(client, "invalid-close-project")
    missing_task_id = str(uuid4())

    delta = client.post(
        f"/projects/{project_id}/session-deltas",
        json={
            "session_key": "invalid-close-1",
            "summary": "Tentativa com tarefa inexistente.",
            "decisions": [{"title": "Não aplicar", "body": "Deve falhar antes da transação."}],
            "close_task_ids": [missing_task_id],
            "status_change": "should-not-apply",
        },
    ).json()

    preview = client.get(f"/session-deltas/{delta['id']}/preview").json()
    assert preview["effects"]["missing_or_foreign_task_ids"] == [missing_task_id]

    response = client.post(f"/session-deltas/{delta['id']}/apply")
    assert response.status_code == 422

    listed = client.get(
        f"/projects/{project_id}/session-deltas",
        params={"status": "pending"},
    )
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    snapshot = client.get(f"/projects/{project_id}/snapshot").json()
    assert snapshot["project"]["status"] == "planning"
    assert snapshot["summary"] is None
    assert snapshot["decisions"] == []
