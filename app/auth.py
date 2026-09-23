from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets
from typing import Callable

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware

from app.auth_models import AuthSession
from app.core.config import Settings

PASSWORD_SCHEME = "pbkdf2_sha256"
DEFAULT_PASSWORD_ITERATIONS = 600_000
MIN_PASSWORD_ITERATIONS = 200_000
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
PUBLIC_PATHS = {"/health", "/login", "/auth/login", "/auth/status"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def hash_password(password: str, *, iterations: int = DEFAULT_PASSWORD_ITERATIONS) -> str:
    if not password or len(password) > 1024:
        raise ValueError("password must contain between 1 and 1024 characters")
    if iterations < MIN_PASSWORD_ITERATIONS:
        raise ValueError(f"iterations must be >= {MIN_PASSWORD_ITERATIONS}")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{PASSWORD_SCHEME}${iterations}${_b64encode(salt)}${_b64encode(digest)}"


def _parse_password_hash(encoded: str | None) -> tuple[int, bytes, bytes] | None:
    if not encoded:
        return None
    try:
        scheme, iterations_raw, salt_raw, digest_raw = encoded.split("$", 3)
        iterations = int(iterations_raw)
        salt = _b64decode(salt_raw)
        digest = _b64decode(digest_raw)
    except (ValueError, TypeError, base64.binascii.Error):
        return None
    if scheme != PASSWORD_SCHEME or iterations < MIN_PASSWORD_ITERATIONS:
        return None
    if len(salt) < 16 or len(digest) != hashlib.sha256().digest_size:
        return None
    return iterations, salt, digest


def verify_password(password: str, encoded: str | None) -> bool:
    parsed = _parse_password_hash(encoded)
    if parsed is None or len(password) > 1024:
        return False
    iterations, salt, expected = parsed
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def validate_security_settings(settings: Settings) -> None:
    if not 300 <= settings.auth_session_ttl_seconds <= 604_800:
        raise RuntimeError("AUTH_SESSION_TTL_SECONDS must be between 300 and 604800")
    if not settings.auth_cookie_name.strip() or not settings.auth_csrf_cookie_name.strip():
        raise RuntimeError("authentication cookie names must not be empty")
    if settings.auth_enabled:
        if not settings.auth_username.strip():
            raise RuntimeError("AUTH_USERNAME must not be empty when authentication is enabled")
        if _parse_password_hash(settings.auth_password_hash) is None:
            raise RuntimeError("AUTH_PASSWORD_HASH must be a valid PBKDF2-SHA256 hash")
    if settings.environment.lower() == "production":
        if not settings.auth_enabled:
            raise RuntimeError("AUTH_ENABLED=true is required in production")
        if not settings.auth_cookie_secure:
            raise RuntimeError("AUTH_COOKIE_SECURE=true is required in production")


def create_session(db: Session, settings: Settings) -> tuple[AuthSession, str, str]:
    now = utcnow()
    raw_token = secrets.token_urlsafe(32)
    raw_csrf = secrets.token_urlsafe(32)
    session = AuthSession(
        token_hash=token_hash(raw_token),
        csrf_token_hash=token_hash(raw_csrf),
        username=settings.auth_username,
        role="admin",
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(seconds=settings.auth_session_ttl_seconds),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session, raw_token, raw_csrf


def resolve_session(db: Session, raw_token: str | None) -> AuthSession | None:
    if not raw_token:
        return None
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash(raw_token)))
    if session is None or session.revoked_at is not None:
        return None
    now = utcnow()
    if _as_utc(session.expires_at) <= now:
        return None
    if now - _as_utc(session.last_seen_at) >= timedelta(minutes=5):
        session.last_seen_at = now
        db.commit()
    return session


def revoke_session(db: Session, session: AuthSession) -> None:
    if session.revoked_at is None:
        session.revoked_at = utcnow()
        db.commit()


def csrf_valid(request: Request, session: AuthSession, settings: Settings) -> bool:
    if request.headers.get("sec-fetch-site", "").lower() == "cross-site":
        return False
    raw_csrf = request.cookies.get(settings.auth_csrf_cookie_name)
    supplied = request.headers.get("x-csrf-token")
    if not raw_csrf or not supplied:
        return False
    if not hmac.compare_digest(token_hash(raw_csrf), session.csrf_token_hash):
        return False
    return hmac.compare_digest(supplied, raw_csrf)


def _wants_html(request: Request) -> bool:
    if request.url.path == "/" or request.url.path.startswith("/app"):
        return True
    return "text/html" in request.headers.get("accept", "")


class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        *,
        settings: Settings,
        session_factory: Callable[[], Session],
    ) -> None:
        super().__init__(app)
        self.settings = settings
        self.session_factory = session_factory

    async def dispatch(self, request: Request, call_next):
        request.state.auth_session = None
        request.state.authenticated = not self.settings.auth_enabled
        request.state.auth_principal = (
            {"username": self.settings.auth_username, "role": "admin"}
            if not self.settings.auth_enabled
            else None
        )

        if not self.settings.auth_enabled:
            return await call_next(request)

        raw_token = request.cookies.get(self.settings.auth_cookie_name)
        db = self.session_factory()
        try:
            session = resolve_session(db, raw_token)
            if session is not None:
                request.state.auth_session = session
                request.state.authenticated = True
                request.state.auth_principal = {"username": session.username, "role": session.role}

            if request.url.path in PUBLIC_PATHS:
                return await call_next(request)

            if session is None:
                if _wants_html(request):
                    target = request.url.path
                    return RedirectResponse(url=f"/login?next={target}", status_code=303)
                return JSONResponse(status_code=401, content={"detail": "authentication required"})

            if request.method.upper() in UNSAFE_METHODS and not csrf_valid(request, session, self.settings):
                return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})

            return await call_next(request)
        finally:
            db.close()
