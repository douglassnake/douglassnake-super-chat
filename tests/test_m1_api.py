from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
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
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_project_lifecycle_and_snapshot(client: TestClient) -> None:
    project_response = client.post(
        "/projects",
        json={
            "slug": "meunegocioia",
            "name": "MeuNegocioIA",
            "status": "active",
            "priority": 10,
            "next_action": "Implementar M2.6",
        },
    )
    assert project_response.status_code == 201
    project = project_response.json()
    project_id = project["id"]

    duplicate = client.post(
        "/projects",
        json={"slug": "meunegocioia", "name": "Duplicado"},
    )
    assert duplicate.status_code == 409

    decision_response = client.post(
        f"/projects/{project_id}/decisions",
        json={
            "title": "Implementação em PR separado",
            "body": "M2.6 deve ser implementado em PR próprio.",
            "rationale": "Separar planejamento de implementação.",
            "source_ref": "github:pr/24",
        },
    )
    assert decision_response.status_code == 201

    task_response = client.post(
        f"/projects/{project_id}/tasks",
        json={
            "title": "Implementar confirmação financeira",
            "priority": 100,
        },
    )
    assert task_response.status_code == 201
    task = task_response.json()

    summary_response = client.post(
        f"/projects/{project_id}/summaries",
        json={
            "session_key": "test-session",
            "summary": "Planejamento concluído e implementação pendente.",
            "next_action": "Implementar confirmação financeira",
        },
    )
    assert summary_response.status_code == 201

    patch_response = client.patch(
        f"/projects/{project_id}",
        json={"status": "m2.6", "next_action": "Implementar confirmação financeira"},
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["status"] == "m2.6"

    snapshot_response = client.get(f"/projects/{project_id}/snapshot")
    assert snapshot_response.status_code == 200
    snapshot = snapshot_response.json()
    assert snapshot["project"]["name"] == "MeuNegocioIA"
    assert snapshot["summary"]["session_key"] == "test-session"
    assert len(snapshot["decisions"]) == 1
    assert len(snapshot["open_tasks"]) == 1
    assert snapshot["open_tasks"][0]["id"] == task["id"]

    close_task_response = client.patch(
        f"/tasks/{task['id']}",
        json={"status": "done"},
    )
    assert close_task_response.status_code == 200

    final_snapshot = client.get(f"/projects/{project_id}/snapshot").json()
    assert final_snapshot["open_tasks"] == []


def test_missing_project_returns_404(client: TestClient) -> None:
    response = client.get("/projects/00000000-0000-0000-0000-000000000001/snapshot")
    assert response.status_code == 404
