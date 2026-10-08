from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Event, Project, ProjectSource, SessionDelta, Task
from app.session_memory import SessionDeltaConflict, create_session_delta
from app.session_schemas import ProposedTask, SessionDeltaCreate


DIGEST_PREFIX = "github-digest:"
FAILURE_CONCLUSIONS = {"failure", "cancelled", "timed_out", "action_required", "startup_failure"}


def _event_ref(event_id: UUID) -> str:
    return f"event:{event_id}"


def _parse_event_ref(value: object) -> UUID | None:
    text = str(value or "")
    if not text.startswith("event:"):
        return None
    try:
        return UUID(text.removeprefix("event:"))
    except ValueError:
        return None


def _pending_digest(db: Session, project_id: UUID) -> SessionDelta | None:
    return db.scalar(
        select(SessionDelta)
        .where(
            SessionDelta.project_id == project_id,
            SessionDelta.status == "pending",
            SessionDelta.session_key.like(f"{DIGEST_PREFIX}%"),
        )
        .order_by(SessionDelta.created_at.desc())
        .limit(1)
    )


def _reviewed_event_ids(db: Session, project_id: UUID) -> set[UUID]:
    deltas = list(
        db.scalars(
            select(SessionDelta).where(
                SessionDelta.project_id == project_id,
                SessionDelta.session_key.like(f"{DIGEST_PREFIX}%"),
            )
        ).all()
    )
    reviewed: set[UUID] = set()
    for delta in deltas:
        for ref in delta.source_refs_json or []:
            parsed = _parse_event_ref(ref)
            if parsed is not None:
                reviewed.add(parsed)
    return reviewed


def _existing_open_task_titles(db: Session, project_id: UUID) -> set[str]:
    titles = db.scalars(
        select(Task.title).where(
            Task.project_id == project_id,
            Task.status.notin_(["done", "cancelled"]),
        )
    ).all()
    return {str(title).strip().casefold() for title in titles if title}


def _task_suggestions(db: Session, project_id: UUID, events: list[Event]) -> list[ProposedTask]:
    existing = _existing_open_task_titles(db, project_id)
    tasks: list[ProposedTask] = []

    def add(title: str, description: str, priority: int, source_ref: str) -> None:
        if title.casefold() in existing:
            return
        tasks.append(
            ProposedTask(
                title=title,
                description=description,
                priority=priority,
                source_ref=source_ref,
            )
        )
        existing.add(title.casefold())

    issues = [item for item in events if item.event_type == "github.issue"]
    pulls = [item for item in events if item.event_type == "github.pull_request"]
    failed_runs = [
        item
        for item in events
        if item.event_type == "github.workflow_run"
        and str((item.metadata_json or {}).get("conclusion") or "").lower() in FAILURE_CONCLUSIONS
    ]

    if failed_runs:
        evidence = "; ".join(item.title for item in failed_runs[:5])
        add(
            "Investigar novas falhas de CI",
            f"{len(failed_runs)} execução(ões) com falha apareceram no digest. Evidência: {evidence}.",
            90,
            _event_ref(failed_runs[0].id),
        )

    if pulls:
        evidence = "; ".join(item.title for item in pulls[:5])
        add(
            "Revisar novos pull requests do GitHub",
            f"{len(pulls)} pull request(s) novo(s) entraram no contexto. Evidência: {evidence}.",
            75,
            _event_ref(pulls[0].id),
        )

    if issues:
        evidence = "; ".join(item.title for item in issues[:5])
        add(
            "Revisar novas issues do GitHub",
            f"{len(issues)} issue(s) nova(s) entraram no contexto. Evidência: {evidence}.",
            70,
            _event_ref(issues[0].id),
        )

    return tasks


def prepare_github_digest(
    db: Session,
    project: Project,
    *,
    since: datetime | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    pending = _pending_digest(db, project.id)
    if pending is not None:
        return {
            "delta": pending,
            "created": False,
            "pending_exists": True,
            "event_count": 0,
        }

    reviewed = _reviewed_event_ids(db, project.id)
    stmt = (
        select(Event)
        .where(
            Event.project_id == project.id,
            Event.source_type == "github",
        )
        .order_by(Event.created_at.asc(), Event.id.asc())
    )
    if since is not None:
        stmt = stmt.where(Event.created_at >= since)

    events = [event for event in db.scalars(stmt).all() if event.id not in reviewed][:limit]
    if not events:
        return {
            "delta": None,
            "created": False,
            "pending_exists": False,
            "event_count": 0,
        }

    counts = Counter(event.event_type for event in events)
    labels = {
        "github.commit": "commit(s)",
        "github.pull_request": "PR(s)",
        "github.issue": "issue(s)",
        "github.workflow_run": "workflow run(s)",
    }
    count_text = ", ".join(
        f"{counts[kind]} {labels.get(kind, kind)}"
        for kind in sorted(counts)
    )
    highlights = " | ".join(event.title for event in events[-8:])
    summary = (
        f"Digest GitHub com {len(events)} mudança(s) nova(s): {count_text}. "
        f"Destaques: {highlights}. "
        "Nada abaixo altera tarefas, decisões ou memória operacional até revisão e aplicação manual."
    )

    now = datetime.now(timezone.utc)
    payload = SessionDeltaCreate(
        session_key=f"{DIGEST_PREFIX}{now.strftime('%Y%m%dT%H%M%SZ')}:{uuid4().hex[:8]}",
        summary=summary,
        tasks=_task_suggestions(db, project.id, events),
        source_refs=[_event_ref(event.id) for event in events],
        started_at=min(event.created_at for event in events),
        ended_at=max(event.created_at for event in events),
    )
    try:
        delta = create_session_delta(db, project, payload)
    except SessionDeltaConflict:
        existing = _pending_digest(db, project.id)
        if existing is None:
            raise
        delta = existing
        return {
            "delta": delta,
            "created": False,
            "pending_exists": True,
            "event_count": 0,
        }

    return {
        "delta": delta,
        "created": True,
        "pending_exists": False,
        "event_count": len(events),
        "counts": dict(counts),
        "suggested_tasks": len(delta.tasks_json or []),
    }


def _parse_cursor(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def digest_cursor(db: Session, project_id: UUID) -> datetime | None:
    sources = list(
        db.scalars(
            select(ProjectSource).where(
                ProjectSource.project_id == project_id,
                ProjectSource.source_type == "github",
                ProjectSource.is_active.is_(True),
            )
        ).all()
    )
    cursors = [_parse_cursor((source.metadata_json or {}).get("github_digest_cursor_at")) for source in sources]
    if not sources or any(cursor is None for cursor in cursors):
        return None
    return min(cursor for cursor in cursors if cursor is not None)


def advance_digest_cursor(db: Session, project_id: UUID, cursor_at: datetime) -> None:
    sources = list(
        db.scalars(
            select(ProjectSource).where(
                ProjectSource.project_id == project_id,
                ProjectSource.source_type == "github",
                ProjectSource.is_active.is_(True),
            )
        ).all()
    )
    for source in sources:
        metadata = dict(source.metadata_json or {})
        metadata["github_digest_cursor_at"] = cursor_at.isoformat()
        source.metadata_json = metadata
        source.updated_at = cursor_at
    db.commit()


def prepare_automatic_github_digest(
    db: Session,
    project: Project,
    *,
    sync_started_at: datetime,
    sync_completed_at: datetime | None = None,
) -> dict[str, Any]:
    if _pending_digest(db, project.id) is not None:
        return {
            "delta": _pending_digest(db, project.id),
            "created": False,
            "pending_exists": True,
            "event_count": 0,
        }

    since = digest_cursor(db, project.id) or sync_started_at
    result = prepare_github_digest(db, project, since=since)
    if not result["pending_exists"]:
        advance_digest_cursor(
            db,
            project.id,
            sync_completed_at or datetime.now(timezone.utc),
        )
    return result
