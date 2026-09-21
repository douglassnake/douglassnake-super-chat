from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent_execution import append_execution_event
from app.agent_models import AgentExecution, ExecutorRequest
from app.core.config import get_settings
from app.database import get_db
from app.models import utcnow
from app.worker_attempts import (
    ACTIVE_ATTEMPT_STATES,
    attempt_payload,
    create_attempt,
    heartbeat_attempt,
    reconcile_expired_attempts,
    verify_lease_token,
)
from app.worker_models import WorkerAttempt


router = APIRouter(tags=["worker-attempts"])


class HeartbeatPayload(BaseModel):
    lease_token: str = Field(min_length=20, max_length=256)


def _request(db: Session, request_id: UUID) -> ExecutorRequest:
    request = db.get(ExecutorRequest, request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="Executor request not found")
    return request


def _attempt(db: Session, attempt_id: UUID) -> WorkerAttempt:
    attempt = db.get(WorkerAttempt, attempt_id)
    if attempt is None:
        raise HTTPException(status_code=404, detail="Worker attempt not found")
    return attempt


@router.get("/executor-requests/{request_id}/worker-attempts")
def list_attempts(request_id: UUID, db: Session = Depends(get_db)) -> list[dict]:
    _request(db, request_id)
    stmt = (
        select(WorkerAttempt)
        .where(WorkerAttempt.executor_request_id == request_id)
        .order_by(WorkerAttempt.attempt_number.asc())
    )
    return [attempt_payload(item) for item in db.scalars(stmt).all()]


@router.get("/worker-attempts/{attempt_id}")
def read_attempt(attempt_id: UUID, db: Session = Depends(get_db)) -> dict:
    return attempt_payload(_attempt(db, attempt_id))


@router.post(
    "/executor-requests/{request_id}/worker-attempts/lease",
    status_code=status.HTTP_201_CREATED,
)
def lease_attempt(request_id: UUID, db: Session = Depends(get_db)) -> dict:
    request = _request(db, request_id)
    if request.status != "released":
        raise HTTPException(status_code=409, detail="Executor request must be released before leasing a worker attempt")
    if request.adapter_type != "isolated-local":
        raise HTTPException(status_code=409, detail="Worker attempts are only used by isolated-local requests")
    settings = get_settings()
    try:
        attempt, lease_token = create_attempt(
            db,
            request,
            lease_seconds=settings.executor_worker_lease_seconds,
            max_attempts=settings.executor_worker_max_attempts,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    execution = db.get(AgentExecution, request.execution_id)
    if execution is not None:
        append_execution_event(
            db,
            execution,
            event_type="worker_lease",
            message=f"Worker attempt leased: #{attempt.attempt_number}",
            payload={"attempt_id": str(attempt.id), "attempt_number": attempt.attempt_number},
        )
    db.commit()
    db.refresh(attempt)
    response = attempt_payload(attempt)
    response["lease_token"] = lease_token  # returned once; only the hash is persisted
    return response


@router.post("/worker-attempts/{attempt_id}/heartbeat")
def heartbeat(attempt_id: UUID, payload: HeartbeatPayload, db: Session = Depends(get_db)) -> dict:
    attempt = _attempt(db, attempt_id)
    if not verify_lease_token(attempt, payload.lease_token):
        raise HTTPException(status_code=403, detail="Invalid worker lease token")
    try:
        heartbeat_attempt(attempt, lease_seconds=get_settings().executor_worker_lease_seconds)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    db.refresh(attempt)
    return attempt_payload(attempt)


@router.post("/worker-attempts/reconcile")
def reconcile(db: Session = Depends(get_db)) -> dict:
    attempts = reconcile_expired_attempts(db)
    request_ids: list[str] = []
    for attempt in attempts:
        request = db.get(ExecutorRequest, attempt.executor_request_id)
        if request is not None and request.status == "running":
            request.status = "failed"
            request.error_text = "Worker attempt became orphaned after lease expiration"
            request.failed_at = utcnow()
            request_ids.append(str(request.id))
        execution = db.get(AgentExecution, attempt.execution_id)
        if execution is not None:
            append_execution_event(
                db,
                execution,
                event_type="worker_orphaned",
                message=f"Worker attempt #{attempt.attempt_number} reconciled as {attempt.status}",
                payload={"attempt_id": str(attempt.id), "status": attempt.status},
            )
    db.commit()
    return {
        "reconciled": len(attempts),
        "attempt_ids": [str(item.id) for item in attempts],
        "failed_request_ids": request_ids,
    }


@router.post("/executor-requests/{request_id}/retry")
def retry_request(request_id: UUID, db: Session = Depends(get_db)) -> dict:
    request = _request(db, request_id)
    if request.adapter_type != "isolated-local":
        raise HTTPException(status_code=409, detail="Controlled retry is only enabled for isolated-local requests")
    if request.status != "failed":
        raise HTTPException(status_code=409, detail=f"Executor request is {request.status}; only failed requests can retry")
    active = db.scalar(
        select(WorkerAttempt).where(
            WorkerAttempt.executor_request_id == request.id,
            WorkerAttempt.status.in_(ACTIVE_ATTEMPT_STATES),
        )
    )
    if active is not None:
        raise HTTPException(status_code=409, detail="An active worker attempt still exists")
    attempts = list(
        db.scalars(
            select(WorkerAttempt)
            .where(WorkerAttempt.executor_request_id == request.id)
            .order_by(WorkerAttempt.attempt_number.asc())
        ).all()
    )
    if len(attempts) >= max(1, get_settings().executor_worker_max_attempts):
        raise HTTPException(status_code=409, detail="Maximum worker attempts reached for this executor request")
    if not attempts:
        raise HTTPException(status_code=409, detail="Request has no worker attempt history to retry")

    request.status = "released"
    request.result_json = {}
    request.error_text = None
    request.started_at = None
    request.completed_at = None
    request.failed_at = None
    execution = db.get(AgentExecution, request.execution_id)
    if execution is not None:
        append_execution_event(
            db,
            execution,
            event_type="worker_retry_released",
            message=f"Controlled retry released after attempt #{attempts[-1].attempt_number}",
            payload={"request_id": str(request.id), "previous_attempt_id": str(attempts[-1].id)},
        )
    db.commit()
    return {
        "request_id": request.id,
        "status": request.status,
        "previous_attempts": len(attempts),
        "remaining_attempts": max(0, get_settings().executor_worker_max_attempts - len(attempts)),
    }
