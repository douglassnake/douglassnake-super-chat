from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app


@pytest.fixture()
def cross_graph_client() -> Generator[TestClient, None, None]:
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


def _project(client: TestClient) -> str:
    response = client.post(
        "/projects",
        json={
            "slug": "cross-knowledge",
            "name": "Cross Knowledge",
            "description": "Projeto para validar conexões entre documentos e entidades.",
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def _seed_github_and_readme(client: TestClient, project_id: str) -> None:
    github = client.post(
        f"/projects/{project_id}/relations",
        json={
            "entity_name": "GitHub",
            "entity_kind": "platform",
            "entity_key": "github",
            "relation_type": "uses",
            "rationale": "Repositório do projeto.",
        },
    )
    assert github.status_code == 201

    document = client.post(
        f"/projects/{project_id}/relations",
        json={
            "entity_name": "README — Cross Knowledge",
            "entity_kind": "document",
            "entity_key": "https-github-com-example-cross-knowledge-readme",
            "entity_description": "Documentação principal do projeto.",
            "entity_metadata_json": {
                "document_type": "markdown",
                "source_type": "GitHub",
                "url": "https://github.com/example/cross-knowledge/blob/main/README.md",
            },
            "relation_type": "has_document",
            "rationale": "Documenta a arquitetura do projeto.",
        },
    )
    assert document.status_code == 201


def test_document_source_is_suggested_only_after_human_review(cross_graph_client: TestClient) -> None:
    project_id = _project(cross_graph_client)
    _seed_github_and_readme(cross_graph_client, project_id)

    prepared = cross_graph_client.post(f"/projects/{project_id}/graph/suggestions")
    assert prepared.status_code == 201
    batch = prepared.json()
    suggestion = next(
        item
        for item in batch["suggestions"]
        if item["subject_type"] == "entity"
        and item["subject_label"] == "README — Cross Knowledge"
        and item["entity_name"] == "GitHub"
    )
    assert suggestion["relation_type"] == "created_from"
    assert suggestion["confidence"] >= 0.95
    suggestion_index = batch["suggestions"].index(suggestion)

    before = cross_graph_client.get("/graph").json()
    assert not [edge for edge in before["edges"] if edge["type"] == "created_from"]

    applied = cross_graph_client.post(
        f"/graph-suggestions/{batch['id']}/apply",
        json={"selected_indexes": [suggestion_index]},
    )
    assert applied.status_code == 200
    assert applied.json()["applied_count"] == 1

    after = cross_graph_client.get("/graph").json()
    readme = next(node for node in after["nodes"] if node["label"] == "README — Cross Knowledge")
    github = next(node for node in after["nodes"] if node["label"] == "GitHub")
    edge = next(
        edge
        for edge in after["edges"]
        if edge["source"] == readme["id"]
        and edge["target"] == github["id"]
        and edge["type"] == "created_from"
    )
    assert edge["semantic"] is True
    assert edge["metadata"]["relation_scope"] == "knowledge"
    assert edge["metadata"]["relation_id"]


def test_existing_document_relation_is_not_suggested_twice(cross_graph_client: TestClient) -> None:
    project_id = _project(cross_graph_client)
    _seed_github_and_readme(cross_graph_client, project_id)

    first = cross_graph_client.post(f"/projects/{project_id}/graph/suggestions").json()
    index = next(
        index
        for index, item in enumerate(first["suggestions"])
        if item["subject_type"] == "entity"
        and item["entity_name"] == "GitHub"
        and item["relation_type"] == "created_from"
    )
    applied = cross_graph_client.post(
        f"/graph-suggestions/{first['id']}/apply",
        json={"selected_indexes": [index]},
    )
    assert applied.status_code == 200

    second = cross_graph_client.post(f"/projects/{project_id}/graph/suggestions")
    assert second.status_code == 201
    assert not [
        item
        for item in second.json()["suggestions"]
        if item["subject_type"] == "entity"
        and item["entity_name"] == "GitHub"
        and item["relation_type"] == "created_from"
    ]


def test_empty_pending_batch_can_be_superseded_by_new_evidence(cross_graph_client: TestClient) -> None:
    project_id = _project(cross_graph_client)

    empty = cross_graph_client.post(f"/projects/{project_id}/graph/suggestions")
    assert empty.status_code == 201
    assert empty.json()["suggestions"] == []

    _seed_github_and_readme(cross_graph_client, project_id)
    refreshed = cross_graph_client.post(f"/projects/{project_id}/graph/suggestions")
    assert refreshed.status_code == 201
    assert refreshed.json()["id"] != empty.json()["id"]
    assert any(item["subject_type"] == "entity" for item in refreshed.json()["suggestions"])


def test_cross_knowledge_relation_can_be_removed(cross_graph_client: TestClient) -> None:
    project_id = _project(cross_graph_client)
    _seed_github_and_readme(cross_graph_client, project_id)
    batch = cross_graph_client.post(f"/projects/{project_id}/graph/suggestions").json()
    index = next(
        index
        for index, item in enumerate(batch["suggestions"])
        if item["subject_type"] == "entity" and item["relation_type"] == "created_from"
    )
    cross_graph_client.post(
        f"/graph-suggestions/{batch['id']}/apply",
        json={"selected_indexes": [index]},
    )

    graph = cross_graph_client.get("/graph").json()
    edge = next(edge for edge in graph["edges"] if edge["type"] == "created_from")
    relation_id = edge["metadata"]["relation_id"]
    removed = cross_graph_client.delete(f"/knowledge-relations/{relation_id}")
    assert removed.status_code == 204
    graph_after = cross_graph_client.get("/graph").json()
    assert not [edge for edge in graph_after["edges"] if edge["type"] == "created_from"]
