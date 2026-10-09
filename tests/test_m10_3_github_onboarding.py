from collections.abc import Generator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.onboarding_routes as onboarding_routes
from app.database import Base, get_db
from app.github_onboarding import prepare_github_onboarding as real_prepare_github_onboarding
from app.main import app
from app.models import Decision, Project, SessionDelta, SessionSummary, Task


class FakeGitHubReader:
    def repository(self, repository: str) -> dict:
        return {"full_name": repository, "default_branch": "main", "private": False}

    def commits(self, repository: str) -> list[dict]:
        return [
            {
                "sha": "abc123456789",
                "html_url": f"https://github.com/{repository}/commit/abc123456789",
                "commit": {
                    "message": "feat: estado inicial",
                    "author": {"name": "Dev", "date": "2026-09-29T12:00:00Z"},
                },
            }
        ]

    def pulls(self, repository: str) -> list[dict]:
        return [
            {
                "number": 12,
                "title": "Preparar produção",
                "body": "Checklist de produção.",
                "state": "open",
                "draft": False,
                "updated_at": "2026-09-29T12:10:00Z",
                "html_url": f"https://github.com/{repository}/pull/12",
                "head": {"ref": "feature/prod"},
                "base": {"ref": "main"},
            }
        ]

    def issues(self, repository: str) -> list[dict]:
        return [
            {
                "number": 22,
                "title": "Documentar recuperação",
                "body": "Adicionar runbook.",
                "state": "open",
                "updated_at": "2026-09-29T12:20:00Z",
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
                "head_branch": "main",
                "head_sha": "abc123456789",
                "updated_at": "2026-09-29T12:30:00Z",
                "html_url": f"https://github.com/{repository}/actions/runs/99",
            }
        ]


@pytest.fixture()
def onboarding_client() -> Generator[tuple[TestClient, sessionmaker], None, None]:
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


def test_github_onboarding_requires_review_before_memory_changes(
    onboarding_client: tuple[TestClient, sessionmaker],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, SessionFactory = onboarding_client
    project = client.post(
        "/projects",
        json={"slug": "onboarding", "name": "Onboarding", "status": "active"},
    ).json()
    project_id = project["id"]
    project_uuid = UUID(project_id)

    source = client.post(
        f"/projects/{project_id}/sources",
        json={
            "source_type": "github",
            "external_id": "douglassnake/example",
            "url": "https://github.com/douglassnake/example",
            "label": "Código principal",
        },
    )
    assert source.status_code == 201

    def fake_prepare(db: Session, project_obj: Project):
        return real_prepare_github_onboarding(db, project_obj, reader=FakeGitHubReader())

    monkeypatch.setattr(onboarding_routes, "prepare_github_onboarding", fake_prepare)

    prepared = client.post(f"/projects/{project_id}/github/onboarding")
    assert prepared.status_code == 200
    payload = prepared.json()
    assert payload["requires_review"] is True
    assert payload["suggested_decisions"] == 1
    assert payload["suggested_tasks"] == 3
    assert payload["current_failed_workflows"] == 1
    assert payload["delta"]["status"] == "pending"
    assert payload["sync"]["created_events"] == 4

    delta_id = payload["delta"]["id"]

    with SessionFactory() as db:
        assert db.scalar(select(func.count(Decision.id))) == 0
        assert db.scalar(select(func.count(Task.id))) == 0
        assert db.scalar(select(func.count(SessionSummary.id))) == 0
        delta = db.get(SessionDelta, UUID(delta_id))
        assert delta is not None
        assert delta.project_id == project_uuid
        assert delta.status == "pending"

    duplicate = client.post(f"/projects/{project_id}/github/onboarding")
    assert duplicate.status_code == 409

    preview = client.get(f"/session-deltas/{delta_id}/preview")
    assert preview.status_code == 200
    assert len(preview.json()["delta"]["decisions_json"]) == 1
    assert len(preview.json()["delta"]["tasks_json"]) == 3

    applied = client.post(f"/session-deltas/{delta_id}/apply")
    assert applied.status_code == 200
    applied_payload = applied.json()
    assert len(applied_payload["created_decision_ids"]) == 1
    assert len(applied_payload["created_task_ids"]) == 3
    assert applied_payload["project_next_action"] == "Investigar falhas atuais de CI"

    with SessionFactory() as db:
        assert db.scalar(select(func.count(Decision.id))) == 1
        assert db.scalar(select(func.count(Task.id))) == 3
        assert db.scalar(select(func.count(SessionSummary.id))) == 1
        project_row = db.get(Project, project_uuid)
        assert project_row is not None
        assert project_row.next_action == "Investigar falhas atuais de CI"



def test_applying_onboarding_cannot_replace_existing_specific_next_action(
    onboarding_client: tuple[TestClient, sessionmaker],
) -> None:
    client, _ = onboarding_client
    project = client.post(
        "/projects",
        json={
            "slug": "action-preserved",
            "name": "Action preserved",
            "next_action": "Validar o PR #38 do M3.2 antes de integrar",
        },
    ).json()
    project_id = project["id"]

    onboarding = client.post(
        f"/projects/{project_id}/session-deltas",
        json={
            "session_key": "github-onboarding:test-specific-action",
            "summary": "Snapshot histórico importado do GitHub.",
            "next_action": "Revisar pull requests abertos",
        },
    )
    assert onboarding.status_code == 201
    applied = client.post(f"/session-deltas/{onboarding.json()['id']}/apply")
    assert applied.status_code == 200
    assert applied.json()["project_next_action"] == "Validar o PR #38 do M3.2 antes de integrar"

    # A deliberate, manually reviewed non-onboarding delta still changes the action.
    reviewed = client.post(
        f"/projects/{project_id}/session-deltas",
        json={
            "session_key": "manual:action-review",
            "summary": "Proxima etapa aprovada manualmente.",
            "next_action": "Iniciar M3.3 apos revisao",
        },
    )
    assert reviewed.status_code == 201
    manual = client.post(f"/session-deltas/{reviewed.json()['id']}/apply")
    assert manual.status_code == 200
    assert manual.json()["project_next_action"] == "Iniciar M3.3 apos revisao"



def test_github_onboarding_requires_active_source(onboarding_client: tuple[TestClient, sessionmaker]) -> None:
    client, _ = onboarding_client
    project_id = client.post(
        "/projects",
        json={"slug": "without-github", "name": "Without GitHub"},
    ).json()["id"]

    response = client.post(f"/projects/{project_id}/github/onboarding")
    assert response.status_code == 400


def test_web_exposes_reviewed_onboarding_controls(onboarding_client: tuple[TestClient, sessionmaker]) -> None:
    client, _ = onboarding_client
    html = client.get("/app/")
    js = client.get("/app/onboarding.js")
    css = client.get("/app/onboarding.css")

    assert html.status_code == 200
    assert js.status_code == 200
    assert css.status_code == 200
    assert "Projeto + GitHub" in html.text
    assert "Preparar onboarding" in html.text
    assert "Aplicar sugestões" in html.text
    assert "/github/onboarding" in js.text
    assert "Não informe token" in html.text
    assert "github_token" not in js.text.lower()
