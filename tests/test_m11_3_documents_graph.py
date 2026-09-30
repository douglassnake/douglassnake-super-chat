from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app


@pytest.fixture()
def document_client() -> Generator[TestClient, None, None]:
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


def _project(client: TestClient, slug: str, name: str) -> str:
    response = client.post("/projects", json={"slug": slug, "name": name})
    assert response.status_code == 201
    return response.json()["id"]


def _document_payload() -> dict:
    return {
        "entity_name": "Arquitetura compartilhada",
        "entity_kind": "document",
        "entity_key": "docs/architecture.md",
        "relation_type": "has_document",
        "entity_description": "Documento de arquitetura usado pelos dois projetos.",
        "entity_metadata_json": {
            "document_type": "markdown",
            "source_type": "github",
            "external_id": "docs/architecture.md",
            "url": "https://github.com/douglassnake/shared/blob/main/docs/architecture.md",
        },
        "rationale": "Documenta a arquitetura operacional.",
        "source_ref": "docs/architecture.md",
    }


def test_shared_document_is_first_class_graph_node(document_client: TestClient) -> None:
    superchat = _project(document_client, "superchat-doc", "Super Chat")
    camara = _project(document_client, "camara-doc", "Camara360")

    first = document_client.post(
        f"/projects/{superchat}/relations",
        json=_document_payload(),
    )
    assert first.status_code == 201
    assert first.json()["relation_type"] == "has_document"
    entity_id = first.json()["entity"]["id"]

    second = document_client.post(
        f"/projects/{camara}/relations",
        json=_document_payload(),
    )
    assert second.status_code == 201
    assert second.json()["entity"]["id"] == entity_id

    graph = document_client.get("/graph")
    assert graph.status_code == 200
    payload = graph.json()

    documents = [node for node in payload["nodes"] if node["type"] == "document"]
    assert len(documents) == 1
    document = documents[0]
    assert document["label"] == "Arquitetura compartilhada"
    assert document["subtitle"] == "markdown"
    assert set(document["project_ids"]) == {superchat, camara}
    assert document["metadata"]["source_type"] == "github"
    assert document["metadata"]["external_id"] == "docs/architecture.md"
    assert document["metadata"]["url"].endswith("docs/architecture.md")

    assert not [
        node
        for node in payload["nodes"]
        if node["type"] == "entity" and node["entity_id"] == entity_id
    ]
    edges = [edge for edge in payload["edges"] if edge["type"] == "has_document"]
    assert len(edges) == 2
    assert {edge["target"] for edge in edges} == {document["id"]}
    assert all(edge["label"] == "HAS_DOCUMENT" for edge in edges)
    assert payload["counts"]["document"] == 1
    assert "has_document" in payload["relation_types"]


def test_document_controls_are_exposed_in_web_ui(document_client: TestClient) -> None:
    html = document_client.get("/app/")
    js = document_client.get("/app/graph.js")
    css = document_client.get("/app/graph.css")

    assert html.status_code == 200
    assert js.status_code == 200
    assert css.status_code == 200
    assert "+ Documento" in html.text
    assert 'data-graph-type="document"' in html.text
    assert "graph-document-dialog" in html.text
    assert "graph-document-url" in html.text
    assert 'relation_type: "has_document"' in js.text
    assert "Abrir documento" in js.text
    assert ".graph-node.document" in css.text
    assert ".graph-document-link" in css.text
