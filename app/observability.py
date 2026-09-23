from __future__ import annotations

import json
import logging
import re
import sys
import time
from typing import Callable
from uuid import uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")


def normalize_request_id(value: str | None) -> str:
    if value and REQUEST_ID_PATTERN.fullmatch(value):
        return value
    return uuid4().hex


def _build_logger() -> logging.Logger:
    logger = logging.getLogger("superchat.http")
    logger.setLevel(logging.INFO)
    if not getattr(logger, "_superchat_configured", False):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.propagate = False
        setattr(logger, "_superchat_configured", True)
    return logger


logger = _build_logger()


def emit_observability_event(event: dict) -> None:
    logger.info(json.dumps(event, ensure_ascii=False, separators=(",", ":"), default=str))


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Emit one sanitized structured event for each HTTP request.

    The event intentionally excludes query strings, bodies, cookies, headers,
    tokens and exception messages. Only stable operational metadata is logged.
    """

    def __init__(
        self,
        app,
        *,
        emit: Callable[[dict], None] = emit_observability_event,
    ) -> None:
        super().__init__(app)
        self.emit = emit

    async def dispatch(self, request: Request, call_next):
        request_id = normalize_request_id(request.headers.get("x-request-id"))
        request.state.request_id = request_id
        started = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception as exc:
            principal = getattr(request.state, "auth_principal", None)
            self.emit(
                {
                    "event": "http.request",
                    "request_id": request_id,
                    "method": request.method.upper(),
                    "path": request.url.path,
                    "status": 500,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                    "username": principal.get("username") if principal else None,
                    "exception_type": type(exc).__name__,
                }
            )
            raise

        principal = getattr(request.state, "auth_principal", None)
        self.emit(
            {
                "event": "http.request",
                "request_id": request_id,
                "method": request.method.upper(),
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                "username": principal.get("username") if principal else None,
            }
        )
        response.headers["X-Request-ID"] = request_id
        return response
