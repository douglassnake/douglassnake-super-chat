from collections.abc import Generator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.routes as routes_module
from app.database import Base, get_db
from app.github_sync import sync_project_github as real_sync_project_github
from app.main import app
from app.models import Event, ProjectSource


class FakeGitHubReader:
    def repository(self, repository: str) -> dict:
        return {"full_name": repository, "default_branch": "main", "private": False}

    def commits(self, repository: str) -> list[dict]:
        return [
            {
                "sha": "abc123456789",
                "html_url": f"https://github.com/{repository}/commit/abc123456789",
                "commit": {
                    "message": "feat: adicionar contexto técnico\n\nDetalhes do commit.",
                    "author": {"name": "Dev", "date": "2026-09-18T12:00:00Z"},
                },
            }
        ]

    def pulls(self, repository: str) -> list[dict]:
        return [
            {
                "number": 12,
                "title": "Context Engine",
                "body": "Implementa recuperação seletiva.",
                "state": "open",
                "draft": False,
                "updated_at": "2026-09-18T12:10:00Z",
                "html_url": f"https://github.com/{repository}/pull/12",
                "head": {"ref": "feature/context"},
                "base": {"ref": "main"},
            }
        ]

    def issues(self, repository: str) -> list[dict]:
        return [
            {
                "number": 22,
                "title": "Corrigir orçamento de tokens",
                "body": "Garantir que o pacote permaneça dentro do limite.",
                "state": "open",
                "updated_at": "2026-09-18T12:20:00Z",
                "html_url": f"https://github.com/{repository}/issues/22",
            }
        ]

    def workflow_runs(self, repository: str) -> list[dict]:
        return [
            {
                "id": 99,
                "name": "tests",
                "display_title": "pytest",
                "status": "completed",
                "conclusion": "failure",
                "head_branch": "feature/context",
                "head_sha": "abc123456789",
                "updated_at": "2026-09-18T12:30:00Z",
                "html_url": f"https://github.com/{repository}/actions/runs/99",
            }
        ]


@pytest.fixture()
def github_client() -> Generator[tuple[TestClient, sessionmaker], None, None]:
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


def test_github_source_sync_is_idempotent_and_enters_context(
    github_client: tuple[TestClient, sessionmaker],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, SessionFactory = github_client
    project = client.post(
        "/projects",
        json={
            "slug": "github-project",
            "name": "GitHub Project",
            "status": "implementation",
            "next_action": "Revisar CI e PRs",
        },
    ).json()
    project_id = project["id"]
    project_uuid = UUID(project_id)

    source_response = client.post(
        f"/projects/{project_id}/sources",
        json={
            "source_type": "github",
            "external_id": "douglassnake/example",
            "url": "https://github.com/douglassnake/example",
            "label": "Código principal",
        },
    )
    assert source_response.status_code == 201
    assert source_response.json()["external_id"] == "douglassnake/example"

    duplicate_source = client.post(
        f"/projects/{project_id}/sources",
        json={
            "source_type": "github",
            "external_id": "douglassnake/example",
            "label": "Duplicado",
        },
    )
    assert duplicate_source.status_code == 409

    def fake_sync(db: Session, project_obj):
        return real_sync_project_github(db, project_obj, FakeGitHubReader())

    monkeypatch.setattr(routes_module, "sync_project_github", fake_sync)

    first_sync = client.post(f"/projects/{project_id}/github/sync")
    assert first_sync.status_code == 200
    first = first_sync.json()
    assert first["created_events"] == 4
    assert first["skipped_events"] == 0
    assert first["sources"][0]["default_branch"] == "main"

    second_sync = client.post(f"/projects/{project_id}/github/sync")
    assert second_sync.status_code == 200
    second = second_sync.json()
    assert second["created_events"] == 0
    assert second["skipped_events"] == 4

    with SessionFactory() as db:
        event_count = db.scalar(select(func.count(Event.id)))
        assert event_count == 4
        source = db.scalar(select(ProjectSource).where(ProjectSource.project_id == project_uuid))
        assert source is not None
        assert source.metadata_json["default_branch"] == "main"
        assert "last_synced_at" in source.metadata_json
        assert "token" not in str(source.metadata_json).lower()

    context = client.get(
        f"/projects/{project_id}/continue",
        params={"profile": "standard", "query": "commit PR issue action failure CI"},
    )
    assert context.status_code == 200
    package = context.json()
    github_items = [item for item in package["items"] if item["source_type"] == "github"]
    assert github_items
    assert any("Action" in (item["title"] or "") for item in github_items)
    assert package["budget"]["estimated_tokens"] <= package["budget"]["max_tokens"]


def test_github_sync_requires_active_source(github_client: tuple[TestClient, sessionmaker]) -> None:
    client, _ = github_client
    project_id = client.post(
        "/projects",
        json={"slug": "no-source", "name": "No Source"},
    ).json()["id"]

    response = client.post(f"/projects/{project_id}/github/sync")
    assert response.status_code == 400


def test_github_source_requires_owner_repo(github_client: tuple[TestClient, sessionmaker]) -> None:
    client, _ = github_client
    project_id = client.post(
        "/projects",
        json={"slug": "invalid-source", "name": "Invalid Source"},
    ).json()["id"]
    response = client.post(
        f"/projects/{project_id}/sources",
        json={"source_type": "github", "external_id": "invalid", "label": "Invalid"},
    )
    assert response.status_code == 422
