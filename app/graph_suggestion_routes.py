from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.graph_suggestion_schemas import (
    GraphSuggestionApplyRequest,
    GraphSuggestionApplyResult,
    GraphSuggestionBatchRead,
)
from app.graph_suggestions import (
    apply_suggestion_batch,
    create_suggestion_batch,
    discard_suggestion_batch,
)
from app.knowledge_models import GraphSuggestionBatch
from app.models import Project


router = APIRouter(tags=["graph-suggestions"])


def _project_or_404(db: Session, project_id: UUID) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _batch_or_404(db: Session, batch_id: UUID) -> GraphSuggestionBatch:
    batch = db.get(GraphSuggestionBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Graph suggestion batch not found")
    return batch


def _read(batch: GraphSuggestionBatch) -> GraphSuggestionBatchRead:
    return GraphSuggestionBatchRead(
        id=batch.id,
        project_id=batch.project_id,
        status=batch.status,
        summary=batch.summary,
        suggestions=batch.suggestions_json or [],
        source_refs=batch.source_refs_json or [],
        created_at=batch.created_at,
        applied_at=batch.applied_at,
        discarded_at=batch.discarded_at,
    )


@router.post(
    "/projects/{project_id}/graph/suggestions",
    response_model=GraphSuggestionBatchRead,
    status_code=status.HTTP_201_CREATED,
)
def prepare_graph_suggestions(
    project_id: UUID,
    db: Session = Depends(get_db),
) -> GraphSuggestionBatchRead:
    project = _project_or_404(db, project_id)
    batch = create_suggestion_batch(db, project)
    return _read(batch)


@router.get(
    "/projects/{project_id}/graph/suggestions",
    response_model=list[GraphSuggestionBatchRead],
)
def list_graph_suggestions(
    project_id: UUID,
    batch_status: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
) -> list[GraphSuggestionBatchRead]:
    _project_or_404(db, project_id)
    stmt = select(GraphSuggestionBatch).where(GraphSuggestionBatch.project_id == project_id)
    if batch_status:
        stmt = stmt.where(GraphSuggestionBatch.status == batch_status)
    stmt = stmt.order_by(GraphSuggestionBatch.created_at.desc()).limit(20)
    return [_read(item) for item in db.scalars(stmt).all()]


@router.get("/graph-suggestions/{batch_id}", response_model=GraphSuggestionBatchRead)
def get_graph_suggestion_batch(
    batch_id: UUID,
    db: Session = Depends(get_db),
) -> GraphSuggestionBatchRead:
    return _read(_batch_or_404(db, batch_id))


@router.post(
    "/graph-suggestions/{batch_id}/apply",
    response_model=GraphSuggestionApplyResult,
)
def apply_graph_suggestions(
    batch_id: UUID,
    payload: GraphSuggestionApplyRequest,
    db: Session = Depends(get_db),
) -> GraphSuggestionApplyResult:
    batch = _batch_or_404(db, batch_id)
    try:
        applied_count, skipped_count = apply_suggestion_batch(
            db,
            batch,
            payload.selected_indexes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IndexError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.refresh(batch)
    return GraphSuggestionApplyResult(
        batch=_read(batch),
        applied_count=applied_count,
        skipped_count=skipped_count,
    )


@router.post(
    "/graph-suggestions/{batch_id}/discard",
    response_model=GraphSuggestionBatchRead,
)
def discard_graph_suggestions(
    batch_id: UUID,
    db: Session = Depends(get_db),
) -> GraphSuggestionBatchRead:
    batch = _batch_or_404(db, batch_id)
    try:
        discard_suggestion_batch(db, batch)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.refresh(batch)
    return _read(batch)
