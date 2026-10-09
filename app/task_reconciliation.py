"""Read-only, evidence-based hints for reviewing potentially stale GitHub CI tasks.

No task, SessionDelta, event, or project record is mutated here. A later green
workflow run is only a *review signal*: it never authorizes automatic closure.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Event, Project, Task

CI_TASK_TITLE = "investigar novas falhas de ci"
FAILURE_CONCLUSIONS = frozenset(
    {"failure", "cancelled", "timed_out", "action_required", "startup_failure"}
)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _source_event_id(source_ref: str | None) -> UUID | None:
    if not source_ref or not source_ref.startswith("event:"):
        return None
    try:
        return UUID(source_ref.removeprefix("event:"))
    except ValueError:
        return None


def _workflow_identity(event: Event) -> tuple[str, str, str] | None:
    """Identify the same repo, workflow name and branch, or refuse to infer."""
    if event.event_type != "github.workflow_run" or event.source_type != "github":
        return None
    metadata = event.metadata_json or {}
    repo = str(metadata.get("repository") or "").strip()
    branch = str(metadata.get("head_branch") or "").strip()
    title = event.title or ""
    if not title.startswith("Action ") or ": " not in title:
        return None
    workflow = title.removeprefix("Action ").rsplit(": ", 1)[0].strip()
    if not repo or not branch or not workflow:
        return None
    return repo, workflow, branch


def collect_ci_reconciliation_hints(
    db: Session, *, project_slug: str | None = None
) -> dict:
    """Return only corroborated candidate review hints; never write to the DB."""
    projects = list(
        db.scalars(
            select(Project)
            .where(Project.slug == project_slug if project_slug else True)
            .order_by(Project.slug)
        ).all()
    )
    report: dict = {
        "mode": "check",
        "message": "Consulta somente leitura. Ausência de sugestão não significa ausência de pendências.",
        "project_count": len(projects),
        "open_tasks_examined": 0,
        "ci_tasks_examined": 0,
        "diagnostics": [],
        "suggestions": [],
        "changes_applied": 0,
    }

    for project in projects:
        tasks = list(
            db.scalars(
                select(Task).where(
                    Task.project_id == project.id,
                    Task.status.notin_(("done", "cancelled")),
                )
            ).all()
        )
        report["open_tasks_examined"] += len(tasks)
        ci_tasks = [
            task for task in tasks if task.title.strip().casefold() == CI_TASK_TITLE
        ]
        report["ci_tasks_examined"] += len(ci_tasks)
        if not ci_tasks:
            report["diagnostics"].append({"project_slug": project.slug, "classification": "no_matching_task", "reason": "Nenhuma tarefa aberta de investigação de falhas de CI foi encontrada."})
            continue

        runs = list(
            db.scalars(
                select(Event).where(
                    Event.project_id == project.id,
                    Event.source_type == "github",
                    Event.event_type == "github.workflow_run",
                )
            ).all()
        )
        latest: dict[tuple[str, str, str], Event] = {}
        for run in runs:
            identity = _workflow_identity(run)
            if identity is None:
                continue
            previous = latest.get(identity)
            if previous is None or (_aware(run.occurred_at), str(run.id)) > (
                _aware(previous.occurred_at), str(previous.id)
            ):
                latest[identity] = run

        for task in ci_tasks:
            event_id = _source_event_id(task.source_ref)
            if event_id is None:
                report["diagnostics"].append({"project_slug": project.slug, "task_id": str(task.id), "classification": "insufficient_evidence", "reason": "Tarefa sem referência de evento GitHub válida."})
                continue
            failure = next((run for run in runs if run.id == event_id), None)
            if failure is None:
                report["diagnostics"].append({"project_slug": project.slug, "task_id": str(task.id), "classification": "insufficient_evidence", "reason": "Evento de origem não está disponível no histórico sincronizado."})
                continue
            identity = _workflow_identity(failure)
            if identity is None:
                report["diagnostics"].append({"project_slug": project.slug, "task_id": str(task.id), "classification": "insufficient_evidence", "reason": "Workflow, repositório ou branch de origem não identificável."})
                continue
            failure_conclusion = str(
                (failure.metadata_json or {}).get("conclusion") or ""
            ).lower()
            if failure_conclusion not in FAILURE_CONCLUSIONS:
                continue
            last = latest.get(identity)
            if last is None or last.id == failure.id:
                continue
            if _aware(last.occurred_at) <= _aware(failure.occurred_at):
                continue
            if str((last.metadata_json or {}).get("conclusion") or "").lower() != "success":
                continue
            if str((last.metadata_json or {}).get("status") or "").lower() != "completed":
                continue
            # Missing URLs must never produce a corroborated review suggestion.
            if not failure.url or not last.url:
                continue

            report["suggestions"].append(
                {
                    "project_slug": project.slug,
                    "task_id": str(task.id),
                    "task_title": task.title,
                    "recommendation": "review_possible_ci_resolution",
                    "workflow": identity[1],
                    "branch": identity[2],
                    "repository": identity[0],
                    "failure_run_url": failure.url,
                    "failure_at": _aware(failure.occurred_at).isoformat(),
                    "success_run_url": last.url,
                    "success_at": _aware(last.occurred_at).isoformat(),
                    "caution": (
                        "Uma execução posterior aprovada no mesmo workflow e branch "
                        "é apenas um indício para revisão. Confirme o escopo e os jobs "
                        "antes de encerrar a tarefa manualmente."
                    ),
                }
            )

    report["suggestion_count"] = len(report["suggestions"])
    report["diagnostic_count"] = len(report["diagnostics"])
    return report
