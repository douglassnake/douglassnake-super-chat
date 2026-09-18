from __future__ import annotations

import json
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agent_execution import (
    append_execution_event,
    completion_gate,
    criteria_summary,
    execution_event_payload,
    execution_payload,
    list_execution_events,
    sanitize_reference,
)
from app.agent_handoff import sanitize_value
from app.agent_models import AgentExecution, AgentHandoff, AgentTaskPack
from app.agent_task_pack import redact_secrets
from app.database import get_db
from app.models import utcnow


router = APIRouter(tags=["agent-executions"])
EvidenceStatus = Literal["passed", "failed"]


class ExecutionProgressRequest(BaseModel):
    progress_percent: int = Field(ge=0, le=100)
    current_step: str | None = Field(default=None, max_length=2000)
    message: str | None = Field(default=None, max_length=6000)


class ExecutionTechnicalRefsRequest(BaseModel):
    branch_ref: str | None = Field(default=None, max_length=1000)
    commit_sha: str | None = Field(default=None, max_length=128)
    pr_url: str | None = Field(default=None, max_length=3000)
    message: str | None = Field(default=None, max_length=6000)

    @model_validator(mode="after")
    def require_reference(self):
        if self.branch_ref is None and self.commit_sha is None and self.pr_url is None:
            raise ValueError("At least one technical reference is required")
        return self


class ExecutionEvidenceRequest(BaseModel):
    criterion_index: int = Field(ge=0)
    status: EvidenceStatus
    evidence_type: str = Field(min_length=1, max_length=60, pattern=r"^[A-Za-z0-9._-]+$")
    summary: str = Field(min_length=1, max_length=6000)
    reference: str | None = Field(default=None, max_length=3000)
    payload: dict = Field(default_factory=dict)


class ExecutionCompleteRequest(BaseModel):
    summary: str | None = Field(default=None, max_length=6000)
    result: dict = Field(default_factory=dict)


class ExecutionFailureRequest(BaseModel):
    error: str = Field(min_length=1, max_length=6000)
    result: dict = Field(default_factory=dict)


def get_handoff(db: Session, handoff_id: UUID) -> AgentHandoff:
    handoff = db.get(AgentHandoff, handoff_id)
    if handoff is None:
        raise HTTPException(status_code=404, detail="Agent handoff not found")
    return handoff


def get_execution(db: Session, execution_id: UUID) -> AgentExecution:
    execution = db.get(AgentExecution, execution_id)
    if execution is None:
        raise HTTPException(status_code=404, detail="Agent execution not found")
    return execution


def get_pack(db: Session, pack_id: UUID) -> AgentTaskPack:
    pack = db.get(AgentTaskPack, pack_id)
    if pack is None:
        raise HTTPException(status_code=404, detail="Agent task pack not found")
    return pack


def get_execution_pack(db: Session, execution: AgentExecution) -> AgentTaskPack:
    return get_pack(db, execution.pack_id)


def sanitize_bounded_json(payload: dict, *, field_name: str) -> dict:
    cleaned = sanitize_value(payload)
    rendered = json.dumps(cleaned, ensure_ascii=False, sort_keys=True, default=str)
    if len(rendered) > 100_000:
        raise HTTPException(status_code=422, detail=f"{field_name} is too large")
    return cleaned


@router.post(
    "/agent-handoffs/{handoff_id}/execution",
    status_code=status.HTTP_201_CREATED,
)
def create_agent_execution(
    handoff_id: UUID,
    db: Session = Depends(get_db),
) -> dict:
    handoff = get_handoff(db, handoff_id)
    if handoff.status != "released":
        raise HTTPException(
            status_code=409,
            detail=f"Handoff is {handoff.status}; execution tracking requires a released handoff",
        )

    existing = db.scalar(select(AgentExecution).where(AgentExecution.handoff_id == handoff.id))
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "An execution already exists for this handoff",
                "execution_id": str(existing.id),
                "status": existing.status,
            },
        )

    pack = get_pack(db, handoff.pack_id)
    if pack.fingerprint != handoff.pack_fingerprint:
        raise HTTPException(status_code=409, detail="Task pack fingerprint does not match handoff snapshot")

    execution = AgentExecution(
        handoff_id=handoff.id,
        pack_id=pack.id,
        project_id=handoff.project_id,
        status="running",
        progress_percent=0,
        current_step=None,
        event_sequence=0,
        result_json={},
    )
    db.add(execution)
    try:
        db.flush()
        append_execution_event(
            db,
            execution,
            event_type="started",
            message="Execution tracking started",
            payload={
                "handoff_id": str(handoff.id),
                "pack_fingerprint": handoff.pack_fingerprint,
                "executor_type": handoff.executor_type,
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="An execution already exists for this handoff") from exc
    db.refresh(execution)
    return execution_payload(db, execution, pack)


@router.get("/agent-handoffs/{handoff_id}/execution")
def read_execution_by_handoff(handoff_id: UUID, db: Session = Depends(get_db)) -> dict:
    get_handoff(db, handoff_id)
    execution = db.scalar(select(AgentExecution).where(AgentExecution.handoff_id == handoff_id))
    if execution is None:
        raise HTTPException(status_code=404, detail="Agent execution not found")
    pack = get_execution_pack(db, execution)
    return execution_payload(db, execution, pack)


@router.get("/agent-executions/{execution_id}")
def read_agent_execution(execution_id: UUID, db: Session = Depends(get_db)) -> dict:
    execution = get_execution(db, execution_id)
    pack = get_execution_pack(db, execution)
    return execution_payload(db, execution, pack)


@router.get("/agent-executions/{execution_id}/events")
def read_agent_execution_events(execution_id: UUID, db: Session = Depends(get_db)) -> list[dict]:
    get_execution(db, execution_id)
    return [execution_event_payload(event) for event in list_execution_events(db, execution_id)]


@router.post("/agent-executions/{execution_id}/progress")
def record_execution_progress(
    execution_id: UUID,
    payload: ExecutionProgressRequest,
    db: Session = Depends(get_db),
) -> dict:
    execution = get_execution(db, execution_id)
    if execution.status != "running":
        raise HTTPException(status_code=409, detail=f"Execution is {execution.status} and cannot receive progress")

    execution.progress_percent = payload.progress_percent
    execution.current_step = redact_secrets(payload.current_step)
    append_execution_event(
        db,
        execution,
        event_type="progress",
        message=payload.message,
        payload={
            "progress_percent": payload.progress_percent,
            "current_step": execution.current_step,
        },
    )
    db.commit()
    db.refresh(execution)
    return execution_payload(db, execution, get_execution_pack(db, execution))


@router.post("/agent-executions/{execution_id}/technical-refs")
def record_execution_technical_refs(
    execution_id: UUID,
    payload: ExecutionTechnicalRefsRequest,
    db: Session = Depends(get_db),
) -> dict:
    execution = get_execution(db, execution_id)
    if execution.status != "running":
        raise HTTPException(status_code=409, detail=f"Execution is {execution.status} and cannot receive references")

    if payload.branch_ref is not None:
        execution.branch_ref = redact_secrets(payload.branch_ref)
    if payload.commit_sha is not None:
        execution.commit_sha = redact_secrets(payload.commit_sha)
    if payload.pr_url is not None:
        execution.pr_url = sanitize_reference(payload.pr_url)

    append_execution_event(
        db,
        execution,
        event_type="technical_refs",
        message=payload.message,
        payload={
            "branch_ref": execution.branch_ref,
            "commit_sha": execution.commit_sha,
            "pr_url": execution.pr_url,
        },
    )
    db.commit()
    db.refresh(execution)
    return execution_payload(db, execution, get_execution_pack(db, execution))


@router.post("/agent-executions/{execution_id}/evidence")
def record_execution_evidence(
    execution_id: UUID,
    payload: ExecutionEvidenceRequest,
    db: Session = Depends(get_db),
) -> dict:
    execution = get_execution(db, execution_id)
    if execution.status != "running":
        raise HTTPException(status_code=409, detail=f"Execution is {execution.status} and cannot receive evidence")

    pack = get_execution_pack(db, execution)
    criteria = list(pack.acceptance_criteria_json or [])
    if payload.criterion_index >= len(criteria):
        raise HTTPException(
            status_code=422,
            detail=f"Criterion index {payload.criterion_index} does not exist",
        )

    evidence_payload = sanitize_bounded_json(payload.payload, field_name="Evidence payload")
    evidence_payload.update(
        {
            "criterion": criteria[payload.criterion_index],
            "evidence_type": payload.evidence_type,
            "summary": redact_secrets(payload.summary),
            "reference": sanitize_reference(payload.reference),
        }
    )
    append_execution_event(
        db,
        execution,
        event_type="criterion_evidence",
        message=payload.summary,
        payload=evidence_payload,
        criterion_index=payload.criterion_index,
        criterion_status=payload.status,
    )
    db.commit()
    db.refresh(execution)
    return execution_payload(db, execution, pack)


@router.post("/agent-executions/{execution_id}/complete")
def complete_agent_execution(
    execution_id: UUID,
    payload: ExecutionCompleteRequest,
    db: Session = Depends(get_db),
) -> dict:
    execution = get_execution(db, execution_id)
    pack = get_execution_pack(db, execution)
    if execution.status == "completed":
        return execution_payload(db, execution, pack)
    if execution.status != "running":
        raise HTTPException(status_code=409, detail=f"Execution is {execution.status} and cannot be completed")

    criteria = criteria_summary(db, execution, pack)
    gate = completion_gate(criteria)
    if not gate["complete_allowed"]:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "All acceptance criteria require latest explicit passed evidence",
                "criteria_coverage": gate,
                "criteria": criteria,
            },
        )

    result = sanitize_bounded_json(payload.result, field_name="Execution result")
    summary = redact_secrets(payload.summary)
    now = utcnow()
    execution.status = "completed"
    execution.progress_percent = 100
    execution.current_step = "Completed"
    execution.result_json = {**result, **({"summary": summary} if summary else {})}
    execution.error_text = None
    execution.completed_at = now

    handoff = get_handoff(db, execution.handoff_id)
    handoff.status = "completed"
    handoff.result_json = execution.result_json
    handoff.error_text = None
    handoff.completed_at = now

    append_execution_event(
        db,
        execution,
        event_type="status",
        message=summary or "Execution completed",
        payload={"status": "completed", "criteria_coverage": gate},
    )
    db.commit()
    db.refresh(execution)
    return execution_payload(db, execution, pack)


@router.post("/agent-executions/{execution_id}/fail")
def fail_agent_execution(
    execution_id: UUID,
    payload: ExecutionFailureRequest,
    db: Session = Depends(get_db),
) -> dict:
    execution = get_execution(db, execution_id)
    pack = get_execution_pack(db, execution)
    if execution.status == "failed":
        return execution_payload(db, execution, pack)
    if execution.status != "running":
        raise HTTPException(status_code=409, detail=f"Execution is {execution.status} and cannot be failed")

    result = sanitize_bounded_json(payload.result, field_name="Execution result")
    error = redact_secrets(payload.error)
    now = utcnow()
    execution.status = "failed"
    execution.result_json = result
    execution.error_text = error
    execution.failed_at = now

    handoff = get_handoff(db, execution.handoff_id)
    handoff.status = "failed"
    handoff.result_json = result
    handoff.error_text = error
    handoff.failed_at = now

    append_execution_event(
        db,
        execution,
        event_type="status",
        message=error,
        payload={"status": "failed"},
    )
    db.commit()
    db.refresh(execution)
    return execution_payload(db, execution, pack)


@router.post("/agent-executions/{execution_id}/cancel")
def cancel_agent_execution(execution_id: UUID, db: Session = Depends(get_db)) -> dict:
    execution = get_execution(db, execution_id)
    pack = get_execution_pack(db, execution)
    if execution.status == "cancelled":
        return execution_payload(db, execution, pack)
    if execution.status != "running":
        raise HTTPException(status_code=409, detail=f"Execution is {execution.status} and cannot be cancelled")

    now = utcnow()
    execution.status = "cancelled"
    execution.cancelled_at = now

    handoff = get_handoff(db, execution.handoff_id)
    handoff.status = "cancelled"
    handoff.cancelled_at = now

    append_execution_event(
        db,
        execution,
        event_type="status",
        message="Execution cancelled",
        payload={"status": "cancelled"},
    )
    db.commit()
    db.refresh(execution)
    return execution_payload(db, execution, pack)
