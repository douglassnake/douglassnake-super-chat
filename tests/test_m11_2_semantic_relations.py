from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app


@pytest.fixture()
def semantic_client() -> Generator[TestClient, None, None]:
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


def test_semantic_relation_is_typed_and_shared_entity_converges(semantic_client: TestClient) -> None:
    superchat = _project(semantic_client, "superchat", "Super Chat")
    camara = _project(semantic_client, "camara360", "Camara360")

    first = semantic_client.post(
        f"/projects/{superchat}/relations",
        json={
            "entity_name": "ZimaOS",
            "entity_kind": "infrastructure",
            "relation_type": "runs_on",
            "entity_description": "Servidor NAS interno.",
            "rationale": "Hospeda o stack Docker do projeto.",
        },
    )
    assert first.status_code == 201
    assert first.json()["relation_type"] == "runs_on"
    entity_id = first.json()["entity"]["id"]

    second = semantic_client.post(
        f"/projects/{camara}/relations",
        json={
            "entity_name": "ZimaOS",
            "entity_kind": "infrastructure",
            "relation_type": "runs_on",
        },
    )
    assert second.status_code == 201
    assert second.json()["entity"]["id"] == entity_id

    graph = semantic_client.get("/graph")
    assert graph.status_code == 200
    payload = graph.json()
    entities = [node for node in payload["nodes"] if node["type"] == "entity"]
    assert len(entities) == 1
    assert entities[0]["label"] == "ZimaOS"
    assert set(entities[0]["project_ids"]) == {superchat, camara}

    edges = [edge for edge in payload["edges"] if edge["type"] == "runs_on"]
    assert len(edges) == 2
    assert {edge["target"] for edge in edges} == {entities[0]["id"]}
    assert all(edge["label"] == "RUNS_ON" for edge in edges)
    assert all(edge["semantic"] is True for edge in edges)
    assert "runs_on" in payload["relation_types"]


def test_duplicate_relation_conflicts_and_delete_hides_edge(semantic_client: TestClient) -> None:
    project_id = _project(semantic_client, "alpha", "Alpha")
    payload = {
        "entity_name": "PostgreSQL",
        "entity_kind": "database",
        "relation_type": "depends_on",
    }
    created = semantic_client.post(f"/projects/{project_id}/relations", json=payload)
    assert created.status_code == 201
    relation_id = created.json()["id"]

    duplicate = semantic_client.post(f"/projects/{project_id}/relations", json=payload)
    assert duplicate.status_code == 409

    listed = semantic_client.get(f"/projects/{project_id}/relations")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [relation_id]

    deleted = semantic_client.delete(f"/relations/{relation_id}")
    assert deleted.status_code == 204
    assert semantic_client.get(f"/projects/{project_id}/relations").json() == []
    assert not [edge for edge in semantic_client.get("/graph").json()["edges"] if edge["type"] == "depends_on"]


def test_relation_type_validation_and_web_controls(semantic_client: TestClient) -> None:
    project_id = _project(semantic_client, "typed", "Typed")
    invalid = semantic_client.post(
        f"/projects/{project_id}/relations",
        json={"entity_name": "Anything", "entity_kind": "system", "relation_type": "invented"},
    )
    assert invalid.status_code == 422

    html = semantic_client.get("/app/")
    js = semantic_client.get("/app/graph.js")
    css = semantic_client.get("/app/graph.css")
    assert html.status_code == 200
    assert js.status_code == 200
    assert css.status_code == 200
    assert "+ Relação" in html.text
    assert 'data-graph-type="entity"' in html.text
    assert "graph-relation-dialog" in html.text
    assert "/relations" in js.text
    assert "RUNS_ON" in js.text
    assert ".graph-node.entity" in css.text
