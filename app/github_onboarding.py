from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.github_sync import GitHubReader, sync_project_github
from app.models import Decision, Event, Project, ProjectSource, SessionDelta, Task
from app.session_memory import SessionDeltaConflict, create_session_delta
from app.session_schemas import ProposedDecision, ProposedTask, SessionDeltaCreate


class GitHubOnboardingError(RuntimeError):
    pass


class GitHubOnboardingConflict(GitHubOnboardingError):
    pass


FAILURE_CONCLUSIONS = {"failure", "cancelled", "timed_out", "action_required", "startup_failure"}


def _active_sources(db: Session, project_id: UUID) -> list[ProjectSource]:
    stmt = select(ProjectSource).where(
        ProjectSource.project_id == project_id,
        ProjectSource.source_type == "github",
        ProjectSource.is_active.is_(True),
    )
    return list(db.scalars(stmt).all())


def _workflow_name(event: Event) -> str:
    metadata = event.metadata_json or {}
    explicit = str(metadata.get("workflow") or "").strip()
    if explicit:
        return explicit
    title = event.title or "workflow"
    if title.startswith("Action "):
        title = title.removeprefix("Action ")
    return title.rsplit(":", 1)[0].strip() or "workflow"


def _current_failed_workflows(
    db: Session,
    project_id: UUID,
    *,
    default_branch_by_repository: dict[str, str],
) -> list[Event]:
    """Return only workflows whose latest default-branch run is currently failing.

    Historical failures are intentionally ignored when a newer run for the same
    repository/workflow has already recovered.
    """
    stmt = (
        select(Event)
        .where(
            Event.project_id == project_id,
            Event.source_type == "github",
            Event.event_type == "github.workflow_run",
        )
        .order_by(Event.occurred_at.desc(), Event.created_at.desc())
    )
    latest: dict[tuple[str, str], Event] = {}
    for event in db.scalars(stmt).all():
        metadata = event.metadata_json or {}
        repository = str(metadata.get("repository") or "").strip()
        branch = str(metadata.get("head_branch") or "").strip()
        default_branch = default_branch_by_repository.get(repository)
        if default_branch and branch and branch != default_branch:
            continue
        key = (repository, _workflow_name(event))
        if key not in latest:
            latest[key] = event

    return [
        event
        for event in latest.values()
        if str((event.metadata_json or {}).get("conclusion") or "").lower() in FAILURE_CONCLUSIONS
    ]


def _existing_active_decision_titles(db: Session, project_id: UUID) -> set[str]:
    stmt = select(Decision.title).where(
        Decision.project_id == project_id,
        Decision.status == "active",
    )
    return {str(title).strip().casefold() for title in db.scalars(stmt).all() if title}


def _existing_open_task_titles(db: Session, project_id: UUID) -> set[str]:
    stmt = select(Task.title).where(
        Task.project_id == project_id,
        Task.status.notin_(["done", "cancelled"]),
    )
    return {str(title).strip().casefold() for title in db.scalars(stmt).all() if title}


def _ensure_no_pending_onboarding(db: Session, project_id: UUID) -> None:
    stmt = select(SessionDelta.id).where(
        SessionDelta.project_id == project_id,
        SessionDelta.status == "pending",
        SessionDelta.session_key.like("github-onboarding:%"),
    )
    if db.scalar(stmt) is not None:
        raise GitHubOnboardingConflict(
            "Já existe um onboarding GitHub pendente de revisão para este projeto"
        )


def prepare_github_onboarding(
    db: Session,
    project: Project,
    *,
    reader: GitHubReader | None = None,
) -> dict[str, Any]:
    sources = _active_sources(db, project.id)
    if not sources:
        raise GitHubOnboardingError("Project has no active GitHub source")

    _ensure_no_pending_onboarding(db, project.id)

    sync_result = sync_project_github(db, project, reader=reader, create_digest=False)
    now = datetime.now(timezone.utc)

    repositories: list[str] = []
    total_issues = 0
    total_pulls = 0
    total_runs = 0
    default_branches: list[str] = []
    default_branch_by_repository: dict[str, str] = {}
    source_refs: list[str] = []

    for source in sources:
        repository = (source.external_id or "").strip().strip("/")
        repositories.append(repository)
        source_refs.append(source.url or f"https://github.com/{repository}")
        metadata = source.metadata_json or {}
        last_sync = metadata.get("last_sync") or {}
        total_issues += int(last_sync.get("issues") or 0)
        total_pulls += int(last_sync.get("pulls") or 0)
        total_runs += int(last_sync.get("workflow_runs") or 0)
        branch = str(metadata.get("default_branch") or "").strip()
        if branch:
            default_branches.append(branch)
            default_branch_by_repository[repository] = branch

    failed_workflows = _current_failed_workflows(
        db,
        project.id,
        default_branch_by_repository=default_branch_by_repository,
    )
    failed_count = len(failed_workflows)

    repo_label = ", ".join(repositories)
    branch_label = ", ".join(sorted(set(default_branches))) or "não identificada"
    ci_label = (
        f"{failed_count} workflow(s) atualmente com falha na branch principal"
        if failed_count
        else "nenhum workflow atualmente com falha na branch principal"
    )
    summary = (
        f"Onboarding GitHub preparado para {repo_label}. "
        f"Branch principal: {branch_label}. "
        f"Estado atual sincronizado: {total_issues} issue(s) aberta(s), "
        f"{total_pulls} PR(s) aberto(s), {total_runs} workflow run(s) recente(s) e {ci_label}. "
        "Falhas históricas já recuperadas não geram tarefa. "
        "As sugestões abaixo só serão incorporadas à memória após revisão e aplicação manual."
    )

    existing_decisions = _existing_active_decision_titles(db, project.id)
    existing_tasks = _existing_open_task_titles(db, project.id)

    decisions: list[ProposedDecision] = []
    source_decision_title = "Usar o repositório GitHub vinculado como fonte técnica principal"
    if source_decision_title.casefold() not in existing_decisions:
        decisions.append(
            ProposedDecision(
                title=source_decision_title,
                body=(
                    f"Tratar {repo_label} como fonte técnica principal do projeto para "
                    "atividade de engenharia, commits, PRs, issues e CI."
                ),
                rationale=(
                    "O repositório foi vinculado explicitamente ao projeto e validado pela "
                    "sincronização inicial."
                ),
                source_ref=source_refs[0],
            )
        )

    tasks: list[ProposedTask] = []

    def add_task(task: ProposedTask) -> None:
        if task.title.strip().casefold() not in existing_tasks:
            tasks.append(task)

    if failed_count:
        evidence = ", ".join(
            f"{_workflow_name(event)} ({(event.metadata_json or {}).get('conclusion')})"
            for event in failed_workflows[:5]
        )
        add_task(
            ProposedTask(
                title="Investigar falhas atuais de CI",
                description=(
                    f"Há {failed_count} workflow(s) cujo run mais recente na branch principal está com falha. "
                    f"Evidência: {evidence}."
                ),
                priority=90,
                source_ref=source_refs[0],
            )
        )
    if total_issues:
        add_task(
            ProposedTask(
                title="Revisar issues abertas importadas do GitHub",
                description=f"Triar {total_issues} issue(s) aberta(s) e incorporar apenas as que forem relevantes ao plano do projeto.",
                priority=75,
                source_ref=source_refs[0],
            )
        )
    if total_pulls:
        add_task(
            ProposedTask(
                title="Revisar pull requests abertos",
                description=f"Avaliar {total_pulls} PR(s) aberto(s), riscos, dependências e próximos passos.",
                priority=70,
                source_ref=source_refs[0],
            )
        )
    if not tasks and not (total_issues or total_pulls or failed_count):
        add_task(
            ProposedTask(
                title="Revisar snapshot inicial importado do GitHub",
                description="Confirmar se o estado técnico sincronizado representa corretamente o ponto atual do projeto.",
                priority=60,
                source_ref=source_refs[0],
            )
        )

    payload = SessionDeltaCreate(
        session_key=f"github-onboarding:{now.strftime('%Y%m%dT%H%M%SZ')}:{uuid4().hex[:8]}",
        summary=summary,
        decisions=decisions,
        tasks=tasks,
        next_action=tasks[0].title if tasks else None,
        source_refs=source_refs,
        started_at=now,
        ended_at=now,
    )

    try:
        delta = create_session_delta(db, project, payload)
    except SessionDeltaConflict as exc:
        raise GitHubOnboardingConflict(str(exc)) from exc

    return {
        "project_id": project.id,
        "delta": delta,
        "sync": sync_result,
        "repositories": repositories,
        "suggested_decisions": len(decisions),
        "suggested_tasks": len(tasks),
        "requires_review": True,
        "current_failed_workflows": failed_count,
    }
