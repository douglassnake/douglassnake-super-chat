"""M13.8: explicit, authenticated, audit-only reconciliation reviews.

Reviews are recorded without completing tasks or modifying the official next action.
"""
from __future__ import annotations

from datetime import timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Event, Task, utcnow

router = APIRouter(prefix="/ops/task-reconciliation", tags=["operations"])


class ReviewRequest(BaseModel):
    task_id: UUID
    request_id: UUID
    expected_updated_at: str = Field(min_length=10, max_length=60)
    decision: str = Field(pattern="^(keep_open|needs_investigation)$")
    justification: str = Field(min_length=15, max_length=4000)
    evidence_urls: list[str] = Field(default_factory=list, max_length=12)


def _normalize_time(value):
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)


@router.post("/reviews", status_code=201)
def record_review(payload: ReviewRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    """Explicit review only; never changes Task.status or Project.next_action."""
    principal = getattr(request.state, "auth_principal", None)
    if not getattr(request.state, "authenticated", False) or not principal:
        raise HTTPException(401, "Autenticação necessária")
    if principal.get("role") != "admin":
        raise HTTPException(403, "Permissão de administrador necessária")
    if not getattr(request.app.state.settings, "auth_enabled", False):
        raise HTTPException(403, "Revisão exige autenticação habilitada")

    # Serialize review against task updates in this transaction.
    task = db.scalar(select(Task).where(Task.id == payload.task_id).with_for_update())
    if task is None or task.project_id is None:
        raise HTTPException(404, "Tarefa não encontrada")
    existing = db.scalar(select(Event).where(
        Event.project_id == task.project_id,
        Event.event_type == "reconciliation.review",
        Event.external_id == str(payload.request_id),
    ))
    if existing is not None:
        metadata = existing.metadata_json or {}
        if (metadata.get("task_id") != str(task.id)
            or metadata.get("decision") != payload.decision
            or existing.body != payload.justification
            or metadata.get("evidence_urls") != payload.evidence_urls
            or metadata.get("task_updated_at") != payload.expected_updated_at):
            raise HTTPException(409, "Chave de revisão reutilizada com conteúdo diferente")
        return {"review_id": str(existing.id), "task_id": str(task.id),
                "decision": payload.decision, "changes_applied": 0}
    if task.status in {"done", "cancelled"}:
        raise HTTPException(409, "Tarefa já encerrada")
    try:
        from datetime import datetime
        expected = datetime.fromisoformat(payload.expected_updated_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(422, "Data de versão inválida") from exc
    if _normalize_time(expected) != _normalize_time(task.updated_at):
        raise HTTPException(409, "Tarefa alterada desde a consulta")
    urls = []
    for raw in payload.evidence_urls:
        from urllib.parse import urlparse
        parsed = urlparse(raw)
        if parsed.scheme != "https" or parsed.hostname != "github.com" or parsed.username or parsed.password:
            raise HTTPException(422, "Evidência deve ser uma URL HTTPS do GitHub")
        urls.append(raw)

    audit_id = uuid4()
    event = Event(
        id=audit_id, project_id=task.project_id,
        source_type="manual", event_type="reconciliation.review",
        external_id=str(payload.request_id),
        title="Revisão manual de tarefa de CI",
        body=payload.justification,
        occurred_at=utcnow(),
        metadata_json={
            "actor": principal["username"],
            "task_id": str(task.id), "task_status": task.status,
            "task_updated_at": payload.expected_updated_at,
            "decision": payload.decision,
            "evidence_urls": urls,
            "changes_applied": 0,
        },
    )
    db.add(event)
    db.commit()
    return {"review_id": str(audit_id), "task_id": str(task.id),
            "decision": payload.decision, "changes_applied": 0}
