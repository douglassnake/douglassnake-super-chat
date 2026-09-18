from collections.abc import Generator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.routes as routes_module
from app.database import Base, get_db
from app.google_context import build_context_with_google
from app.google_sync import sync_project_google as real_sync_project_google
from app.main import app
from app.models import ContextItem, Event, Project, ProjectSource


class FakeGoogleReader:
    def drive_metadata(self, file_id: str) -> dict:
        return {
            "id": file_id,
            "name": "Plano Segundo Cérebro",
            "mimeType": "application/vnd.google-apps.document",
            "modifiedTime": "2026-09-18T12:00:00Z",
            "webViewLink": f"https://docs.google.com/document/d/{file_id}/edit",
            "trashed": False,
        }

    def drive_text(self, file_id: str, metadata: dict) -> str:
        filler = "arquitetura integração memória projeto " * 80
        target = (
            "A próxima etapa documental usa recuperação sob demanda do Google Drive, "
            "sem persistir o documento completo no banco. O Context Engine deve selecionar "
            "apenas o trecho relevante para economizar tokens."
        )
        return filler + target + filler

    def calendar_events(self, calendar_id: str, *, time_min, time_max) -> list[dict]:
        return [
            {
                "id": "event-1",
                "summary": "Reunião Segundo Cérebro",
                "description": "Revisar integração com Google Drive e Calendar.",
                "location": "Online",
                "status": "confirmed",
                "start": {"dateTime": "2026-09-20T13:00:00Z"},
                "end": {"dateTime": "2026-09-20T14:00:00Z"},
                "updated": "2026-09-18T12:30:00Z",
                "htmlLink": "https://calendar.google.com/calendar/event?eid=event-1",
            }
        ]


@pytest.fixture()
def google_client() -> Generator[tuple[TestClient, sessionmaker], None, None]:
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


def _project_with_google_sources(client: TestClient) -> tuple[str, str, str]:
    project = client.post(
        "/projects",
        json={
            "slug": "google-context",
            "name": "Google Context",
            "status": "implementation",
            "next_action": "Validar integração Google",
        },
    ).json()
    project_id = project["id"]

    drive = client.post(
        f"/projects/{project_id}/sources",
        json={
            "source_type": "google_drive",
            "external_id": "drive-file-1",
            "label": "Plano Segundo Cérebro",
        },
    )
    assert drive.status_code == 201

    calendar = client.post(
        f"/projects/{project_id}/sources",
        json={
            "source_type": "google_calendar",
            "external_id": "primary",
            "label": "Agenda principal",
        },
    )
    assert calendar.status_code == 201
    return project_id, drive.json()["id"], calendar.json()["id"]


def test_google_sync_is_idempotent_and_drive_is_on_demand(
    google_client: tuple[TestClient, sessionmaker],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, SessionFactory = google_client
    project_id, drive_source_id, calendar_source_id = _project_with_google_sources(client)
    fake_reader = FakeGoogleReader()

    def fake_sync(db: Session, project: Project):
        return real_sync_project_google(db, project, fake_reader)

    def fake_context(db: Session, project: Project, query: str, profile: str):
        return build_context_with_google(db, project, query, profile, reader=fake_reader)

    monkeypatch.setattr(routes_module, "sync_project_google", fake_sync)
    monkeypatch.setattr(routes_module, "build_project_context", fake_context)

    first = client.post(f"/projects/{project_id}/google/sync")
    assert first.status_code == 200
    first_payload = first.json()
    assert first_payload["drive_sources"] == 1
    assert first_payload["calendar_sources"] == 1
    assert first_payload["created_events"] == 1
    assert first_payload["updated_events"] == 0

    second = client.post(f"/projects/{project_id}/google/sync")
    assert second.status_code == 200
    second_payload = second.json()
    assert second_payload["created_events"] == 0
    assert second_payload["updated_events"] == 0
    assert second_payload["skipped_events"] == 1

    with SessionFactory() as db:
        assert db.scalar(select(func.count(Event.id))) == 1
        assert db.scalar(select(func.count(ContextItem.id))) == 0

        drive_source = db.get(ProjectSource, UUID(drive_source_id))
        calendar_source = db.get(ProjectSource, UUID(calendar_source_id))
        assert drive_source is not None
        assert calendar_source is not None
        assert drive_source.metadata_json["name"] == "Plano Segundo Cérebro"
        assert "last_synced_at" in drive_source.metadata_json
        assert calendar_source.metadata_json["last_sync"]["events"] == 1
        serialized_metadata = f"{drive_source.metadata_json} {calendar_source.metadata_json}".lower()
        assert "access_token" not in serialized_metadata
        assert "refresh_token" not in serialized_metadata
        assert "client_secret" not in serialized_metadata

    context = client.get(
        f"/projects/{project_id}/continue",
        params={
            "profile": "standard",
            "query": "recuperação sob demanda Google Drive economizar tokens documento completo agenda reunião",
        },
    )
    assert context.status_code == 200
    package = context.json()
    assert package["budget"]["estimated_tokens"] <= package["budget"]["max_tokens"]
    assert any(item["source_type"] == "google_drive" for item in package["items"])
    assert any(
        "recuperação sob demanda" in item["content"]
        for item in package["items"]
        if item["source_type"] == "google_drive"
    )
    assert any(item["source_type"] == "google_calendar" for item in package["items"])

    with SessionFactory() as db:
        # Drive text remains transient: only metadata/reference is persistent.
        assert db.scalar(select(func.count(ContextItem.id))) == 0


def test_continue_degrades_without_google_oauth(
    google_client: tuple[TestClient, sessionmaker],
) -> None:
    client, _ = google_client
    project_id = client.post(
        "/projects",
        json={
            "slug": "google-offline",
            "name": "Google Offline",
            "next_action": "Continuar com memória local",
        },
    ).json()["id"]
    source = client.post(
        f"/projects/{project_id}/sources",
        json={
            "source_type": "google_drive",
            "external_id": "unavailable-file",
            "label": "Documento indisponível",
        },
    )
    assert source.status_code == 201

    response = client.get(
        f"/projects/{project_id}/continue",
        params={"profile": "minimal", "query": "continuar projeto"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["project"]["name"] == "Google Offline"
    assert payload["budget"]["estimated_tokens"] <= payload["budget"]["max_tokens"]


def test_google_sources_require_external_id(google_client: tuple[TestClient, sessionmaker]) -> None:
    client, _ = google_client
    project_id = client.post(
        "/projects",
        json={"slug": "invalid-google", "name": "Invalid Google"},
    ).json()["id"]

    for source_type in ("google_drive", "google_calendar"):
        response = client.post(
            f"/projects/{project_id}/sources",
            json={"source_type": source_type, "label": "Inválida"},
        )
        assert response.status_code == 422
