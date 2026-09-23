from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
import time
from typing import Any

from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.agent_models import AgentExecution, ExecutorRequest
from app.auth_models import AuthSession
from app.git_change_models import GitChangeApproval
from app.worker_models import WorkerAttempt

_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(authorization|cookie|set-cookie|password|passwd|token|secret|api[_-]?key)\b\s*[:=]\s*([^\s,;]+)"
)
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_URL_CREDENTIALS = re.compile(r"(https?://)([^/@\s:]+):([^/@\s]+)@", re.IGNORECASE)
_GITHUB_TOKEN = re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def sanitize_error(value: str | None, *, max_chars: int = 400) -> str | None:
    if not value:
        return None
    sanitized = _BEARER.sub("Bearer [REDACTED]", value)
    sanitized = _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=[REDACTED]", sanitized)
    sanitized = _URL_CREDENTIALS.sub(r"\1[REDACTED]@", sanitized)
    sanitized = _GITHUB_TOKEN.sub("[REDACTED_GITHUB_TOKEN]", sanitized)
    sanitized = _JWT.sub("[REDACTED_JWT]", sanitized)
    sanitized = " ".join(sanitized.split())
    if len(sanitized) > max_chars:
        sanitized = sanitized[: max_chars - 1] + "…"
    return sanitized


def _status_counts(db: Session, model: Any) -> dict[str, int]:
    rows = db.execute(select(model.status, func.count()).group_by(model.status)).all()
    return {str(status): int(count) for status, count in rows}


def build_operational_status(
    db: Session,
    *,
    app_version: str,
    environment: str,
    started_monotonic: float,
) -> tuple[dict[str, Any], int]:
    try:
        db.execute(text("SELECT 1"))
        database = "ok"
        http_status = 200
        status = "ready"
    except SQLAlchemyError:
        db.rollback()
        database = "unavailable"
        http_status = 503
        status = "degraded"

    return (
        {
            "status": status,
            "version": app_version,
            "environment": environment,
            "database": database,
            "uptime_seconds": max(0, int(time.monotonic() - started_monotonic)),
            "checked_at": utcnow().isoformat(),
        },
        http_status,
    )


def build_operational_summary(db: Session, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or utcnow()
    last_24h = now - timedelta(hours=24)

    active_sessions = db.scalar(
        select(func.count())
        .select_from(AuthSession)
        .where(AuthSession.revoked_at.is_(None), AuthSession.expires_at > now)
    ) or 0
    revoked_sessions = db.scalar(
        select(func.count()).select_from(AuthSession).where(AuthSession.revoked_at.is_not(None))
    ) or 0
    stale_worker_leases = db.scalar(
        select(func.count())
        .select_from(WorkerAttempt)
        .where(
            WorkerAttempt.lease_expires_at < now,
            WorkerAttempt.completed_at.is_(None),
            WorkerAttempt.failed_at.is_(None),
            WorkerAttempt.orphaned_at.is_(None),
        )
    ) or 0
    pending_git_approvals = db.scalar(
        select(func.count()).select_from(GitChangeApproval).where(GitChangeApproval.status == "pending")
    ) or 0
    failed_agent_executions_24h = db.scalar(
        select(func.count())
        .select_from(AgentExecution)
        .where(AgentExecution.failed_at.is_not(None), AgentExecution.failed_at >= last_24h)
    ) or 0
    failed_executor_requests_24h = db.scalar(
        select(func.count())
        .select_from(ExecutorRequest)
        .where(ExecutorRequest.failed_at.is_not(None), ExecutorRequest.failed_at >= last_24h)
    ) or 0
    failed_worker_attempts_24h = db.scalar(
        select(func.count())
        .select_from(WorkerAttempt)
        .where(
            or_(
                WorkerAttempt.failed_at >= last_24h,
                WorkerAttempt.orphaned_at >= last_24h,
            )
        )
    ) or 0

    return {
        "generated_at": now.isoformat(),
        "agent_executions": _status_counts(db, AgentExecution),
        "executor_requests": _status_counts(db, ExecutorRequest),
        "worker_attempts": _status_counts(db, WorkerAttempt),
        "git_change_approvals": _status_counts(db, GitChangeApproval),
        "auth_sessions": {
            "active": int(active_sessions),
            "revoked": int(revoked_sessions),
        },
        "signals": {
            "stale_worker_leases": int(stale_worker_leases),
            "pending_git_approvals": int(pending_git_approvals),
            "failed_agent_executions_24h": int(failed_agent_executions_24h),
            "failed_executor_requests_24h": int(failed_executor_requests_24h),
            "failed_worker_attempts_24h": int(failed_worker_attempts_24h),
        },
    }


def build_recent_failures(db: Session, *, limit: int = 20) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    executions = db.scalars(
        select(AgentExecution)
        .where(AgentExecution.failed_at.is_not(None))
        .order_by(AgentExecution.failed_at.desc())
        .limit(limit)
    ).all()
    for item in executions:
        candidates.append(
            {
                "kind": "agent_execution",
                "id": str(item.id),
                "project_id": str(item.project_id),
                "execution_id": str(item.id),
                "status": item.status,
                "occurred_at": _as_utc(item.failed_at),
                "error": sanitize_error(item.error_text),
            }
        )

    requests = db.scalars(
        select(ExecutorRequest)
        .where(ExecutorRequest.failed_at.is_not(None))
        .order_by(ExecutorRequest.failed_at.desc())
        .limit(limit)
    ).all()
    for item in requests:
        candidates.append(
            {
                "kind": "executor_request",
                "id": str(item.id),
                "project_id": str(item.project_id),
                "execution_id": str(item.execution_id),
                "status": item.status,
                "action": item.action,
                "adapter_type": item.adapter_type,
                "occurred_at": _as_utc(item.failed_at),
                "error": sanitize_error(item.error_text),
            }
        )

    attempts = db.scalars(
        select(WorkerAttempt)
        .where(or_(WorkerAttempt.failed_at.is_not(None), WorkerAttempt.orphaned_at.is_not(None)))
        .order_by(func.coalesce(WorkerAttempt.failed_at, WorkerAttempt.orphaned_at).desc())
        .limit(limit)
    ).all()
    for item in attempts:
        occurred_at = item.failed_at or item.orphaned_at or item.created_at
        candidates.append(
            {
                "kind": "worker_attempt",
                "id": str(item.id),
                "project_id": str(item.project_id),
                "execution_id": str(item.execution_id),
                "executor_request_id": str(item.executor_request_id),
                "status": item.status,
                "attempt_number": item.attempt_number,
                "backend": item.backend,
                "occurred_at": _as_utc(occurred_at),
                "error": sanitize_error(item.error_text),
            }
        )

    candidates.sort(key=lambda item: item["occurred_at"], reverse=True)
    selected = candidates[:limit]
    for item in selected:
        item["occurred_at"] = item["occurred_at"].isoformat()
    return selected
