from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agent_models import AgentTaskPack
from app.agent_task_pack import build_agent_task_pack, render_task_pack_markdown
from app.database import get_db
from app.models import Project, utcnow


router = APIRouter(tags=["agent-task-packs"])
ContextProfile = Literal["minimal", "standard", "deep"]
PackStatus = Literal["pending", "approved", "cancelled"]


class AgentTaskPackRequest(BaseModel):
    project_id: UUID
    objective: str = Field(min_length=1, max_length=6000)
    acceptance_criteria: list[str] = Field(min_length=1, max_length=50)
    constraints: list[str] = Field(default_factory=list, max_length=50)
    suggested_areas: list[str] = Field(default_factory=list, max_length=100)
    profile: ContextProfile = "standard"
    query: str | None = Field(default=None, max_length=4000)


def get_project(db: Session, project_id: UUID) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def get_pack(db: Session, pack_id: UUID) -> AgentTaskPack:
    pack = db.get(AgentTaskPack, pack_id)
    if pack is None:
        raise HTTPException(status_code=404, detail="Agent task pack not found")
    return pack


def model_payload(pack: AgentTaskPack) -> dict:
    return {
        "id": pack.id,
        "project_id": pack.project_id,
        "status": pack.status,
        "ready_for_handoff": pack.status == "approved",
        "authorized_for_execution": False,
        "project": pack.project_snapshot_json or {},
        "objective": pack.objective,
        "profile": pack.profile,
        "query": pack.query_text,
        "acceptance_criteria": pack.acceptance_criteria_json or [],
        "constraints": pack.constraints_json or [],
        "suggested_areas": pack.suggested_areas_json or [],
        "context": pack.context_json or [],
        "sources": pack.sources_json or [],
        "budget": pack.budget_json or {},
        "fingerprint": pack.fingerprint,
        "created_at": pack.created_at,
        "approved_at": pack.approved_at,
        "cancelled_at": pack.cancelled_at,
    }


def content_payload(pack: AgentTaskPack) -> dict:
    return {
        "project": pack.project_snapshot_json or {},
        "objective": pack.objective,
        "profile": pack.profile,
        "query": pack.query_text,
        "acceptance_criteria": pack.acceptance_criteria_json or [],
        "constraints": pack.constraints_json or [],
        "suggested_areas": pack.suggested_areas_json or [],
        "context": pack.context_json or [],
        "sources": pack.sources_json or [],
        "budget": pack.budget_json or {},
        "fingerprint": pack.fingerprint,
    }


@router.post("/agent-task-packs/preview")
def preview_agent_task_pack(
    payload: AgentTaskPackRequest,
    db: Session = Depends(get_db),
) -> dict:
    project = get_project(db, payload.project_id)
    try:
        pack = build_agent_task_pack(
            db,
            project,
            objective=payload.objective,
            acceptance_criteria=payload.acceptance_criteria,
            constraints=payload.constraints,
            suggested_areas=payload.suggested_areas,
            profile=payload.profile,
            query=payload.query,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        **pack,
        "status": "preview",
        "ready_for_handoff": False,
        "authorized_for_execution": False,
    }


@router.post(
    "/agent-task-packs",
    status_code=status.HTTP_201_CREATED,
)
def create_agent_task_pack(
    payload: AgentTaskPackRequest,
    db: Session = Depends(get_db),
) -> dict:
    project = get_project(db, payload.project_id)
    try:
        built = build_agent_task_pack(
            db,
            project,
            objective=payload.objective,
            acceptance_criteria=payload.acceptance_criteria,
            constraints=payload.constraints,
            suggested_areas=payload.suggested_areas,
            profile=payload.profile,
            query=payload.query,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    existing = db.scalar(
        select(AgentTaskPack).where(AgentTaskPack.fingerprint == built["fingerprint"])
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "An identical agent task pack already exists",
                "pack_id": str(existing.id),
                "status": existing.status,
            },
        )

    pack = AgentTaskPack(
        project_id=project.id,
        status="pending",
        project_snapshot_json=built["project"],
        objective=built["objective"],
        profile=built["profile"],
        query_text=built["query"],
        acceptance_criteria_json=built["acceptance_criteria"],
        constraints_json=built["constraints"],
        suggested_areas_json=built["suggested_areas"],
        context_json=built["context"],
        sources_json=built["sources"],
        budget_json=built["budget"],
        fingerprint=built["fingerprint"],
    )
    db.add(pack)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Agent task pack fingerprint already exists") from exc
    db.refresh(pack)
    return model_payload(pack)


@router.get("/agent-task-packs/{pack_id}")
def read_agent_task_pack(pack_id: UUID, db: Session = Depends(get_db)) -> dict:
    return model_payload(get_pack(db, pack_id))


@router.get("/projects/{project_id}/agent-task-packs")
def list_agent_task_packs(
    project_id: UUID,
    pack_status: PackStatus | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
) -> list[dict]:
    get_project(db, project_id)
    stmt = select(AgentTaskPack).where(AgentTaskPack.project_id == project_id)
    if pack_status:
        stmt = stmt.where(AgentTaskPack.status == pack_status)
    stmt = stmt.order_by(AgentTaskPack.created_at.desc())
    return [model_payload(pack) for pack in db.scalars(stmt).all()]


@router.post("/agent-task-packs/{pack_id}/approve")
def approve_agent_task_pack(pack_id: UUID, db: Session = Depends(get_db)) -> dict:
    pack = get_pack(db, pack_id)
    if pack.status == "approved":
        return model_payload(pack)
    if pack.status != "pending":
        raise HTTPException(status_code=409, detail=f"Pack is {pack.status} and cannot be approved")
    pack.status = "approved"
    pack.approved_at = utcnow()
    db.commit()
    db.refresh(pack)
    return model_payload(pack)


@router.post("/agent-task-packs/{pack_id}/cancel")
def cancel_agent_task_pack(pack_id: UUID, db: Session = Depends(get_db)) -> dict:
    pack = get_pack(db, pack_id)
    if pack.status == "cancelled":
        return model_payload(pack)
    if pack.status != "pending":
        raise HTTPException(status_code=409, detail=f"Pack is {pack.status} and cannot be cancelled")
    pack.status = "cancelled"
    pack.cancelled_at = utcnow()
    db.commit()
    db.refresh(pack)
    return model_payload(pack)


@router.get(
    "/agent-task-packs/{pack_id}/markdown",
    response_class=PlainTextResponse,
)
def export_agent_task_pack_markdown(
    pack_id: UUID,
    db: Session = Depends(get_db),
) -> PlainTextResponse:
    pack = get_pack(db, pack_id)
    markdown = render_task_pack_markdown(content_payload(pack), status=pack.status)
    return PlainTextResponse(markdown, media_type="text/markdown; charset=utf-8")
