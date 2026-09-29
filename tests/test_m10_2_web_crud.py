from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app


@pytest.fixture()
def crud_client() -> Generator[TestClient, None, None]:
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


def test_decision_and_context_item_can_be_updated(crud_client: TestClient) -> None:
    project = crud_client.post(
        "/projects",
        json={"slug": "daily-ops", "name": "Daily Ops", "next_action": "Cadastrar memória"},
    )
    assert project.status_code == 201
    project_id = project.json()["id"]

    decision = crud_client.post(
        f"/projects/{project_id}/decisions",
        json={
            "title": "Proxy compartilhado",
            "body": "Usar Caddy compartilhado.",
            "rationale": "Evita segunda porta 443.",
        },
    )
    assert decision.status_code == 201
    decision_id = decision.json()["id"]

    updated_decision = crud_client.patch(
        f"/decisions/{decision_id}",
        json={"body": "Usar Caddy compartilhado com hostname dedicado.", "status": "active"},
    )
    assert updated_decision.status_code == 200
    assert updated_decision.json()["body"] == "Usar Caddy compartilhado com hostname dedicado."

    memory = crud_client.post(
        f"/projects/{project_id}/context-items",
        json={
            "kind": "deployment",
            "title": "Deploy NAS",
            "content": "API local e HTTPS via proxy.",
            "importance": 0.8,
            "source_type": "manual",
        },
    )
    assert memory.status_code == 201
    memory_id = memory.json()["id"]

    updated_memory = crud_client.patch(
        f"/context-items/{memory_id}",
        json={"importance": 1.0, "content": "API local e HTTPS via Caddy compartilhado."},
    )
    assert updated_memory.status_code == 200
    assert updated_memory.json()["importance"] == 1.0
    assert "Caddy compartilhado" in updated_memory.json()["content"]

    decisions = crud_client.get(f"/projects/{project_id}/decisions")
    memories = crud_client.get(f"/projects/{project_id}/context-items")
    assert decisions.status_code == 200
    assert memories.status_code == 200
    assert decisions.json()[0]["id"] == decision_id
    assert memories.json()[0]["id"] == memory_id


def test_web_ui_exposes_daily_operation_controls(crud_client: TestClient) -> None:
    html = crud_client.get("/app/")
    assert html.status_code == 200
    for marker in [
        "Novo projeto",
        "Editar projeto",
        "+ Tarefa",
        "+ Decisão",
        "+ Memória",
        "+ GitHub",
        "editor-dialog",
        "/app/operations.css",
    ]:
        assert marker in html.text

    javascript = crud_client.get("/app/app.js")
    assert javascript.status_code == 200
    for marker in [
        "openProjectEditor",
        "openTaskEditor",
        "openDecisionEditor",
        "openMemoryEditor",
        "openSourceEditor",
        "/decisions/",
        "/context-items/",
        "X-CSRF-Token" if False else "method: \"PATCH\"",
    ]:
        assert marker in javascript.text

    operations_css = crud_client.get("/app/operations.css")
    assert operations_css.status_code == 200
    assert ".form-grid" in operations_css.text
    assert ".mini-button" in operations_css.text
