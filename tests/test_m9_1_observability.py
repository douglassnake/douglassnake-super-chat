from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
import json
import re
import time
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.agent_models import AgentExecution, ExecutorRequest
from app.auth import AuthMiddleware, hash_password
from app.auth_models import AuthSession
from app.core.config import Settings
from app.database import Base, get_db
from app.git_change_models import GitChangeApproval
from app.observability import ObservabilityMiddleware, REQUEST_ID_PATTERN
from app.ops import build_operational_status, build_operational_summary, build_recent_failures, sanitize_error
from app.ops_routes import router as ops_router
from app.worker_models import WorkerAttempt


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    Base.metadata.create_all(bind=engine)
    return engine, SessionLocal


def test_request_id_and_structured_log_do_not_leak_request_secrets() -> None:
    events: list[dict] = []
    test_app = FastAPI()
    test_app.add_middleware(ObservabilityMiddleware, emit=events.append)

    @test_app.post("/echo")
    async def echo(request: Request) -> dict[str, bool]:
        request.state.auth_principal = {"username": "admin", "role": "admin"}
        await request.body()
        return {"ok": True}

    with TestClient(test_app) as client:
        response = client.post(
            "/echo?token=QUERY_SECRET",
            json={"password": "BODY_SECRET"},
            headers={
                "X-Request-ID": "request-12345678",
                "Authorization": "Bearer HEADER_SECRET",
                "Cookie": "session=COOKIE_SECRET",
            },
        )
        assert response.status_code == 200
        assert response.headers["x-request-id"] == "request-12345678"

        event = events[-1]
        assert event["path"] == "/echo"
        assert event["username"] == "admin"
        rendered = json.dumps(event)
        assert "QUERY_SECRET" not in rendered
        assert "BODY_SECRET" not in rendered
        assert "HEADER_SECRET" not in rendered
        assert "COOKIE_SECRET" not in rendered
        assert "authorization" not in rendered.lower()
        assert "cookie" not in rendered.lower()

        invalid = client.post("/echo", headers={"X-Request-ID": "bad id with spaces"})
        replacement = invalid.headers["x-request-id"]
        assert replacement != "bad id with spaces"
        assert REQUEST_ID_PATTERN.fullmatch(replacement)


def test_error_sanitization_redacts_common_secret_shapes() -> None:
    github_token = "ghp_" + "A" * 40
    jwt = "eyJabc.DEFghi.JKLmno"
    raw = (
        "Authorization: Bearer TOPSECRET password=hunter2 "
        "https://user:pass@example.test/path "
        f"token={github_token} {jwt}"
    )
    sanitized = sanitize_error(raw)
    assert sanitized is not None
    assert "TOPSECRET" not in sanitized
    assert "hunter2" not in sanitized
    assert "user:pass" not in sanitized
    assert github_token not in sanitized
    assert jwt not in sanitized
    assert "REDACTED" in sanitized


def test_operational_summary_and_recent_failures_use_persisted_state() -> None:
    engine, SessionLocal = _session_factory()
    now = datetime(2026, 9, 23, 19, 30, tzinfo=timezone.utc)
    project_id = uuid4()
    handoff_id = uuid4()
    pack_id = uuid4()
    execution_id = uuid4()
    request_id = uuid4()

    with SessionLocal() as db:
        db.add(
            AgentExecution(
                id=execution_id,
                handoff_id=handoff_id,
                pack_id=pack_id,
                project_id=project_id,
                status="failed",
                failed_at=now - timedelta(minutes=40),
                error_text="Authorization: Bearer AGENT_SECRET failure",
            )
        )
        db.add(
            ExecutorRequest(
                id=request_id,
                execution_id=execution_id,
                handoff_id=handoff_id,
                project_id=project_id,
                action="run_tests",
                adapter_type="isolated-local",
                status="failed",
                fingerprint="f" * 64,
                failed_at=now - timedelta(minutes=30),
                error_text="password=EXECUTOR_SECRET test failed",
            )
        )
        db.add_all(
            [
                WorkerAttempt(
                    executor_request_id=request_id,
                    execution_id=execution_id,
                    project_id=project_id,
                    attempt_number=1,
                    status="leased",
                    lease_token_hash="a" * 64,
                    lease_expires_at=now - timedelta(minutes=5),
                    heartbeat_at=now - timedelta(minutes=10),
                ),
                WorkerAttempt(
                    executor_request_id=request_id,
                    execution_id=execution_id,
                    project_id=project_id,
                    attempt_number=2,
                    status="failed",
                    lease_token_hash="b" * 64,
                    lease_expires_at=now + timedelta(minutes=5),
                    heartbeat_at=now - timedelta(minutes=2),
                    failed_at=now - timedelta(minutes=20),
                    error_text="token=WORKER_SECRET worker failed",
                ),
            ]
        )
        db.add(
            GitChangeApproval(
                executor_request_id=request_id,
                execution_id=execution_id,
                project_id=project_id,
                status="pending",
                patch_digest="c" * 64,
                proposal_fingerprint="d" * 64,
            )
        )
        db.add_all(
            [
                AuthSession(
                    token_hash="1" * 64,
                    csrf_token_hash="2" * 64,
                    username="admin",
                    role="admin",
                    created_at=now - timedelta(hours=1),
                    last_seen_at=now - timedelta(minutes=1),
                    expires_at=now + timedelta(hours=1),
                ),
                AuthSession(
                    token_hash="3" * 64,
                    csrf_token_hash="4" * 64,
                    username="admin",
                    role="admin",
                    created_at=now - timedelta(hours=2),
                    last_seen_at=now - timedelta(hours=1),
                    expires_at=now + timedelta(hours=1),
                    revoked_at=now - timedelta(minutes=5),
                ),
            ]
        )
        db.commit()

        summary = build_operational_summary(db, now=now)
        assert summary["agent_executions"] == {"failed": 1}
        assert summary["executor_requests"] == {"failed": 1}
        assert summary["worker_attempts"] == {"failed": 1, "leased": 1}
        assert summary["git_change_approvals"] == {"pending": 1}
        assert summary["auth_sessions"] == {"active": 1, "revoked": 1}
        assert summary["signals"]["stale_worker_leases"] == 1
        assert summary["signals"]["pending_git_approvals"] == 1
        assert summary["signals"]["failed_agent_executions_24h"] == 1
        assert summary["signals"]["failed_executor_requests_24h"] == 1
        assert summary["signals"]["failed_worker_attempts_24h"] == 1

        failures = build_recent_failures(db, limit=10)
        assert {item["kind"] for item in failures} == {
            "agent_execution",
            "executor_request",
            "worker_attempt",
        }
        rendered = json.dumps(failures)
        assert "AGENT_SECRET" not in rendered
        assert "EXECUTOR_SECRET" not in rendered
        assert "WORKER_SECRET" not in rendered

        status, status_code = build_operational_status(
            db,
            app_version="0.9.1",
            environment="test",
            started_monotonic=time.monotonic(),
        )
        assert status_code == 200
        assert status["status"] == "ready"
        assert status["database"] == "ok"

    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_ops_endpoints_are_protected_when_auth_is_enabled() -> None:
    engine, SessionLocal = _session_factory()
    settings = Settings(
        _env_file=None,
        auth_enabled=True,
        auth_username="admin",
        auth_password_hash=hash_password("observability password", iterations=200_000),
        auth_cookie_secure=False,
    )
    test_app = FastAPI(version="0.9.1")
    test_app.state.settings = settings
    test_app.state.started_monotonic = time.monotonic()
    test_app.include_router(ops_router)

    def override_get_db() -> Generator[Session, None, None]:
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    test_app.dependency_overrides[get_db] = override_get_db
    test_app.add_middleware(AuthMiddleware, settings=settings, session_factory=SessionLocal)
    test_app.add_middleware(ObservabilityMiddleware, emit=lambda event: None)

    with TestClient(test_app) as client:
        assert client.get("/ops/status").status_code == 401
        assert client.get("/ops/summary").status_code == 401
        assert client.get("/ops/failures").status_code == 401

    Base.metadata.drop_all(bind=engine)
    engine.dispose()
