from __future__ import annotations

from time import perf_counter
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.google_context import build_context_with_google
from app.models import Project
from app.retrieval_metrics import evaluate_context_package


router = APIRouter(prefix="/evaluation", tags=["evaluation"])
ContextProfile = Literal["minimal", "standard", "deep"]


class ContextEvaluationRequest(BaseModel):
    project_id: UUID
    query: str = Field(min_length=1, max_length=4000)
    profile: ContextProfile = "standard"
    expected_source_refs: list[str] = Field(min_length=1, max_length=100)
    k: int = Field(default=5, ge=1, le=100)


@router.post("/context")
def evaluate_context(
    payload: ContextEvaluationRequest,
    db: Session = Depends(get_db),
) -> dict:
    project = db.get(Project, payload.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    started = perf_counter()
    package = build_context_with_google(
        db,
        project,
        payload.query,
        payload.profile,
    )
    elapsed_ms = round((perf_counter() - started) * 1000, 3)
    metrics = evaluate_context_package(
        package,
        payload.expected_source_refs,
        k=payload.k,
    )

    return {
        "project_id": project.id,
        "profile": payload.profile,
        "query": payload.query,
        "latency_ms": elapsed_ms,
        "metrics": metrics,
    }
