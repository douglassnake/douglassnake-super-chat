from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import ContextItem, Decision, Project, ProjectSource, SessionDelta, Task


def graph_client() -> Generator[tuple[TestClient, sessionmaker], None, None]:
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
    try:
        with TestClient(app) as client:
            yield client, TestingSessionLocal
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=engine)


def test_graph_contains_existing_project_records_and_shared_sources() -> None:
    fixture = graph_client()
    client, SessionFactory = next(fixture)
    try:
        with SessionFactory() as db:
            alpha = Project(slug="alpha", name="Alpha", status="active", priority=90)
            beta = Project(slug="beta", name="Beta", status="active", priority=70)
            db.add_all([alpha, beta])
            db.flush()

            db.add(
                Task(
                    project_id=alpha.id,
                    title="Documentar arquitetura",
                    status="todo",
                    priority=85,
                )
            )
            db.add(
                Decision(
                    project_id=alpha.id,
                    title="Usar Caddy compartilhado",
                    body="Centralizar HTTPS.",
                    status="active",
                )
            )
            db.add(
                ContextItem(
                    project_id=alpha.id,
                    kind="deployment",
                    title="Implantação no NAS",
                    content="Serviço self-hosted.",
                    importance=1.0,
                    source_type="manual",
                )
            )
            for project in (alpha, beta):
                db.add(
                    ProjectSource(
                        project_id=project.id,
                        source_type="github",
                        external_id="douglassnake/shared",
                        url="https://github.com/douglassnake/shared",
                        label="Repositório compartilhado",
                        is_active=True,
                    )
                )
            db.add(
                SessionDelta(
                    project_id=alpha.id,
                    session_key="review-1",
                    status="pending",
                    summary="Revisar proposta.",
                )
            )
            db.commit()

        response = client.get("/graph")
        assert response.status_code == 200
        payload = response.json()

        node_types = [node["type"] for node in payload["nodes"]]
        assert node_types.count("project") == 2
        assert node_types.count("task") == 1
        assert node_types.count("decision") == 1
        assert node_types.count("memory") == 1
        assert node_types.count("delta") == 1
        assert node_types.count("source") == 1

        shared_source = next(node for node in payload["nodes"] if node["type"] == "source")
        assert len(shared_source["project_ids"]) == 2
        source_edges = [edge for edge in payload["edges"] if edge["type"] == "uses_source"]
        assert len(source_edges) == 2
        assert {edge["target"] for edge in source_edges} == {shared_source["id"]}

        assert payload["counts"]["project"] == 2
        assert "has_task" in payload["relation_types"]
        assert "uses_source" in payload["relation_types"]
    finally:
        try:
            next(fixture)
        except StopIteration:
            pass


def test_graph_excludes_completed_tasks_and_inactive_sources() -> None:
    fixture = graph_client()
    client, SessionFactory = next(fixture)
    try:
        with SessionFactory() as db:
            project = Project(slug="filtered", name="Filtered")
            db.add(project)
            db.flush()
            db.add_all(
                [
                    Task(project_id=project.id, title="Concluída", status="done"),
                    ProjectSource(
                        project_id=project.id,
                        source_type="github",
                        external_id="douglassnake/inactive",
                        label="Inativa",
                        is_active=False,
                    ),
                ]
            )
            db.commit()

        payload = client.get("/graph").json()
        assert [node["type"] for node in payload["nodes"]] == ["project"]
        assert payload["edges"] == []
    finally:
        try:
            next(fixture)
        except StopIteration:
            pass
