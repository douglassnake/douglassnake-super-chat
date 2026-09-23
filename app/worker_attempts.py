from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agent_handoff import sanitize_value
from app.agent_models import ExecutorRequest
from app.core.config import get_settings
from app.models import utcnow
from app.worker_models import WorkerAttempt


ACTIVE_ATTEMPT_STATES = {"leased", "running"}
TERMINAL_ATTEMPT_STATES = {"completed", "failed", "orphaned", "expired"}


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _effective_lease_seconds(requested_seconds: int) -> int:
    # A tentativa síncrona não pode ser reconciliada como órfã enquanto um
    # `run_tests` ainda está dentro do maior timeout permitido. A margem cobre
    # startup/teardown do processo separado do worker.
    settings = get_settings()
    timeout_floor = int(settings.executor_max_timeout_seconds) + 30
    return max(10, int(requested_seconds), timeout_floor)


def verify_lease_token(attempt: WorkerAttempt, token: str) -> bool:
    return secrets.compare_digest(attempt.lease_token_hash, _token_hash(token))


def attempt_payload(attempt: WorkerAttempt) -> dict[str, Any]:
    return {
        "id": attempt.id,
        "executor_request_id": attempt.executor_request_id,
        "execution_id": attempt.execution_id,
        "project_id": attempt.project_id,
        "attempt_number": attempt.attempt_number,
        "status": attempt.status,
        "worker_id": attempt.worker_id,
        "backend": attempt.backend,
        "job_digest": attempt.job_digest,
        "result_digest": attempt.result_digest,
        "lease_expires_at": attempt.lease_expires_at,
        "heartbeat_at": attempt.heartbeat_at,
        "provenance": attempt.provenance_json or {},
        "result": attempt.result_json or {},
        "error": attempt.error_text,
        "created_at": attempt.created_at,
        "started_at": attempt.started_at,
        "completed_at": attempt.completed_at,
        "failed_at": attempt.failed_at,
        "orphaned_at": attempt.orphaned_at,
    }


def create_attempt(
    db: Session,
    request: ExecutorRequest,
    *,
    lease_seconds: int,
    max_attempts: int,
) -> tuple[WorkerAttempt, str]:
    active = db.scalar(
        select(WorkerAttempt).where(
            WorkerAttempt.executor_request_id == request.id,
            WorkerAttempt.status.in_(ACTIVE_ATTEMPT_STATES),
        )
    )
    if active is not None:
        raise ValueError(f"Worker attempt {active.id} is already active")

    count = int(
        db.scalar(
            select(func.count(WorkerAttempt.id)).where(WorkerAttempt.executor_request_id == request.id)
        )
        or 0
    )
    if count >= max(1, int(max_attempts)):
        raise ValueError("Maximum worker attempts reached for this executor request")

    now = utcnow()
    token = secrets.token_urlsafe(32)
    effective_lease = _effective_lease_seconds(lease_seconds)
    attempt = WorkerAttempt(
        executor_request_id=request.id,
        execution_id=request.execution_id,
        project_id=request.project_id,
        attempt_number=count + 1,
        status="leased",
        lease_token_hash=_token_hash(token),
        lease_expires_at=now + timedelta(seconds=effective_lease),
        heartbeat_at=now,
        provenance_json={},
        result_json={},
    )
    db.add(attempt)
    db.flush()
    return attempt, token


def heartbeat_attempt(attempt: WorkerAttempt, *, lease_seconds: int) -> None:
    if attempt.status not in ACTIVE_ATTEMPT_STATES:
        raise ValueError(f"Worker attempt is {attempt.status} and cannot heartbeat")
    now = utcnow()
    if _aware(attempt.lease_expires_at) < now:
        raise ValueError("Worker attempt lease has expired")
    attempt.heartbeat_at = now
    attempt.lease_expires_at = now + timedelta(seconds=_effective_lease_seconds(lease_seconds))


def mark_attempt_running(attempt: WorkerAttempt) -> None:
    if attempt.status != "leased":
        raise ValueError(f"Worker attempt is {attempt.status} and cannot start")
    attempt.status = "running"
    attempt.started_at = utcnow()


def finalize_attempt(
    attempt: WorkerAttempt,
    *,
    ok: bool,
    result: dict[str, Any],
    error: str | None,
) -> None:
    if attempt.status not in ACTIVE_ATTEMPT_STATES:
        raise ValueError(f"Worker attempt is {attempt.status} and cannot finish")
    clean_result = sanitize_value(result or {})
    provenance = dict(clean_result.get("provenance") or {}) if isinstance(clean_result, dict) else {}
    attempt.worker_id = provenance.get("worker_id")
    attempt.backend = provenance.get("backend") or (clean_result.get("backend") if isinstance(clean_result, dict) else None)
    attempt.job_digest = provenance.get("job_digest")
    attempt.result_digest = provenance.get("result_digest")
    attempt.provenance_json = sanitize_value(provenance)
    attempt.result_json = clean_result if isinstance(clean_result, dict) else {}
    attempt.error_text = error
    now = utcnow()
    if ok:
        attempt.status = "completed"
        attempt.completed_at = now
    else:
        attempt.status = "failed"
        attempt.failed_at = now


def reconcile_expired_attempts(db: Session) -> list[WorkerAttempt]:
    now = utcnow()
    attempts = list(
        db.scalars(
            select(WorkerAttempt).where(
                WorkerAttempt.status.in_(ACTIVE_ATTEMPT_STATES),
                WorkerAttempt.lease_expires_at < now,
            )
        ).all()
    )
    for attempt in attempts:
        attempt.status = "orphaned" if attempt.started_at is not None else "expired"
        attempt.orphaned_at = now
        attempt.error_text = "Worker lease expired before a terminal result was reconciled"
    return attempts
