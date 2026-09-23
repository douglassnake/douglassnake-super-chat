from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Project, SessionDelta
from app.session_memory import (
    SessionDeltaConflict,
    SessionDeltaInvalid,
    apply_session_delta,
    create_session_delta,
    discard_session_delta,
    get_delta_or_raise,
    preview_session_delta,
)
from app.session_schemas import (
    SessionDeltaApplyResult,
    SessionDeltaCreate,
    SessionDeltaPreview,
    SessionDeltaRead,
    SessionDeltaStatus,
)

router = APIRouter(tags=["session-memory"])


def project_or_404(db: Session, project_id: UUID) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def delta_or_404(db: Session, delta_id: UUID) -> SessionDelta:
    try:
        return get_delta_or_raise(db, delta_id)
    except SessionDeltaInvalid as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/projects/{project_id}/session-deltas",
    response_model=SessionDeltaRead,
    status_code=status.HTTP_201_CREATED,
)
def create_delta(
    project_id: UUID,
    payload: SessionDeltaCreate,
    db: Session = Depends(get_db),
) -> SessionDelta:
    project = project_or_404(db, project_id)
    try:
        return create_session_delta(db, project, payload)
    except SessionDeltaConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/projects/{project_id}/session-deltas", response_model=list[SessionDeltaRead])
def list_deltas(
    project_id: UUID,
    delta_status: SessionDeltaStatus | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
) -> list[SessionDelta]:
    project_or_404(db, project_id)
    stmt = select(SessionDelta).where(SessionDelta.project_id == project_id)
    if delta_status is not None:
        stmt = stmt.where(SessionDelta.status == delta_status)
    stmt = stmt.order_by(SessionDelta.created_at.desc())
    return list(db.scalars(stmt).all())


@router.get("/session-deltas/{delta_id}/preview", response_model=SessionDeltaPreview)
def preview_delta(delta_id: UUID, db: Session = Depends(get_db)) -> SessionDeltaPreview:
    delta = delta_or_404(db, delta_id)
    return SessionDeltaPreview(
        delta=SessionDeltaRead.model_validate(delta),
        effects=preview_session_delta(db, delta),
    )


@router.post("/session-deltas/{delta_id}/apply", response_model=SessionDeltaApplyResult)
def apply_delta(delta_id: UUID, db: Session = Depends(get_db)) -> SessionDeltaApplyResult:
    delta = delta_or_404(db, delta_id)
    try:
        result = apply_session_delta(db, delta)
    except SessionDeltaConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SessionDeltaInvalid as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return SessionDeltaApplyResult(
        delta=SessionDeltaRead.model_validate(delta),
        **result,
    )


@router.post("/session-deltas/{delta_id}/discard", response_model=SessionDeltaRead)
def discard_delta(delta_id: UUID, db: Session = Depends(get_db)) -> SessionDelta:
    delta = delta_or_404(db, delta_id)
    try:
        return discard_session_delta(db, delta)
    except SessionDeltaConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
