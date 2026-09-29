from collections.abc import Generator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import ContextRun, Event


@pytest.fixture()
def context_client() -> Generator[tuple[TestClient, sessionmaker], None, None]:
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


def seed_project(client: TestClient) -> str:
    project = client.post(
        "/projects",
        json={
            "slug": "context-test",
            "name": "Context Test",
            "description": "Projeto fictício para validar recuperação de contexto.",
            "status": "implementation",
            "priority": 10,
            "next_action": "Implementar Context Engine",
        },
    ).json()
    project_id = project["id"]

    client.post(
        f"/projects/{project_id}/summaries",
        json={
            "summary": "O M1 foi concluído e a próxima fase é reduzir contexto e consumo de tokens.",
            "next_action": "Implementar Context Engine",
            "source_ref": "session:test",
        },
    )
    client.post(
        f"/projects/{project_id}/decisions",
        json={
            "title": "Usar ranking determinístico antes de embeddings",
            "body": "A primeira versão do Context Engine deve usar ranking determinístico e orçamento de tokens.",
            "source_ref": "decision:test",
        },
    )
    client.post(
        f"/projects/{project_id}/tasks",
        json={
            "title": "Adicionar endpoint continuar projeto",
            "description": "Gerar contexto operacional sem carregar histórico bruto.",
            "priority": 100,
            "source_ref": "task:test",
        },
    )

    duplicate_content = "Contexto importante sobre economia de tokens e recuperação seletiva."
    for source_ref, importance in [("manual:a", 0.90), ("manual:b", 0.80)]:
        client.post(
            f"/projects/{project_id}/context-items",
            json={
                "kind": "fact",
                "title": "Economia de tokens",
                "content": duplicate_content,
                "importance": importance,
                "source_type": "manual",
                "source_ref": source_ref,
            },
        )

    client.post(
        f"/projects/{project_id}/context-items",
        json={
            "kind": "document_excerpt",
            "title": "Documento extenso sobre contexto",
            "content": ("tokens contexto recuperação seletiva arquitetura " * 1000).strip(),
            "importance": 1.0,
            "source_type": "drive",
            "source_ref": "drive:long-document",
        },
    )
    return project_id


def test_context_profiles_budget_dedup_and_audit(context_client: tuple[TestClient, sessionmaker]) -> None:
    client, SessionFactory = context_client
    project_id = seed_project(client)

    minimal_response = client.post(
        "/context/build",
        json={
            "project_id": project_id,
            "query": "economia tokens contexto recuperação seletiva",
            "profile": "minimal",
        },
    )
    assert minimal_response.status_code == 200
    minimal = minimal_response.json()
    assert minimal["profile"] == "minimal"
    assert minimal["budget"]["max_tokens"] == 1800
    assert minimal["budget"]["estimated_tokens"] <= minimal["budget"]["max_tokens"]
    assert minimal["budget"]["selected_count"] == len(minimal["items"])

    normalized_contents = [" ".join(item["content"].lower().split()) for item in minimal["items"]]
    assert len(normalized_contents) == len(set(normalized_contents))

    deep_response = client.post(
        "/context/build",
        json={
            "project_id": project_id,
            "query": "economia tokens contexto recuperação seletiva",
            "profile": "deep",
        },
    )
    assert deep_response.status_code == 200
    deep = deep_response.json()
    assert deep["budget"]["max_tokens"] == 15000
    assert deep["budget"]["estimated_tokens"] <= deep["budget"]["max_tokens"]
    assert deep["budget"]["selected_count"] >= minimal["budget"]["selected_count"]

    with SessionFactory() as db:
        audit_count = db.scalar(select(func.count(ContextRun.id)))
        assert audit_count == 2


def test_continue_project_builds_operational_context(context_client: tuple[TestClient, sessionmaker]) -> None:
    client, SessionFactory = context_client
    project_id = seed_project(client)

    response = client.get(f"/projects/{project_id}/continue?profile=standard")
    assert response.status_code == 200
    package = response.json()
    assert package["project"]["next_action"] == "Implementar Context Engine"
    assert package["profile"] == "standard"
    assert package["budget"]["estimated_tokens"] <= 5000
    assert package["items"]
    assert any(item["kind"] in {"summary", "decision", "task"} for item in package["items"])

    with SessionFactory() as db:
        audit_count = db.scalar(select(func.count(ContextRun.id)))
        assert audit_count == 1


def test_operational_context_reserves_signal_and_caps_successful_workflows(
    context_client: tuple[TestClient, sessionmaker],
) -> None:
    client, SessionFactory = context_client
    project = client.post(
        "/projects",
        json={
            "slug": "operational-quality",
            "name": "Operational Quality",
            "description": "Projeto para validar sinal operacional contra ruído de CI.",
            "status": "active",
            "priority": 100,
            "next_action": "Validar recuperação operacional",
        },
    ).json()
    project_id = project["id"]

    assert client.post(
        f"/projects/{project_id}/decisions",
        json={
            "title": "Publicação HTTPS pelo Caddy compartilhado",
            "body": "Usar hostname dedicado no Caddy existente e acessar api:8000 pela rede Docker.",
            "rationale": "Evita concorrência na porta 443 e mantém isolamento.",
            "source_ref": "decision:caddy",
        },
    ).status_code == 201

    assert client.post(
        f"/projects/{project_id}/tasks",
        json={
            "title": "Automatizar backup e restore",
            "description": "Automatizar backup lógico do PostgreSQL e teste periódico de restore.",
            "priority": 90,
            "source_ref": "task:backup",
        },
    ).status_code == 201

    assert client.post(
        f"/projects/{project_id}/context-items",
        json={
            "kind": "deployment",
            "title": "Implantação ZimaOS/NAS",
            "content": (
                "PostgreSQL persistente no NAS, Super Chat atrás do Caddy e "
                "volume antigo preservado para rollback."
            ),
            "importance": 1.0,
            "source_type": "manual",
            "source_ref": "manual:deployment",
        },
    ).status_code == 201

    now = datetime.now(timezone.utc)
    with SessionFactory() as db:
        for index in range(10):
            db.add(
                Event(
                    project_id=project_id,
                    source_type="github",
                    event_type="github.workflow_run",
                    external_id=f"run:{index}",
                    title=f"Action deployment Caddy backup success {index}",
                    body="implantação Caddy PostgreSQL backup restore arquitetura",
                    occurred_at=now,
                    url=f"https://github.example/actions/runs/{index}",
                    metadata_json={
                        "repository": "owner/repo",
                        "status": "completed",
                        "conclusion": "success",
                    },
                )
            )
        db.commit()

    response = client.post(
        "/context/build",
        json={
            "project_id": project_id,
            "query": "implantação ZimaOS Caddy PostgreSQL persistência backup restore decisão arquitetural",
            "profile": "standard",
        },
    )
    assert response.status_code == 200
    package = response.json()
    refs = [item["source_ref"] for item in package["items"]]
    assert refs[:3] == ["decision:caddy", "task:backup", "manual:deployment"]

    successful_workflows = [
        item
        for item in package["items"]
        if item["source_type"] == "github"
        and item["source_ref"]
        and "/actions/runs/" in item["source_ref"]
    ]
    assert len(successful_workflows) <= 3
    assert package["budget"]["estimated_tokens"] <= package["budget"]["max_tokens"]


def test_invalid_context_profile_is_rejected(context_client: tuple[TestClient, sessionmaker]) -> None:
    client, _ = context_client
    project_id = seed_project(client)
    response = client.post(
        "/context/build",
        json={"project_id": project_id, "query": "status", "profile": "everything"},
    )
    assert response.status_code == 422
