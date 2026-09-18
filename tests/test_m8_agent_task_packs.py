from collections.abc import Generator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.agent_models import AgentTaskPack
from app.database import Base, get_db
from app.main import app


@pytest.fixture()
def agent_client() -> Generator[tuple[TestClient, sessionmaker], None, None]:
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


def _prepare_project(client: TestClient) -> str:
    project = client.post(
        "/projects",
        json={
            "slug": "agent-pack-project",
            "name": "Agent Pack Project",
            "status": "implementation",
            "next_action": "Implementar endpoint seguro",
        },
    )
    assert project.status_code == 201
    project_id = project.json()["id"]

    context = client.post(
        f"/projects/{project_id}/context-items",
        json={
            "kind": "decision",
            "title": "API segura",
            "content": "Implementar preview e aprovação. token=super-secret-value não pode chegar ao agente.",
            "importance": 1.0,
            "source_type": "manual",
            "source_ref": "https://example.test/spec?token=secret-query&section=agent",
        },
    )
    assert context.status_code == 201
    return project_id


def _payload(project_id: str) -> dict:
    return {
        "project_id": project_id,
        "objective": "Criar fluxo de Agent Task Pack sem executar deploy. api_key=objective-secret",
        "acceptance_criteria": [
            "Preview não persiste o pack",
            "Pack aprovado deve ficar pronto para handoff",
        ],
        "constraints": ["Não alterar banco fora da migration. password=constraint-secret"],
        "suggested_areas": ["app/agent_routes.py", "tests/test_m8_agent_task_packs.py"],
        "profile": "minimal",
        "query": "preview aprovação agent pack endpoint seguro",
    }


def test_preview_is_non_persistent_and_redacts_secrets(
    agent_client: tuple[TestClient, sessionmaker],
) -> None:
    client, SessionFactory = agent_client
    project_id = _prepare_project(client)

    preview = client.post("/agent-task-packs/preview", json=_payload(project_id))
    assert preview.status_code == 200
    body = preview.json()
    assert body["status"] == "preview"
    assert body["ready_for_handoff"] is False
    assert body["authorized_for_execution"] is False
    assert len(body["fingerprint"]) == 64
    assert body["budget"]["estimated_tokens"] <= body["budget"]["max_tokens"]
    assert body["suggested_areas"] == [
        "app/agent_routes.py",
        "tests/test_m8_agent_task_packs.py",
    ]
    assert body["acceptance_criteria"] == [
        "Preview não persiste o pack",
        "Pack aprovado deve ficar pronto para handoff",
    ]

    serialized = str(body).lower()
    assert "super-secret-value" not in serialized
    assert "objective-secret" not in serialized
    assert "constraint-secret" not in serialized
    assert "secret-query" not in serialized
    assert "[redacted]" in serialized

    with SessionFactory() as db:
        assert db.scalar(select(func.count(AgentTaskPack.id))) == 0


def test_create_approve_export_and_duplicate_protection(
    agent_client: tuple[TestClient, sessionmaker],
) -> None:
    client, SessionFactory = agent_client
    project_id = _prepare_project(client)
    payload = _payload(project_id)

    preview = client.post("/agent-task-packs/preview", json=payload).json()
    created_response = client.post("/agent-task-packs", json=payload)
    assert created_response.status_code == 201
    created = created_response.json()
    pack_id = created["id"]
    assert created["status"] == "pending"
    assert created["ready_for_handoff"] is False
    assert created["authorized_for_execution"] is False
    assert created["fingerprint"] == preview["fingerprint"]

    duplicate = client.post("/agent-task-packs", json=payload)
    assert duplicate.status_code == 409

    first_markdown = client.get(f"/agent-task-packs/{pack_id}/markdown")
    second_markdown = client.get(f"/agent-task-packs/{pack_id}/markdown")
    assert first_markdown.status_code == 200
    assert first_markdown.text == second_markdown.text
    assert "# Agent Task Pack" in first_markdown.text
    assert "Preview não persiste o pack" in first_markdown.text
    assert "super-secret-value" not in first_markdown.text
    assert "objective-secret" not in first_markdown.text
    assert "secret-query" not in first_markdown.text
    assert "Não autoriza merge, deploy" not in first_markdown.text  # wording is explicit below, not duplicated
    assert "não autoriza merge, deploy" in first_markdown.text.lower()

    approved = client.post(f"/agent-task-packs/{pack_id}/approve")
    assert approved.status_code == 200
    approved_body = approved.json()
    assert approved_body["status"] == "approved"
    assert approved_body["ready_for_handoff"] is True
    assert approved_body["authorized_for_execution"] is False
    assert approved_body["approved_at"] is not None

    second_approve = client.post(f"/agent-task-packs/{pack_id}/approve")
    assert second_approve.status_code == 200
    assert second_approve.json()["approved_at"] == approved_body["approved_at"]

    cancel_approved = client.post(f"/agent-task-packs/{pack_id}/cancel")
    assert cancel_approved.status_code == 409

    listed = client.get(f"/projects/{project_id}/agent-task-packs", params={"status": "approved"})
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["fingerprint"] == created["fingerprint"]

    with SessionFactory() as db:
        stored = db.get(AgentTaskPack, UUID(pack_id))
        assert stored is not None
        assert stored.project_snapshot_json["status"] == "implementation"
        assert stored.status == "approved"
        assert "secret" not in str(stored.context_json).lower() or "[redacted]" in str(stored.context_json).lower()


def test_cancel_is_idempotent_and_blocks_approval(
    agent_client: tuple[TestClient, sessionmaker],
) -> None:
    client, _ = agent_client
    project_id = _prepare_project(client)
    created = client.post("/agent-task-packs", json=_payload(project_id)).json()
    pack_id = created["id"]

    cancelled = client.post(f"/agent-task-packs/{pack_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["ready_for_handoff"] is False
    assert cancelled.json()["authorized_for_execution"] is False
    cancelled_at = cancelled.json()["cancelled_at"]

    second_cancel = client.post(f"/agent-task-packs/{pack_id}/cancel")
    assert second_cancel.status_code == 200
    assert second_cancel.json()["cancelled_at"] == cancelled_at

    approve = client.post(f"/agent-task-packs/{pack_id}/approve")
    assert approve.status_code == 409
