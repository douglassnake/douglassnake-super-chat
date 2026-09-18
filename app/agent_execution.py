from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent_handoff import sanitize_value
from app.agent_models import AgentExecution, AgentExecutionEvent, AgentTaskPack
from app.agent_task_pack import redact_secrets, sanitize_source_ref


TERMINAL_EXECUTION_STATES = {"completed", "failed", "cancelled"}


def sanitize_reference(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = redact_secrets(value)
    if not cleaned:
        return cleaned
    return sanitize_source_ref(cleaned)


def append_execution_event(
    db: Session,
    execution: AgentExecution,
    *,
    event_type: str,
    message: str | None = None,
    payload: dict[str, Any] | None = None,
    criterion_index: int | None = None,
    criterion_status: str | None = None,
) -> AgentExecutionEvent:
    execution.event_sequence += 1
    event = AgentExecutionEvent(
        execution_id=execution.id,
        sequence=execution.event_sequence,
        event_type=event_type,
        criterion_index=criterion_index,
        criterion_status=criterion_status,
        message=redact_secrets(message),
        payload_json=sanitize_value(payload or {}),
    )
    db.add(event)
    return event


def list_execution_events(db: Session, execution_id) -> list[AgentExecutionEvent]:
    stmt = (
        select(AgentExecutionEvent)
        .where(AgentExecutionEvent.execution_id == execution_id)
        .order_by(AgentExecutionEvent.sequence.asc())
    )
    return list(db.scalars(stmt).all())


def criteria_summary(
    db: Session,
    execution: AgentExecution,
    pack: AgentTaskPack,
) -> list[dict[str, Any]]:
    criteria = list(pack.acceptance_criteria_json or [])
    latest: dict[int, AgentExecutionEvent] = {}
    stmt = (
        select(AgentExecutionEvent)
        .where(
            AgentExecutionEvent.execution_id == execution.id,
            AgentExecutionEvent.event_type == "criterion_evidence",
        )
        .order_by(AgentExecutionEvent.sequence.asc())
    )
    for event in db.scalars(stmt).all():
        if event.criterion_index is not None:
            latest[event.criterion_index] = event

    result: list[dict[str, Any]] = []
    for index, criterion in enumerate(criteria):
        event = latest.get(index)
        payload = event.payload_json if event is not None else {}
        result.append(
            {
                "index": index,
                "criterion": criterion,
                "status": event.criterion_status if event is not None else "pending",
                "latest_event_id": str(event.id) if event is not None else None,
                "sequence": event.sequence if event is not None else None,
                "summary": payload.get("summary") if event is not None else None,
                "evidence_type": payload.get("evidence_type") if event is not None else None,
                "reference": payload.get("reference") if event is not None else None,
            }
        )
    return result


def completion_gate(summary: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(summary)
    passed = sum(1 for item in summary if item["status"] == "passed")
    failed = sum(1 for item in summary if item["status"] == "failed")
    pending = total - passed - failed
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "pending": pending,
        "complete_allowed": total > 0 and passed == total,
    }


def execution_payload(
    db: Session,
    execution: AgentExecution,
    pack: AgentTaskPack,
) -> dict[str, Any]:
    criteria = criteria_summary(db, execution, pack)
    return {
        "id": execution.id,
        "handoff_id": execution.handoff_id,
        "pack_id": execution.pack_id,
        "project_id": execution.project_id,
        "status": execution.status,
        "progress_percent": execution.progress_percent,
        "current_step": execution.current_step,
        "branch_ref": execution.branch_ref,
        "commit_sha": execution.commit_sha,
        "pr_url": execution.pr_url,
        "event_sequence": execution.event_sequence,
        "criteria": criteria,
        "criteria_coverage": completion_gate(criteria),
        "result": execution.result_json or {},
        "error": execution.error_text,
        "created_at": execution.created_at,
        "updated_at": execution.updated_at,
        "completed_at": execution.completed_at,
        "failed_at": execution.failed_at,
        "cancelled_at": execution.cancelled_at,
    }


def execution_event_payload(event: AgentExecutionEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "execution_id": event.execution_id,
        "sequence": event.sequence,
        "event_type": event.event_type,
        "criterion_index": event.criterion_index,
        "criterion_status": event.criterion_status,
        "message": event.message,
        "payload": event.payload_json or {},
        "created_at": event.created_at,
    }
