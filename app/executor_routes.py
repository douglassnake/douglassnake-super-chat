from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agent_execution import append_execution_event
from app.agent_handoff import sanitize_value
from app.agent_models import AgentExecution, AgentHandoff, ExecutorRequest
from app.agent_task_pack import redact_secrets
from app.core.config import get_settings
from app.database import get_db
from app.executor_control import (
    ExecutorUnavailable,
    TERMINAL_REQUEST_STATES,
    executor_command,
    executor_request_fingerprint,
    executor_request_payload,
    resolve_executor_adapter,
    sanitize_executor_error,
    sanitize_executor_payload,
    validate_executor_action,
)
from app.git_apply_resolver import (
    GitApplyResolutionError,
    resolve_apply_git_change_payload,
)
from app.git_commit_resolver import (
    GitCommitResolutionError,
    resolve_create_commit_payload,
)
from app.models import utcnow
from app.worker_attempts import create_attempt, finalize_attempt, mark_attempt_running
from app.worker_models import WorkerAttempt


router = APIRouter(tags=["controlled-executor"])


class ExecutorRequestCreate(BaseModel):
    action: str = Field(min_length=1, max_length=60, pattern=r"^[A-Za-z0-9._-]+$")
    adapter_type: str = Field(default="manual", min_length=1, max_length=60, pattern=r"^[A-Za-z0-9._-]+$")
    payload: dict = Field(default_factory=dict)
    notes: str | None = Field(default=None, max_length=6000)


def get_execution(db: Session, execution_id: UUID) -> AgentExecution:
    execution = db.get(AgentExecution, execution_id)
    if execution is None:
        raise HTTPException(status_code=404, detail="Agent execution not found")
    return execution


def get_handoff(db: Session, handoff_id: UUID) -> AgentHandoff:
    handoff = db.get(AgentHandoff, handoff_id)
    if handoff is None:
        raise HTTPException(status_code=404, detail="Agent handoff not found")
    return handoff


def get_executor_request(db: Session, request_id: UUID) -> ExecutorRequest:
    request = db.get(ExecutorRequest, request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="Executor request not found")
    return request


def bounded_payload(payload: dict, *, field_name: str) -> dict:
    try:
        cleaned = sanitize_executor_payload(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    rendered = json.dumps(cleaned, ensure_ascii=False, sort_keys=True, default=str)
    if len(rendered) > 100_000:
        raise HTTPException(status_code=422, detail=f"{field_name} is too large")
    return cleaned


def bounded_result(payload: dict) -> dict:
    cleaned = sanitize_value(payload)
    rendered = json.dumps(cleaned, ensure_ascii=False, sort_keys=True, default=str)
    if len(rendered) > 100_000:
        raise HTTPException(status_code=422, detail="Executor result is too large")
    return cleaned


def validate_authorization(
    execution: AgentExecution,
    handoff: AgentHandoff,
    action: str,
) -> None:
    if execution.status != "running":
        raise HTTPException(
            status_code=409,
            detail=f"Execution is {execution.status}; executor requests require a running execution",
        )
    if handoff.status != "released":
        raise HTTPException(
            status_code=409,
            detail=f"Handoff is {handoff.status}; executor requests require a released handoff",
        )
    if execution.handoff_id != handoff.id:
        raise HTTPException(status_code=409, detail="Execution does not belong to this handoff")
    try:
        validate_executor_action(action)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if action not in set(handoff.allowed_actions_json or []):
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Executor action is not authorized by the handoff",
                "action": action,
                "allowed_actions": handoff.allowed_actions_json or [],
            },
        )


@router.post(
    "/agent-executions/{execution_id}/executor-requests",
    status_code=status.HTTP_201_CREATED,
)
def create_executor_request(
    execution_id: UUID,
    payload: ExecutorRequestCreate,
    db: Session = Depends(get_db),
) -> dict:
    execution = get_execution(db, execution_id)
    handoff = get_handoff(db, execution.handoff_id)
    validate_authorization(execution, handoff, payload.action)

    if payload.action == "apply_git_change":
        if payload.adapter_type != "isolated-local":
            raise HTTPException(
                status_code=422,
                detail="apply_git_change requires the isolated-local adapter",
            )
        try:
            resolved = resolve_apply_git_change_payload(db, execution, payload.payload)
        except GitApplyResolutionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        cleaned_payload = bounded_payload(resolved, field_name="Resolved Git apply payload")
    elif payload.action == "create_commit":
        if payload.adapter_type != "isolated-local":
            raise HTTPException(
                status_code=422,
                detail="create_commit requires the isolated-local adapter",
            )
        try:
            resolved = resolve_create_commit_payload(db, execution, payload.payload)
        except GitCommitResolutionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        cleaned_payload = bounded_payload(resolved, field_name="Resolved Git commit payload")
    else:
        cleaned_payload = bounded_payload(payload.payload, field_name="Executor payload")

    fingerprint = executor_request_fingerprint(
        execution_id=execution.id,
        action=payload.action,
        adapter_type=payload.adapter_type,
        payload=cleaned_payload,
    )
    existing = db.scalar(
        select(ExecutorRequest).where(
            ExecutorRequest.execution_id == execution.id,
            ExecutorRequest.fingerprint == fingerprint,
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "An identical executor request already exists for this execution",
                "request_id": str(existing.id),
                "status": existing.status,
            },
        )

    request = ExecutorRequest(
        execution_id=execution.id,
        handoff_id=handoff.id,
        project_id=execution.project_id,
        action=payload.action,
        adapter_type=payload.adapter_type,
        status="prepared",
        payload_json=cleaned_payload,
        fingerprint=fingerprint,
        notes=redact_secrets(payload.notes),
        result_json={},
    )
    db.add(request)
    try:
        db.flush()
        append_execution_event(
            db,
            execution,
            event_type="executor_request",
            message=f"Executor request prepared: {payload.action}",
            payload={
                "request_id": str(request.id),
                "action": request.action,
                "adapter_type": request.adapter_type,
                "fingerprint": request.fingerprint,
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="An identical executor request already exists") from exc
    db.refresh(request)
    return executor_request_payload(request)


@router.get("/agent-executions/{execution_id}/executor-requests")
def list_executor_requests(execution_id: UUID, db: Session = Depends(get_db)) -> list[dict]:
    get_execution(db, execution_id)
    stmt = (
        select(ExecutorRequest)
        .where(ExecutorRequest.execution_id == execution_id)
        .order_by(ExecutorRequest.created_at.asc())
    )
    return [executor_request_payload(item) for item in db.scalars(stmt).all()]


@router.get("/executor-requests/{request_id}")
def read_executor_request(request_id: UUID, db: Session = Depends(get_db)) -> dict:
    return executor_request_payload(get_executor_request(db, request_id))


@router.post("/executor-requests/{request_id}/release")
def release_executor_request(request_id: UUID, db: Session = Depends(get_db)) -> dict:
    request = get_executor_request(db, request_id)
    if request.status == "released":
        return executor_request_payload(request)
    if request.status != "prepared":
        raise HTTPException(status_code=409, detail=f"Executor request is {request.status} and cannot be released")

    execution = get_execution(db, request.execution_id)
    handoff = get_handoff(db, request.handoff_id)
    validate_authorization(execution, handoff, request.action)
    request.status = "released"
    request.released_at = utcnow()
    append_execution_event(
        db,
        execution,
        event_type="executor_released",
        message=f"Executor request released: {request.action}",
        payload={"request_id": str(request.id), "action": request.action},
    )
    db.commit()
    db.refresh(request)
    return executor_request_payload(request)


@router.post("/executor-requests/{request_id}/execute")
def execute_executor_request(request_id: UUID, db: Session = Depends(get_db)) -> dict:
    request = get_executor_request(db, request_id)
    if request.status in TERMINAL_REQUEST_STATES:
        raise HTTPException(
            status_code=409,
            detail=f"Executor request is already terminal ({request.status}) and cannot be replayed",
        )
    if request.status == "running":
        raise HTTPException(status_code=409, detail="Executor request is already running")
    if request.status != "released":
        raise HTTPException(status_code=409, detail="Executor request must be explicitly released before execution")

    execution = get_execution(db, request.execution_id)
    handoff = get_handoff(db, request.handoff_id)
    validate_authorization(execution, handoff, request.action)

    try:
        adapter = resolve_executor_adapter(request.adapter_type)
    except ExecutorUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not getattr(adapter, "available", False):
        raise HTTPException(
            status_code=409,
            detail=f"Executor adapter {request.adapter_type!r} is not configured for automatic execution",
        )

    worker_attempt: WorkerAttempt | None = None
    if request.adapter_type == "isolated-local":
        active_attempts = list(
            db.scalars(
                select(WorkerAttempt).where(
                    WorkerAttempt.executor_request_id == request.id,
                    WorkerAttempt.status.in_(["leased", "running"]),
                )
            ).all()
        )
        running = next((item for item in active_attempts if item.status == "running"), None)
        if running is not None:
            raise HTTPException(status_code=409, detail="A worker attempt is already running")
        leased = next((item for item in active_attempts if item.status == "leased"), None)
        if leased is not None:
            worker_attempt = leased
        else:
            settings = get_settings()
            try:
                worker_attempt, _lease_token = create_attempt(
                    db,
                    request,
                    lease_seconds=settings.executor_worker_lease_seconds,
                    max_attempts=settings.executor_worker_max_attempts,
                )
            except ValueError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
        try:
            mark_attempt_running(worker_attempt)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        append_execution_event(
            db,
            execution,
            event_type="worker_attempt_started",
            message=f"Worker attempt #{worker_attempt.attempt_number} started",
            payload={"attempt_id": str(worker_attempt.id), "attempt_number": worker_attempt.attempt_number},
        )

    request.status = "running"
    request.started_at = utcnow()
    append_execution_event(
        db,
        execution,
        event_type="executor_started",
        message=f"Executor adapter started: {request.adapter_type}",
        payload={"request_id": str(request.id), "action": request.action, "adapter_type": request.adapter_type},
    )
    db.commit()
    db.refresh(request)

    try:
        outcome = adapter.execute(executor_command(request))
    except Exception as exc:  # adapter boundary: persist failure instead of leaking executor exceptions
        outcome = None
        adapter_error = sanitize_executor_error(str(exc)) or "Executor adapter failed"
    else:
        adapter_error = sanitize_executor_error(outcome.error)

    now = utcnow()
    if outcome is not None and outcome.ok:
        clean_result = bounded_result(outcome.result)
        request.status = "completed"
        request.result_json = clean_result
        request.error_text = None
        request.completed_at = now
        event_status = "completed"
        event_message = f"Executor request completed: {request.action}"
    else:
        clean_result = bounded_result(outcome.result if outcome is not None else {})
        request.status = "failed"
        request.result_json = clean_result
        request.error_text = adapter_error or "Executor adapter reported failure"
        request.failed_at = now
        event_status = "failed"
        event_message = request.error_text

    if worker_attempt is not None:
        finalize_attempt(
            worker_attempt,
            ok=(outcome is not None and outcome.ok),
            result=clean_result,
            error=request.error_text,
        )
        append_execution_event(
            db,
            execution,
            event_type="worker_attempt_result",
            message=f"Worker attempt #{worker_attempt.attempt_number} {worker_attempt.status}",
            payload={
                "attempt_id": str(worker_attempt.id),
                "attempt_number": worker_attempt.attempt_number,
                "status": worker_attempt.status,
                "worker_id": worker_attempt.worker_id,
                "job_digest": worker_attempt.job_digest,
                "result_digest": worker_attempt.result_digest,
            },
        )

    append_execution_event(
        db,
        execution,
        event_type="executor_result",
        message=event_message,
        payload={
            "request_id": str(request.id),
            "action": request.action,
            "status": event_status,
            "result": request.result_json,
            "error": request.error_text,
        },
    )
    db.commit()
    db.refresh(request)
    return executor_request_payload(request)


@router.post("/executor-requests/{request_id}/cancel")
def cancel_executor_request(request_id: UUID, db: Session = Depends(get_db)) -> dict:
    request = get_executor_request(db, request_id)
    if request.status == "cancelled":
        return executor_request_payload(request)
    if request.status in {"completed", "failed", "running"}:
        raise HTTPException(status_code=409, detail=f"Executor request is {request.status} and cannot be cancelled")
    if request.status not in {"prepared", "released"}:
        raise HTTPException(status_code=409, detail=f"Executor request is {request.status} and cannot be cancelled")

    execution = get_execution(db, request.execution_id)
    request.status = "cancelled"
    request.cancelled_at = utcnow()
    append_execution_event(
        db,
        execution,
        event_type="executor_result",
        message=f"Executor request cancelled: {request.action}",
        payload={"request_id": str(request.id), "action": request.action, "status": "cancelled"},
    )
    db.commit()
    db.refresh(request)
    return executor_request_payload(request)
