from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.executor_routes as executor_routes_module
from app.database import Base, get_db
from app.isolated_executor import IsolatedLocalExecutorAdapter
from app.main import app
from tests.test_m8_4_controlled_executor import setup_execution


@pytest.fixture()
def provenance_client() -> Generator[TestClient, None, None]:
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


def make_adapter(root) -> IsolatedLocalExecutorAdapter:
    return IsolatedLocalExecutorAdapter(
        enabled=True,
        worktree_root=str(root),
        timeout_seconds=5,
        max_timeout_seconds=10,
        output_max_bytes=4096,
        env_allowlist="",
        worker_backend="subprocess-sandbox",
        worker_cpu_seconds=30,
        worker_memory_mb=512,
        worker_pids=64,
        worker_nofile=128,
        worker_file_size_mb=16,
    )


def create_released_request(client: TestClient, execution: dict, payload: dict) -> dict:
    created = client.post(
        f"/agent-executions/{execution['id']}/executor-requests",
        json={
            "action": "run_tests",
            "adapter_type": "isolated-local",
            "payload": payload,
        },
    )
    assert created.status_code == 201
    request = created.json()
    released = client.post(f"/executor-requests/{request['id']}/release")
    assert released.status_code == 200
    return released.json()


def test_successful_execution_persists_verified_provenance(
    provenance_client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = provenance_client
    _, _, execution = setup_execution(client)
    root = tmp_path / "root"
    tests = root / "repo" / "tests"
    tests.mkdir(parents=True)
    (tests / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    adapter = make_adapter(root)
    monkeypatch.setattr(executor_routes_module, "resolve_executor_adapter", lambda _: adapter)

    request = create_released_request(
        client,
        execution,
        {"worktree": "repo", "preset": "pytest", "test_target": "tests/test_ok.py"},
    )
    executed = client.post(f"/executor-requests/{request['id']}/execute")
    assert executed.status_code == 200
    assert executed.json()["status"] == "completed"

    attempts = client.get(f"/executor-requests/{request['id']}/worker-attempts")
    assert attempts.status_code == 200
    body = attempts.json()
    assert len(body) == 1
    attempt = body[0]
    assert attempt["attempt_number"] == 1
    assert attempt["status"] == "completed"
    assert attempt["worker_id"].startswith("worker-")
    assert len(attempt["job_digest"]) == 64
    assert len(attempt["result_digest"]) == 64
    assert attempt["provenance"]["job_digest"] == attempt["job_digest"]
    assert attempt["provenance"]["result_digest"] == attempt["result_digest"]
    assert "lease_token" not in attempt


def test_explicit_lease_returns_token_once_and_heartbeat_requires_it(
    provenance_client: TestClient,
) -> None:
    client = provenance_client
    _, _, execution = setup_execution(client)
    request = create_released_request(
        client,
        execution,
        {"worktree": "repo", "preset": "pytest", "test_target": "tests"},
    )

    leased = client.post(f"/executor-requests/{request['id']}/worker-attempts/lease")
    assert leased.status_code == 201
    lease = leased.json()
    token = lease["lease_token"]
    assert len(token) >= 20

    wrong = client.post(
        f"/worker-attempts/{lease['id']}/heartbeat",
        json={"lease_token": "x" * 24},
    )
    assert wrong.status_code == 403

    heartbeat = client.post(
        f"/worker-attempts/{lease['id']}/heartbeat",
        json={"lease_token": token},
    )
    assert heartbeat.status_code == 200
    assert heartbeat.json()["status"] == "leased"
    assert "lease_token" not in heartbeat.json()

    duplicate = client.post(f"/executor-requests/{request['id']}/worker-attempts/lease")
    assert duplicate.status_code == 409


def test_failed_request_can_retry_only_by_creating_new_attempt(
    provenance_client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = provenance_client
    _, _, execution = setup_execution(client)
    root = tmp_path / "root"
    test_file = root / "repo" / "tests" / "test_retry.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("def test_retry():\n    assert False\n", encoding="utf-8")
    adapter = make_adapter(root)
    monkeypatch.setattr(executor_routes_module, "resolve_executor_adapter", lambda _: adapter)

    request = create_released_request(
        client,
        execution,
        {"worktree": "repo", "preset": "pytest", "test_target": "tests/test_retry.py"},
    )
    first = client.post(f"/executor-requests/{request['id']}/execute")
    assert first.status_code == 200
    assert first.json()["status"] == "failed"

    direct_replay = client.post(f"/executor-requests/{request['id']}/execute")
    assert direct_replay.status_code == 409

    retry = client.post(f"/executor-requests/{request['id']}/retry")
    assert retry.status_code == 200
    assert retry.json()["status"] == "released"
    assert retry.json()["previous_attempts"] == 1

    test_file.write_text("def test_retry():\n    assert True\n", encoding="utf-8")
    second = client.post(f"/executor-requests/{request['id']}/execute")
    assert second.status_code == 200
    assert second.json()["status"] == "completed"

    attempts = client.get(f"/executor-requests/{request['id']}/worker-attempts").json()
    assert [item["attempt_number"] for item in attempts] == [1, 2]
    assert [item["status"] for item in attempts] == ["failed", "completed"]
    assert attempts[0]["id"] != attempts[1]["id"]
    assert attempts[0]["result_digest"] != attempts[1]["result_digest"]

    retry_after_success = client.post(f"/executor-requests/{request['id']}/retry")
    assert retry_after_success.status_code == 409


def test_worker_events_are_append_only_and_include_digests(
    provenance_client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = provenance_client
    _, _, execution = setup_execution(client)
    root = tmp_path / "root"
    tests = root / "repo" / "tests"
    tests.mkdir(parents=True)
    (tests / "test_ok.py").write_text("def test_ok():\n    assert 1 == 1\n", encoding="utf-8")
    monkeypatch.setattr(executor_routes_module, "resolve_executor_adapter", lambda _: make_adapter(root))
    request = create_released_request(
        client,
        execution,
        {"worktree": "repo", "preset": "pytest", "test_target": "tests/test_ok.py"},
    )
    assert client.post(f"/executor-requests/{request['id']}/execute").status_code == 200

    events = client.get(f"/agent-executions/{execution['id']}/events")
    assert events.status_code == 200
    worker_events = [item for item in events.json() if item["event_type"].startswith("worker_")]
    assert worker_events[-2]["event_type"] == "worker_attempt_started"
    assert worker_events[-1]["event_type"] == "worker_attempt_result"
    payload = worker_events[-1]["payload"]
    assert len(payload["job_digest"]) == 64
    assert len(payload["result_digest"]) == 64
