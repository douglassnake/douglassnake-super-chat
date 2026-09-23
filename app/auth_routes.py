from pathlib import Path
import hmac

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import create_session, revoke_session, verify_password
from app.auth_models import AuthSession
from app.core.config import get_settings
from app.database import get_db

router = APIRouter()
settings = get_settings()
WEB_DIR = Path(__file__).resolve().parent.parent / "web"


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=160)
    password: str = Field(min_length=1, max_length=1024)


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


def _set_auth_cookies(response: Response, raw_token: str, raw_csrf: str) -> None:
    common = {
        "max_age": settings.auth_session_ttl_seconds,
        "path": "/",
        "secure": settings.auth_cookie_secure,
        "samesite": "strict",
    }
    response.set_cookie(
        settings.auth_cookie_name,
        raw_token,
        httponly=True,
        **common,
    )
    response.set_cookie(
        settings.auth_csrf_cookie_name,
        raw_csrf,
        httponly=False,
        **common,
    )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(settings.auth_cookie_name, path="/", secure=settings.auth_cookie_secure, samesite="strict")
    response.delete_cookie(settings.auth_csrf_cookie_name, path="/", secure=settings.auth_cookie_secure, samesite="strict")


@router.get("/login", include_in_schema=False)
def login_page() -> FileResponse:
    response = FileResponse(WEB_DIR / "login.html", media_type="text/html")
    _no_store(response)
    return response


@router.get("/auth/status")
def auth_status(request: Request, response: Response) -> dict:
    _no_store(response)
    principal = getattr(request.state, "auth_principal", None)
    session = getattr(request.state, "auth_session", None)
    return {
        "auth_enabled": settings.auth_enabled,
        "authenticated": bool(getattr(request.state, "authenticated", False)),
        "username": principal.get("username") if principal else None,
        "role": principal.get("role") if principal else None,
        "expires_at": session.expires_at if session is not None else None,
    }


@router.post("/auth/login")
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)) -> dict:
    _no_store(response)
    if not settings.auth_enabled:
        return {
            "auth_enabled": False,
            "authenticated": True,
            "username": settings.auth_username,
            "role": "admin",
        }

    username_ok = hmac.compare_digest(payload.username, settings.auth_username)
    password_ok = verify_password(payload.password, settings.auth_password_hash)
    if not username_ok or not password_ok:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")

    session, raw_token, raw_csrf = create_session(db, settings)
    _set_auth_cookies(response, raw_token, raw_csrf)
    return {
        "auth_enabled": True,
        "authenticated": True,
        "username": session.username,
        "role": session.role,
        "expires_at": session.expires_at,
    }


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> Response:
    session_state = getattr(request.state, "auth_session", None)
    if session_state is not None:
        session = db.get(AuthSession, session_state.id)
        if session is not None:
            revoke_session(db, session)
    _clear_auth_cookies(response)
    _no_store(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
