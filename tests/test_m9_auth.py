from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import auth_routes
from app.auth import AuthMiddleware, hash_password, validate_security_settings, verify_password
from app.auth_models import AuthSession
from app.core.config import Settings
from app.database import Base, get_db


@pytest.fixture()
def auth_client(monkeypatch) -> Generator[tuple[TestClient, sessionmaker, Settings], None, None]:
    password_hash = hash_password("correct horse battery staple", iterations=200_000)
    settings = Settings(
        _env_file=None,
        environment="development",
        auth_enabled=True,
        auth_username="admin",
        auth_password_hash=password_hash,
        auth_cookie_secure=False,
        auth_session_ttl_seconds=3600,
    )
    validate_security_settings(settings)

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

    test_app = FastAPI()
    monkeypatch.setattr(auth_routes, "settings", settings)
    test_app.include_router(auth_routes.router)

    @test_app.get("/private")
    def private() -> dict[str, bool]:
        return {"ok": True}

    @test_app.post("/mutate")
    def mutate() -> dict[str, bool]:
        return {"ok": True}

    test_app.dependency_overrides[get_db] = override_get_db
    test_app.add_middleware(AuthMiddleware, settings=settings, session_factory=TestingSessionLocal)

    with TestClient(test_app) as client:
        yield client, TestingSessionLocal, settings

    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_password_hash_roundtrip_and_serialization() -> None:
    encoded = hash_password("a strong local password", iterations=200_000)
    assert verify_password("a strong local password", encoded)
    assert not verify_password("wrong password", encoded)
    assert "a strong local password" not in encoded

    settings = Settings(_env_file=None, auth_password_hash=encoded)
    assert "auth_password_hash" not in settings.model_dump()
    assert encoded not in settings.model_dump_json()


def test_production_auth_is_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="AUTH_ENABLED"):
        validate_security_settings(Settings(_env_file=None, environment="production", auth_enabled=False))

    password_hash = hash_password("production password", iterations=200_000)
    with pytest.raises(RuntimeError, match="AUTH_COOKIE_SECURE"):
        validate_security_settings(
            Settings(
                _env_file=None,
                environment="production",
                auth_enabled=True,
                auth_password_hash=password_hash,
                auth_cookie_secure=False,
            )
        )

    with pytest.raises(RuntimeError, match="SECRET_BACKEND=files"):
        validate_security_settings(
            Settings(
                _env_file=None,
                environment="production",
                auth_enabled=True,
                auth_password_hash=password_hash,
                auth_cookie_secure=True,
            )
        )

    secret_dir = tmp_path / "secrets"
    secret_dir.mkdir(mode=0o700)
    password_file = secret_dir / "auth_password_hash"
    password_file.write_text(password_hash + "\n", encoding="utf-8")
    password_file.chmod(0o600)

    settings = Settings(
        _env_file=None,
        environment="production",
        auth_enabled=True,
        auth_password_hash="must-be-ignored",
        auth_cookie_secure=True,
        secret_backend="files",
        secret_dir=str(secret_dir),
    )
    validate_security_settings(settings)
    assert settings.auth_password_hash == password_hash


def test_authentication_session_csrf_and_logout(auth_client) -> None:
    client, SessionLocal, settings = auth_client

    protected = client.get("/private", follow_redirects=False)
    assert protected.status_code == 401

    app_redirect = client.get("/app/", follow_redirects=False)
    assert app_redirect.status_code == 303
    assert app_redirect.headers["location"] == "/login?next=/app/"

    wrong = client.post("/auth/login", json={"username": "admin", "password": "wrong"})
    assert wrong.status_code == 401

    login = client.post(
        "/auth/login",
        json={"username": "admin", "password": "correct horse battery staple"},
    )
    assert login.status_code == 200
    assert login.json()["authenticated"] is True
    raw_session = client.cookies.get(settings.auth_cookie_name)
    raw_csrf = client.cookies.get(settings.auth_csrf_cookie_name)
    assert raw_session
    assert raw_csrf

    status_response = client.get("/auth/status")
    assert status_response.status_code == 200
    assert status_response.json()["csrf_cookie_name"] == settings.auth_csrf_cookie_name

    with SessionLocal() as db:
        rows = list(db.scalars(select(AuthSession)))
        assert len(rows) == 1
        stored = rows[0]
        assert stored.token_hash != raw_session
        assert raw_session not in stored.token_hash
        assert stored.csrf_token_hash != raw_csrf
        assert raw_csrf not in stored.csrf_token_hash

    assert client.get("/private").status_code == 200

    missing_header = client.post("/mutate")
    assert missing_header.status_code == 403

    wrong_header = client.post("/mutate", headers={"X-CSRF-Token": "wrong"})
    assert wrong_header.status_code == 403

    valid_mutation = client.post("/mutate", headers={"X-CSRF-Token": raw_csrf})
    assert valid_mutation.status_code == 200

    client.cookies.delete(settings.auth_csrf_cookie_name)
    missing_cookie = client.post("/mutate", headers={"X-CSRF-Token": raw_csrf})
    assert missing_cookie.status_code == 403

    client.cookies.set(settings.auth_csrf_cookie_name, raw_csrf, path="/")
    cross_site = client.post(
        "/mutate",
        headers={"X-CSRF-Token": raw_csrf, "Sec-Fetch-Site": "cross-site"},
    )
    assert cross_site.status_code == 403

    logout = client.post("/auth/logout", headers={"X-CSRF-Token": raw_csrf})
    assert logout.status_code == 204
    assert client.get("/private").status_code == 401

    with SessionLocal() as db:
        stored = db.scalar(select(AuthSession))
        assert stored is not None
        assert stored.revoked_at is not None
