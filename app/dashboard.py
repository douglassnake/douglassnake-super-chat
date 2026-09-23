from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import Event, Project, ProjectSource, SessionDelta, Task


def ensure_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def calculate_health_score(
    project: Project,
    *,
    open_tasks: int,
    overdue_tasks: int,
    blocked_tasks: int,
    pending_deltas: int,
    recent_failed_runs: int,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(timezone.utc)
    score = 100
    reasons: list[dict[str, int | str]] = []

    def penalize(points: int, code: str, label: str) -> None:
        nonlocal score
        if points <= 0:
            return
        score -= points
        reasons.append({"code": code, "label": label, "impact": -points})

    if not (project.next_action or "").strip():
        penalize(20, "missing_next_action", "Projeto sem próxima ação definida")

    if overdue_tasks:
        penalize(min(24, overdue_tasks * 8), "overdue_tasks", f"{overdue_tasks} tarefa(s) vencida(s)")

    if blocked_tasks:
        penalize(min(24, blocked_tasks * 8), "blocked_tasks", f"{blocked_tasks} tarefa(s) bloqueada(s)")

    activity_at = ensure_aware(project.last_activity_at or project.updated_at)
    if activity_at:
        inactivity_days = max(0, (now - activity_at).days)
        if inactivity_days > 30:
            penalize(25, "inactive_30d", f"Sem atividade há {inactivity_days} dias")
        elif inactivity_days > 14:
            penalize(15, "inactive_14d", f"Sem atividade há {inactivity_days} dias")
        elif inactivity_days > 7:
            penalize(5, "inactive_7d", f"Sem atividade há {inactivity_days} dias")
    else:
        inactivity_days = None
        penalize(15, "unknown_activity", "Sem registro de atividade")

    if pending_deltas:
        penalize(min(15, pending_deltas * 5), "pending_deltas", f"{pending_deltas} SessionDelta(s) aguardando revisão")

    if recent_failed_runs:
        penalize(min(20, recent_failed_runs * 10), "failed_ci", f"{recent_failed_runs} execução(ões) recente(s) de CI com falha")

    score = max(0, min(100, score))
    if score >= 85:
        level = "healthy"
    elif score >= 65:
        level = "attention"
    elif score >= 40:
        level = "risk"
    else:
        level = "critical"

    return {
        "score": score,
        "level": level,
        "reasons": reasons,
        "metrics": {
            "open_tasks": open_tasks,
            "overdue_tasks": overdue_tasks,
            "blocked_tasks": blocked_tasks,
            "pending_deltas": pending_deltas,
            "recent_failed_runs": recent_failed_runs,
            "inactivity_days": inactivity_days,
        },
    }


def project_metrics(db: Session, project: Project, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)

    open_tasks = int(
        db.scalar(
            select(func.count(Task.id)).where(
                Task.project_id == project.id,
                Task.status.notin_(["done", "cancelled"]),
            )
        )
        or 0
    )
    overdue_tasks = int(
        db.scalar(
            select(func.count(Task.id)).where(
                Task.project_id == project.id,
                Task.status.notin_(["done", "cancelled"]),
                Task.due_at.is_not(None),
                Task.due_at < now,
            )
        )
        or 0
    )
    blocked_tasks = int(
        db.scalar(
            select(func.count(Task.id)).where(
                Task.project_id == project.id,
                Task.status.notin_(["done", "cancelled"]),
                or_(Task.status == "blocked", Task.blocked_by.is_not(None)),
            )
        )
        or 0
    )
    pending_deltas = int(
        db.scalar(
            select(func.count(SessionDelta.id)).where(
                SessionDelta.project_id == project.id,
                SessionDelta.status == "pending",
            )
        )
        or 0
    )

    failed_since = now - timedelta(days=7)
    recent_workflows = list(
        db.scalars(
            select(Event).where(
                Event.project_id == project.id,
                Event.event_type == "github.workflow_run",
                Event.occurred_at >= failed_since,
            )
        ).all()
    )
    recent_failed_runs = sum(
        1
        for event in recent_workflows
        if str((event.metadata_json or {}).get("conclusion") or "").lower()
        in {"failure", "cancelled", "timed_out"}
    )

    return calculate_health_score(
        project,
        open_tasks=open_tasks,
        overdue_tasks=overdue_tasks,
        blocked_tasks=blocked_tasks,
        pending_deltas=pending_deltas,
        recent_failed_runs=recent_failed_runs,
        now=now,
    )


def dashboard_payload(db: Session) -> dict:
    projects = list(db.scalars(select(Project).order_by(Project.priority.desc(), Project.updated_at.desc())).all())
    items: list[dict] = []
    for project in projects:
        health = project_metrics(db, project)
        source_count = int(
            db.scalar(
                select(func.count(ProjectSource.id)).where(
                    ProjectSource.project_id == project.id,
                    ProjectSource.is_active.is_(True),
                )
            )
            or 0
        )
        items.append(
            {
                "id": project.id,
                "slug": project.slug,
                "name": project.name,
                "status": project.status,
                "priority": project.priority,
                "next_action": project.next_action,
                "last_activity_at": project.last_activity_at,
                "updated_at": project.updated_at,
                "active_sources": source_count,
                "health": health,
            }
        )

    return {
        "generated_at": datetime.now(timezone.utc),
        "project_count": len(items),
        "attention_count": sum(1 for item in items if item["health"]["score"] < 85),
        "pending_delta_count": sum(item["health"]["metrics"]["pending_deltas"] for item in items),
        "projects": items,
    }


def project_overview(db: Session, project_id: UUID) -> dict | None:
    project = db.get(Project, project_id)
    if project is None:
        return None

    tasks = list(
        db.scalars(
            select(Task)
            .where(Task.project_id == project.id, Task.status.notin_(["done", "cancelled"]))
            .order_by(Task.priority.desc(), Task.created_at.desc())
            .limit(25)
        ).all()
    )
    sources = list(
        db.scalars(
            select(ProjectSource)
            .where(ProjectSource.project_id == project.id)
            .order_by(ProjectSource.source_type.asc(), ProjectSource.label.asc())
        ).all()
    )
    events = list(
        db.scalars(
            select(Event)
            .where(Event.project_id == project.id)
            .order_by(Event.occurred_at.desc())
            .limit(20)
        ).all()
    )
    pending_deltas = list(
        db.scalars(
            select(SessionDelta)
            .where(SessionDelta.project_id == project.id, SessionDelta.status == "pending")
            .order_by(SessionDelta.created_at.desc())
            .limit(20)
        ).all()
    )

    return {
        "project": {
            "id": project.id,
            "slug": project.slug,
            "name": project.name,
            "description": project.description,
            "status": project.status,
            "priority": project.priority,
            "next_action": project.next_action,
            "last_activity_at": project.last_activity_at,
            "updated_at": project.updated_at,
        },
        "health": project_metrics(db, project),
        "tasks": [
            {
                "id": task.id,
                "title": task.title,
                "status": task.status,
                "priority": task.priority,
                "due_at": task.due_at,
                "blocked_by": task.blocked_by,
            }
            for task in tasks
        ],
        "sources": [
            {
                "id": source.id,
                "source_type": source.source_type,
                "external_id": source.external_id,
                "label": source.label,
                "url": source.url,
                "is_active": source.is_active,
                "metadata": source.metadata_json,
            }
            for source in sources
        ],
        "events": [
            {
                "id": event.id,
                "source_type": event.source_type,
                "event_type": event.event_type,
                "title": event.title,
                "occurred_at": event.occurred_at,
                "url": event.url,
                "metadata": event.metadata_json,
            }
            for event in events
        ],
        "pending_deltas": [
            {
                "id": delta.id,
                "session_key": delta.session_key,
                "summary": delta.summary,
                "status_change": delta.status_change,
                "next_action": delta.next_action,
                "created_at": delta.created_at,
            }
            for delta in pending_deltas
        ],
    }
