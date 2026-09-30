from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app


@pytest.fixture()
def suggestion_client() -> Generator[TestClient, None, None]:
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


def _project(client: TestClient, slug: str, name: str, description: str | None = None) -> str:
    response = client.post(
        "/projects",
        json={"slug": slug, "name": name, "description": description},
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_discovery_requires_review_before_persisting_relation(suggestion_client: TestClient) -> None:
    project_id = _project(suggestion_client, "auto-graph", "Auto Graph")
    source = suggestion_client.post(
        f"/projects/{project_id}/sources",
        json={
            "source_type": "github",
            "external_id": "douglassnake/example",
            "url": "https://github.com/douglassnake/example",
            "label": "Repositório principal",
            "metadata_json": {},
            "is_active": True,
        },
    )
    assert source.status_code == 201

    prepared = suggestion_client.post(f"/projects/{project_id}/graph/suggestions")
    assert prepared.status_code == 201
    batch = prepared.json()
    assert batch["status"] == "pending"
    assert len(batch["suggestions"]) == 1
    suggestion = batch["suggestions"][0]
    assert suggestion["entity_name"] == "GitHub"
    assert suggestion["relation_type"] == "uses"
    assert suggestion["confidence"] >= 0.9
    assert "Repositório principal" in suggestion["evidence"]

    graph_before = suggestion_client.get("/graph").json()
    assert not [node for node in graph_before["nodes"] if node["type"] == "entity" and node["label"] == "GitHub"]

    pending = suggestion_client.get(
        f"/projects/{project_id}/graph/suggestions",
        params={"status": "pending"},
    )
    assert pending.status_code == 200
    assert [item["id"] for item in pending.json()] == [batch["id"]]

    applied = suggestion_client.post(
        f"/graph-suggestions/{batch['id']}/apply",
        json={"selected_indexes": [0]},
    )
    assert applied.status_code == 200
    assert applied.json()["applied_count"] == 1
    assert applied.json()["batch"]["status"] == "applied"

    graph_after = suggestion_client.get("/graph").json()
    github_nodes = [node for node in graph_after["nodes"] if node["type"] == "entity" and node["label"] == "GitHub"]
    assert len(github_nodes) == 1
    edges = [edge for edge in graph_after["edges"] if edge["type"] == "uses" and edge["target"] == github_nodes[0]["id"]]
    assert len(edges) == 1
    assert edges[0]["semantic"] is True


def test_discard_keeps_graph_unchanged(suggestion_client: TestClient) -> None:
    project_id = _project(suggestion_client, "discard-graph", "Discard Graph")
    source = suggestion_client.post(
        f"/projects/{project_id}/sources",
        json={
            "source_type": "google_drive",
            "external_id": "folder-123",
            "label": "Drive do projeto",
            "metadata_json": {},
            "is_active": True,
        },
    )
    assert source.status_code == 201

    batch = suggestion_client.post(f"/projects/{project_id}/graph/suggestions").json()
    assert batch["suggestions"][0]["entity_name"] == "Google Drive"

    discarded = suggestion_client.post(f"/graph-suggestions/{batch['id']}/discard")
    assert discarded.status_code == 200
    assert discarded.json()["status"] == "discarded"

    graph = suggestion_client.get("/graph").json()
    assert not [node for node in graph["nodes"] if node.get("label") == "Google Drive"]


def test_existing_semantic_entity_is_not_suggested_again(suggestion_client: TestClient) -> None:
    project_id = _project(
        suggestion_client,
        "known-relation",
        "Known Relation",
        "A aplicação está implantada no ZimaOS e executa no NAS interno.",
    )
    relation = suggestion_client.post(
        f"/projects/{project_id}/relations",
        json={
            "entity_name": "ZimaOS",
            "entity_kind": "infrastructure",
            "relation_type": "runs_on",
        },
    )
    assert relation.status_code == 201

    batch = suggestion_client.post(f"/projects/{project_id}/graph/suggestions")
    assert batch.status_code == 201
    assert not [item for item in batch.json()["suggestions"] if item["entity_name"] == "ZimaOS"]


def test_existing_entity_mention_can_generate_evidence_backed_suggestion(suggestion_client: TestClient) -> None:
    first = _project(suggestion_client, "infra-owner", "Infra Owner")
    created = suggestion_client.post(
        f"/projects/{first}/relations",
        json={
            "entity_name": "Caddy",
            "entity_kind": "service",
            "relation_type": "uses",
            "entity_description": "Reverse proxy HTTPS interno.",
        },
    )
    assert created.status_code == 201

    second = _project(
        suggestion_client,
        "caddy-mention",
        "Caddy Mention",
        "O projeto utiliza Caddy como proxy HTTPS para publicação interna.",
    )
    prepared = suggestion_client.post(f"/projects/{second}/graph/suggestions")
    assert prepared.status_code == 201
    suggestions = prepared.json()["suggestions"]
    caddy = next(item for item in suggestions if item["entity_name"] == "Caddy")
    assert caddy["relation_type"] == "uses"
    assert caddy["source_ref"].startswith("project:")
    assert "Caddy" in caddy["evidence"]


def test_graph_suggestion_web_assets_are_exposed(suggestion_client: TestClient) -> None:
    html = suggestion_client.get("/app/")
    js = suggestion_client.get("/app/graph_suggestions.js")
    css = suggestion_client.get("/app/graph_suggestions.css")
    assert html.status_code == 200
    assert js.status_code == 200
    assert css.status_code == 200
    assert "Descobrir conexões" in html.text
    assert "graph-suggestion-dialog" in html.text
    assert "Aplicar selecionadas" in html.text
    assert "/graph/suggestions" in js.text
    assert "selected_indexes" in js.text
    assert "Evidência" in js.text
