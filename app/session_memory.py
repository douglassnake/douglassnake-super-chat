from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Decision, Project, SessionDelta, SessionSummary, Task, utcnow
from app.session_schemas import SessionDeltaCreate


class SessionDeltaError(RuntimeError):
    pass


class SessionDeltaConflict(SessionDeltaError):
    pass


class SessionDeltaInvalid(SessionDeltaError):
    pass


def create_session_delta(db: Session, project: Project, payload: SessionDeltaCreate) -> SessionDelta:
    data = payload.model_dump(mode="json")
    delta = SessionDelta(
        project_id=project.id,
        session_key=data["session_key"],
        status="pending",
        summary=data["summary"],
        decisions_json=data["decisions"],
        tasks_json=data["tasks"],
        close_task_ids_json=data["close_task_ids"],
        status_change=data["status_change"],
        next_action=data["next_action"],
        source_refs_json=data["source_refs"],
        started_at=payload.started_at,
        ended_at=payload.ended_at,
    )
    db.add(delta)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise SessionDeltaConflict("session_key already exists for this project") from exc
    db.refresh(delta)
    return delta


def get_delta_or_raise(db: Session, delta_id: UUID) -> SessionDelta:
    delta = db.get(SessionDelta, delta_id)
    if delta is None:
        raise SessionDeltaInvalid("Session delta not found")
    return delta


def preview_session_delta(db: Session, delta: SessionDelta) -> dict:
    close_ids = [UUID(value) for value in (delta.close_task_ids_json or [])]
    close_tasks: list[Task] = []
    if close_ids:
        stmt = select(Task).where(Task.id.in_(close_ids), Task.project_id == delta.project_id)
        close_tasks = list(db.scalars(stmt).all())

    found_ids = {task.id for task in close_tasks}
    missing_ids = [str(task_id) for task_id in close_ids if task_id not in found_ids]

    return {
        "status": delta.status,
        "will_create_summary": True,
        "decisions_to_create": len(delta.decisions_json or []),
        "tasks_to_create": len(delta.tasks_json or []),
        "tasks_to_close": [
            {"id": str(task.id), "title": task.title, "current_status": task.status}
            for task in close_tasks
        ],
        "missing_or_foreign_task_ids": missing_ids,
        "status_change": delta.status_change,
        "next_action": delta.next_action,
        "source_refs": delta.source_refs_json or [],
    }


def apply_session_delta(db: Session, delta: SessionDelta) -> dict:
    if delta.status != "pending":
        raise SessionDeltaConflict(f"Session delta is {delta.status}, not pending")

    project = db.get(Project, delta.project_id)
    if project is None:
        raise SessionDeltaInvalid("Project not found")

    close_ids = [UUID(value) for value in (delta.close_task_ids_json or [])]
    tasks_to_close: list[Task] = []
    if close_ids:
        stmt = select(Task).where(Task.id.in_(close_ids), Task.project_id == project.id)
        tasks_to_close = list(db.scalars(stmt).all())
        found_ids = {task.id for task in tasks_to_close}
        missing_ids = [task_id for task_id in close_ids if task_id not in found_ids]
        if missing_ids:
            raise SessionDeltaInvalid(
                "Tasks to close must exist and belong to the project: "
                + ", ".join(str(value) for value in missing_ids)
            )

    now = datetime.now(timezone.utc)
    fallback_ref = f"session_delta:{delta.id}"
    source_refs = delta.source_refs_json or []
    summary_source_ref = source_refs[0] if source_refs else fallback_ref

    summary = SessionSummary(
        project_id=project.id,
        session_key=delta.session_key,
        summary=delta.summary,
        next_action=delta.next_action,
        source_ref=summary_source_ref,
        started_at=delta.started_at,
        ended_at=delta.ended_at,
    )
    db.add(summary)

    decisions: list[Decision] = []
    for proposed in delta.decisions_json or []:
        decision = Decision(
            project_id=project.id,
            title=proposed["title"],
            body=proposed["body"],
            rationale=proposed.get("rationale"),
            status="active",
            decided_at=now,
            source_ref=proposed.get("source_ref") or fallback_ref,
        )
        db.add(decision)
        decisions.append(decision)

    created_tasks: list[Task] = []
    for proposed in delta.tasks_json or []:
        due_at_value = proposed.get("due_at")
        due_at = datetime.fromisoformat(due_at_value) if due_at_value else None
        task = Task(
            project_id=project.id,
            title=proposed["title"],
            description=proposed.get("description"),
            status="todo",
            priority=proposed.get("priority", 0),
            due_at=due_at,
            blocked_by=proposed.get("blocked_by"),
            source_ref=proposed.get("source_ref") or fallback_ref,
        )
        db.add(task)
        created_tasks.append(task)

    for task in tasks_to_close:
        task.status = "done"
        task.updated_at = now

    if delta.status_change is not None:
        project.status = delta.status_change
    if delta.next_action is not None:
        project.next_action = delta.next_action
    project.last_activity_at = now
    project.updated_at = now

    delta.status = "applied"
    delta.applied_at = now

    try:
        db.flush()
        result = {
            "created_summary_id": summary.id,
            "created_decision_ids": [item.id for item in decisions],
            "created_task_ids": [item.id for item in created_tasks],
            "closed_task_ids": [item.id for item in tasks_to_close],
            "project_status": project.status,
            "project_next_action": project.next_action,
        }
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(delta)
    return result


def discard_session_delta(db: Session, delta: SessionDelta) -> SessionDelta:
    if delta.status != "pending":
        raise SessionDeltaConflict(f"Session delta is {delta.status}, not pending")
    delta.status = "discarded"
    delta.discarded_at = utcnow()
    db.commit()
    db.refresh(delta)
    return delta
