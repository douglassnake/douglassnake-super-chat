from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.dashboard import calculate_health_score
from app.database import Base, get_db
from app.main import app


@pytest.fixture()
def web_client() -> Generator[TestClient, None, None]:
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


def test_health_score_is_deterministic() -> None:
    now = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)
    project = SimpleNamespace(
        next_action=None,
        last_activity_at=now - timedelta(days=20),
        updated_at=now - timedelta(days=20),
    )

    result = calculate_health_score(
        project,
        open_tasks=5,
        overdue_tasks=2,
        blocked_tasks=1,
        pending_deltas=1,
        recent_failed_runs=1,
        now=now,
    )

    # 100 -20 (sem próxima ação) -16 (vencidas) -8 (bloqueada)
    # -15 (20 dias inativo) -5 (delta) -10 (CI) = 26.
    assert result["score"] == 26
    assert result["level"] == "critical"
    assert result["metrics"]["inactivity_days"] == 20
    assert {reason["code"] for reason in result["reasons"]} == {
        "missing_next_action",
        "overdue_tasks",
        "blocked_tasks",
        "inactive_14d",
        "pending_deltas",
        "failed_ci",
    }


def test_web_app_and_dashboard_flow(web_client: TestClient) -> None:
    root = web_client.get("/", follow_redirects=False)
    assert root.status_code in {302, 307}
    assert root.headers["location"] == "/app/"

    html = web_client.get("/app/")
    assert html.status_code == 200
    assert "Super Chat" in html.text
    assert "Continuar projeto" in html.text
    assert "Session Memory" in html.text

    css = web_client.get("/app/styles.css")
    js = web_client.get("/app/app.js")
    assert css.status_code == 200
    assert js.status_code == 200
    assert "window.confirm" in js.text
    assert "/continue" in js.text

    empty_dashboard = web_client.get("/dashboard")
    assert empty_dashboard.status_code == 200
    assert empty_dashboard.json()["project_count"] == 0

    project_response = web_client.post(
        "/projects",
        json={
            "slug": "super-chat-ui",
            "name": "Super Chat UI",
            "status": "implementation",
            "priority": 100,
        },
    )
    assert project_response.status_code == 201
    project_id = project_response.json()["id"]

    blocked_task = web_client.post(
        f"/projects/{project_id}/tasks",
        json={
            "title": "Validar interface",
            "status": "blocked",
            "blocked_by": "Revisão visual",
            "priority": 90,
        },
    )
    assert blocked_task.status_code == 201

    delta_response = web_client.post(
        f"/projects/{project_id}/session-deltas",
        json={
            "session_key": "ui-test-1",
            "summary": "Interface pronta para revisão.",
            "next_action": "Revisar dashboard no navegador",
        },
    )
    assert delta_response.status_code == 201

    dashboard = web_client.get("/dashboard")
    assert dashboard.status_code == 200
    payload = dashboard.json()
    assert payload["project_count"] == 1
    assert payload["attention_count"] == 1
    assert payload["pending_delta_count"] == 1

    project = payload["projects"][0]
    assert project["name"] == "Super Chat UI"
    assert project["health"]["score"] == 67
    assert project["health"]["level"] == "attention"
    assert project["health"]["metrics"]["blocked_tasks"] == 1
    assert project["health"]["metrics"]["pending_deltas"] == 1

    overview = web_client.get(f"/projects/{project_id}/overview")
    assert overview.status_code == 200
    detail = overview.json()
    assert detail["project"]["id"] == project_id
    assert len(detail["tasks"]) == 1
    assert len(detail["pending_deltas"]) == 1
    assert detail["pending_deltas"][0]["session_key"] == "ui-test-1"

    context = web_client.get(
        f"/projects/{project_id}/continue",
        params={"profile": "minimal", "query": "status próxima ação tarefa bloqueio"},
    )
    assert context.status_code == 200
    context_payload = context.json()
    assert context_payload["profile"] == "minimal"
    assert context_payload["budget"]["estimated_tokens"] <= context_payload["budget"]["max_tokens"]
