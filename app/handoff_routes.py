from __future__ import annotations

import json
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent_handoff import (
    build_pack_handoff_snapshot,
    clean_allowed_actions,
    handoff_payload,
    render_handoff_markdown,
    sanitize_value,
)
from app.agent_models import AgentExecution, AgentHandoff, AgentTaskPack
from app.agent_task_pack import redact_secrets
from app.database import get_db
from app.models import utcnow


router = APIRouter(tags=["agent-handoffs"])
HandoffStatus = Literal["prepared", "released", "completed", "failed", "cancelled"]


class AgentHandoffCreateRequest(BaseModel):
    executor_type: str = Field(min_length=1, max_length=60, pattern=r"^[A-Za-z0-9._-]+$")
    executor_target: str | None = Field(default=None, max_length=2000)
    allowed_actions: list[str] = Field(default_factory=list, max_length=20)
    notes: str | None = Field(default=None, max_length=6000)


class AgentHandoffCompleteRequest(BaseModel):
    result: dict = Field(default_factory=dict)


class AgentHandoffFailureRequest(BaseModel):
    error: str = Field(min_length=1, max_length=6000)
    result: dict = Field(default_factory=dict)


def get_pack(db: Session, pack_id: UUID) -> AgentTaskPack:
    pack = db.get(AgentTaskPack, pack_id)
    if pack is None:
        raise HTTPException(status_code=404, detail="Agent task pack not found")
    return pack


def get_handoff(db: Session, handoff_id: UUID) -> AgentHandoff:
    handoff = db.get(AgentHandoff, handoff_id)
    if handoff is None:
        raise HTTPException(status_code=404, detail="Agent handoff not found")
    return handoff


def reject_if_tracked_execution(db: Session, handoff_id: UUID, action: str) -> None:
    execution = db.scalar(select(AgentExecution).where(AgentExecution.handoff_id == handoff_id))
    if execution is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "This handoff has tracked execution; use the execution endpoint so evidence gates cannot be bypassed",
                "execution_id": str(execution.id),
                "execution_status": execution.status,
                "requested_action": action,
            },
        )


def sanitize_result(payload: dict) -> dict:
    result = sanitize_value(payload)
    rendered = json.dumps(result, ensure_ascii=False, sort_keys=True, default=str)
    if len(rendered) > 100_000:
        raise HTTPException(status_code=422, detail="Handoff result is too large")
    return result


@router.post(
    "/agent-task-packs/{pack_id}/handoffs",
    status_code=status.HTTP_201_CREATED,
)
def create_agent_handoff(
    pack_id: UUID,
    payload: AgentHandoffCreateRequest,
    db: Session = Depends(get_db),
) -> dict:
    pack = get_pack(db, pack_id)
    if pack.status != "approved":
        raise HTTPException(
            status_code=409,
            detail=f"Pack is {pack.status}; only approved packs can be handed off",
        )
    try:
        allowed_actions = clean_allowed_actions(payload.allowed_actions)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    handoff = AgentHandoff(
        pack_id=pack.id,
        project_id=pack.project_id,
        status="prepared",
        executor_type=payload.executor_type,
        executor_target=redact_secrets(payload.executor_target),
        allowed_actions_json=allowed_actions,
        pack_fingerprint=pack.fingerprint,
        pack_snapshot_json=build_pack_handoff_snapshot(pack),
        notes=redact_secrets(payload.notes),
        result_json={},
    )
    db.add(handoff)
    db.commit()
    db.refresh(handoff)
    return handoff_payload(handoff)


@router.get("/agent-handoffs/{handoff_id}")
def read_agent_handoff(handoff_id: UUID, db: Session = Depends(get_db)) -> dict:
    return handoff_payload(get_handoff(db, handoff_id))


@router.get("/agent-task-packs/{pack_id}/handoffs")
def list_agent_handoffs(
    pack_id: UUID,
    handoff_status: HandoffStatus | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
) -> list[dict]:
    get_pack(db, pack_id)
    stmt = select(AgentHandoff).where(AgentHandoff.pack_id == pack_id)
    if handoff_status:
        stmt = stmt.where(AgentHandoff.status == handoff_status)
    stmt = stmt.order_by(AgentHandoff.created_at.desc())
    return [handoff_payload(item) for item in db.scalars(stmt).all()]


@router.post("/agent-handoffs/{handoff_id}/release")
def release_agent_handoff(handoff_id: UUID, db: Session = Depends(get_db)) -> dict:
    handoff = get_handoff(db, handoff_id)
    if handoff.status == "released":
        return handoff_payload(handoff)
    if handoff.status != "prepared":
        raise HTTPException(
            status_code=409,
            detail=f"Handoff is {handoff.status} and cannot be released",
        )
    handoff.status = "released"
    handoff.released_at = utcnow()
    db.commit()
    db.refresh(handoff)
    return handoff_payload(handoff)


@router.post("/agent-handoffs/{handoff_id}/complete")
def complete_agent_handoff(
    handoff_id: UUID,
    payload: AgentHandoffCompleteRequest,
    db: Session = Depends(get_db),
) -> dict:
    handoff = get_handoff(db, handoff_id)
    reject_if_tracked_execution(db, handoff.id, "complete")
    if handoff.status == "completed":
        return handoff_payload(handoff)
    if handoff.status != "released":
        raise HTTPException(
            status_code=409,
            detail=f"Handoff is {handoff.status} and cannot be completed",
        )
    handoff.result_json = sanitize_result(payload.result)
    handoff.error_text = None
    handoff.status = "completed"
    handoff.completed_at = utcnow()
    db.commit()
    db.refresh(handoff)
    return handoff_payload(handoff)


@router.post("/agent-handoffs/{handoff_id}/fail")
def fail_agent_handoff(
    handoff_id: UUID,
    payload: AgentHandoffFailureRequest,
    db: Session = Depends(get_db),
) -> dict:
    handoff = get_handoff(db, handoff_id)
    reject_if_tracked_execution(db, handoff.id, "fail")
    if handoff.status == "failed":
        return handoff_payload(handoff)
    if handoff.status != "released":
        raise HTTPException(
            status_code=409,
            detail=f"Handoff is {handoff.status} and cannot be failed",
        )
    handoff.result_json = sanitize_result(payload.result)
    handoff.error_text = redact_secrets(payload.error)
    handoff.status = "failed"
    handoff.failed_at = utcnow()
    db.commit()
    db.refresh(handoff)
    return handoff_payload(handoff)


@router.post("/agent-handoffs/{handoff_id}/cancel")
def cancel_agent_handoff(handoff_id: UUID, db: Session = Depends(get_db)) -> dict:
    handoff = get_handoff(db, handoff_id)
    reject_if_tracked_execution(db, handoff.id, "cancel")
    if handoff.status == "cancelled":
        return handoff_payload(handoff)
    if handoff.status not in {"prepared", "released"}:
        raise HTTPException(
            status_code=409,
            detail=f"Handoff is {handoff.status} and cannot be cancelled",
        )
    handoff.status = "cancelled"
    handoff.cancelled_at = utcnow()
    db.commit()
    db.refresh(handoff)
    return handoff_payload(handoff)


@router.get(
    "/agent-handoffs/{handoff_id}/markdown",
    response_class=PlainTextResponse,
)
def export_agent_handoff_markdown(
    handoff_id: UUID,
    db: Session = Depends(get_db),
) -> PlainTextResponse:
    handoff = get_handoff(db, handoff_id)
    pack = get_pack(db, handoff.pack_id)
    if pack.fingerprint != handoff.pack_fingerprint:
        raise HTTPException(
            status_code=409,
            detail="Task pack fingerprint no longer matches the handoff snapshot",
        )
    return PlainTextResponse(
        render_handoff_markdown(handoff, pack),
        media_type="text/markdown; charset=utf-8",
    )
