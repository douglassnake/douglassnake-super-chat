from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.github_sync import GitHubReader, sync_project_github
from app.models import Event, Project, ProjectSource, SessionDelta
from app.session_memory import SessionDeltaConflict, create_session_delta
from app.session_schemas import ProposedDecision, ProposedTask, SessionDeltaCreate


class GitHubOnboardingError(RuntimeError):
    pass


class GitHubOnboardingConflict(GitHubOnboardingError):
    pass


def _active_sources(db: Session, project_id: UUID) -> list[ProjectSource]:
    stmt = select(ProjectSource).where(
        ProjectSource.project_id == project_id,
        ProjectSource.source_type == "github",
        ProjectSource.is_active.is_(True),
    )
    return list(db.scalars(stmt).all())


def _recent_failed_runs(db: Session, project_id: UUID, *, now: datetime) -> int:
    since = now - timedelta(days=7)
    stmt = select(Event).where(
        Event.project_id == project_id,
        Event.source_type == "github",
        Event.event_type == "github.workflow_run",
        Event.occurred_at >= since,
    )
    events = list(db.scalars(stmt).all())
    return sum(
        1
        for event in events
        if str((event.metadata_json or {}).get("conclusion") or "").lower()
        in {"failure", "cancelled", "timed_out"}
    )


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

    sync_result = sync_project_github(db, project, reader=reader)
    now = datetime.now(timezone.utc)
    failed_runs = _recent_failed_runs(db, project.id, now=now)

    repositories: list[str] = []
    total_issues = 0
    total_pulls = 0
    total_runs = 0
    default_branches: list[str] = []
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
        branch = metadata.get("default_branch")
        if branch:
            default_branches.append(str(branch))

    repo_label = ", ".join(repositories)
    branch_label = ", ".join(sorted(set(default_branches))) or "não identificada"
    summary = (
        f"Onboarding GitHub preparado para {repo_label}. "
        f"Branch principal: {branch_label}. "
        f"Estado atual sincronizado: {total_issues} issue(s) aberta(s), "
        f"{total_pulls} PR(s) aberto(s), {total_runs} workflow run(s) recente(s) "
        f"e {failed_runs} falha(s) de CI nos últimos 7 dias. "
        "As sugestões abaixo só serão incorporadas à memória após revisão e aplicação manual."
    )

    decisions = [
        ProposedDecision(
            title="Usar o repositório GitHub vinculado como fonte técnica principal",
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
    ]

    tasks: list[ProposedTask] = []
    if failed_runs:
        tasks.append(
            ProposedTask(
                title="Investigar falhas recentes de CI",
                description=(
                    f"Há {failed_runs} execução(ões) recente(s) com failure, cancelled ou timed_out. "
                    "Revisar os workflows antes de considerar o estado técnico estável."
                ),
                priority=90,
                source_ref=source_refs[0],
            )
        )
    if total_issues:
        tasks.append(
            ProposedTask(
                title="Revisar issues abertas importadas do GitHub",
                description=f"Triar {total_issues} issue(s) aberta(s) e incorporar apenas as que forem relevantes ao plano do projeto.",
                priority=75,
                source_ref=source_refs[0],
            )
        )
    if total_pulls:
        tasks.append(
            ProposedTask(
                title="Revisar pull requests abertos",
                description=f"Avaliar {total_pulls} PR(s) aberto(s), riscos, dependências e próximos passos.",
                priority=70,
                source_ref=source_refs[0],
            )
        )
    if not tasks:
        tasks.append(
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
        next_action=tasks[0].title,
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
    }
