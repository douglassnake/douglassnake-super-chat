from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.executor_routes as executor_routes_module
from app.database import Base, get_db
from app.executor_control import ExecutorOutcome
from app.main import app


@pytest.fixture()
def executor_client() -> Generator[TestClient, None, None]:
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


def setup_execution(client: TestClient) -> tuple[dict, dict, dict]:
    project = client.post(
        "/projects",
        json={
            "slug": "executor-project",
            "name": "Executor Project",
            "status": "implementation",
            "next_action": "Validar executor controlado",
        },
    )
    assert project.status_code == 201
    project_id = project.json()["id"]

    context = client.post(
        f"/projects/{project_id}/context-items",
        json={
            "kind": "decision",
            "title": "Executor policy",
            "content": "Ações precisam de allowlist explícita.",
            "importance": 1.0,
            "source_type": "manual",
            "source_ref": "manual:executor-policy",
        },
    )
    assert context.status_code == 201

    pack = client.post(
        "/agent-task-packs",
        json={
            "project_id": project_id,
            "objective": "Validar executor controlado",
            "acceptance_criteria": ["A ação autorizada deve ser auditável"],
            "constraints": ["Não fazer merge, deploy ou publicação"],
            "profile": "minimal",
            "query": "executor política allowlist",
        },
    )
    assert pack.status_code == 201
    approved = client.post(f"/agent-task-packs/{pack.json()['id']}/approve")
    assert approved.status_code == 200

    handoff = client.post(
        f"/agent-task-packs/{approved.json()['id']}/handoffs",
        json={
            "executor_type": "controlled",
            "executor_target": "test-adapter",
            "allowed_actions": ["read_repository", "run_tests", "create_commit"],
        },
    )
    assert handoff.status_code == 201
    released = client.post(f"/agent-handoffs/{handoff.json()['id']}/release")
    assert released.status_code == 200

    execution = client.post(f"/agent-handoffs/{released.json()['id']}/execution")
    assert execution.status_code == 201
    return approved.json(), released.json(), execution.json()


def test_executor_request_requires_allowlist_and_rejects_arbitrary_commands(
    executor_client: TestClient,
) -> None:
    client = executor_client
    _, _, execution = setup_execution(client)

    not_authorized = client.post(
        f"/agent-executions/{execution['id']}/executor-requests",
        json={"action": "create_branch", "payload": {"branch_name": "feature/test"}},
    )
    assert not_authorized.status_code == 409

    forbidden = client.post(
        f"/agent-executions/{execution['id']}/executor-requests",
        json={"action": "deploy", "payload": {}},
    )
    assert forbidden.status_code == 422

    arbitrary_shell = client.post(
        f"/agent-executions/{execution['id']}/executor-requests",
        json={
            "action": "run_tests",
            "payload": {"command": "pytest -q", "target": "tests/"},
        },
    )
    assert arbitrary_shell.status_code == 422
    assert "arbitrary command" in arbitrary_shell.json()["detail"].lower()

    nested_shell = client.post(
        f"/agent-executions/{execution['id']}/executor-requests",
        json={
            "action": "run_tests",
            "payload": {"options": {"argv": ["pytest", "-q"]}},
        },
    )
    assert nested_shell.status_code == 422


def test_prepare_release_and_execute_with_injected_adapter(
    executor_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = executor_client
    _, _, execution = setup_execution(client)
    calls = []

    class FakeAdapter:
        name = "fake"
        available = True

        def execute(self, command):
            calls.append(command)
            return ExecutorOutcome(
                ok=True,
                result={
                    "tests": "passed",
                    "token": "adapter-result-secret",
                    "observed_target": command.payload.get("test_target"),
                },
            )

    monkeypatch.setattr(executor_routes_module, "resolve_executor_adapter", lambda _: FakeAdapter())

    created = client.post(
        f"/agent-executions/{execution['id']}/executor-requests",
        json={
            "action": "run_tests",
            "adapter_type": "fake",
            "payload": {
                "test_target": "tests/test_m8_4_controlled_executor.py",
                "token": "payload-secret",
            },
            "notes": "Executar apenas testes api_key=note-secret",
        },
    )
    assert created.status_code == 201
    request = created.json()
    assert request["status"] == "prepared"
    assert calls == []
    serialized = str(request).lower()
    assert "payload-secret" not in serialized
    assert "note-secret" not in serialized
    assert "[redacted]" in serialized

    duplicate = client.post(
        f"/agent-executions/{execution['id']}/executor-requests",
        json={
            "action": "run_tests",
            "adapter_type": "fake",
            "payload": {
                "test_target": "tests/test_m8_4_controlled_executor.py",
                "token": "another-secret",
            },
            "notes": "nota diferente não altera fingerprint",
        },
    )
    assert duplicate.status_code == 409

    before_release = client.post(f"/executor-requests/{request['id']}/execute")
    assert before_release.status_code == 409
    assert calls == []

    released = client.post(f"/executor-requests/{request['id']}/release")
    assert released.status_code == 200
    assert released.json()["status"] == "released"
    assert calls == []

    executed = client.post(f"/executor-requests/{request['id']}/execute")
    assert executed.status_code == 200
    body = executed.json()
    assert body["status"] == "completed"
    assert len(calls) == 1
    assert calls[0].action == "run_tests"
    assert calls[0].payload["test_target"] == "tests/test_m8_4_controlled_executor.py"
    assert calls[0].payload["token"] == "[REDACTED]"
    assert "adapter-result-secret" not in str(body).lower()
    assert body["result"]["token"] == "[REDACTED]"

    replay = client.post(f"/executor-requests/{request['id']}/execute")
    assert replay.status_code == 409
    assert len(calls) == 1

    events = client.get(f"/agent-executions/{execution['id']}/events")
    assert events.status_code == 200
    event_types = [item["event_type"] for item in events.json()]
    assert event_types[-4:] == [
        "executor_request",
        "executor_released",
        "executor_started",
        "executor_result",
    ]


def test_manual_adapter_is_inert_and_request_can_be_cancelled(
    executor_client: TestClient,
) -> None:
    client = executor_client
    _, _, execution = setup_execution(client)

    created = client.post(
        f"/agent-executions/{execution['id']}/executor-requests",
        json={
            "action": "read_repository",
            "adapter_type": "manual",
            "payload": {"scope": "metadata"},
        },
    )
    assert created.status_code == 201
    request_id = created.json()["id"]
    released = client.post(f"/executor-requests/{request_id}/release")
    assert released.status_code == 200

    blocked = client.post(f"/executor-requests/{request_id}/execute")
    assert blocked.status_code == 409
    read_back = client.get(f"/executor-requests/{request_id}")
    assert read_back.status_code == 200
    assert read_back.json()["status"] == "released"

    cancelled = client.post(f"/executor-requests/{request_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    cancelled_again = client.post(f"/executor-requests/{request_id}/cancel")
    assert cancelled_again.status_code == 200

    replay = client.post(f"/executor-requests/{request_id}/execute")
    assert replay.status_code == 409


def test_adapter_failure_is_persisted_redacted_and_not_replayed(
    executor_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = executor_client
    _, _, execution = setup_execution(client)
    calls = []

    class FailingAdapter:
        name = "failing"
        available = True

        def execute(self, command):
            calls.append(command.request_id)
            raise RuntimeError("adapter failed token=adapter-failure-secret")

    monkeypatch.setattr(executor_routes_module, "resolve_executor_adapter", lambda _: FailingAdapter())

    created = client.post(
        f"/agent-executions/{execution['id']}/executor-requests",
        json={
            "action": "create_commit",
            "adapter_type": "failing",
            "payload": {"message": "test: controlled executor"},
        },
    )
    assert created.status_code == 201
    request_id = created.json()["id"]
    assert client.post(f"/executor-requests/{request_id}/release").status_code == 200

    failed = client.post(f"/executor-requests/{request_id}/execute")
    assert failed.status_code == 200
    body = failed.json()
    assert body["status"] == "failed"
    assert "adapter-failure-secret" not in str(body).lower()
    assert "[redacted]" in (body["error"] or "").lower()
    assert len(calls) == 1

    replay = client.post(f"/executor-requests/{request_id}/execute")
    assert replay.status_code == 409
    assert len(calls) == 1
