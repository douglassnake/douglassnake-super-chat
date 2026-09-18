from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.context_engine import build_context_package
from app.database import get_db
from app.github_sync import GitHubAPIError, sync_project_github
from app.models import ContextItem, Decision, Project, ProjectSource, SessionSummary, Task, utcnow
from app.schemas import (
    ContextBuildRequest,
    ContextItemCreate,
    ContextItemRead,
    ContextPackage,
    ContextProfile,
    DecisionCreate,
    DecisionRead,
    GitHubSyncResult,
    ProjectCreate,
    ProjectRead,
    ProjectSnapshot,
    ProjectSourceCreate,
    ProjectSourceRead,
    ProjectUpdate,
    SessionSummaryCreate,
    SessionSummaryRead,
    TaskCreate,
    TaskRead,
    TaskUpdate,
)

router = APIRouter()


def get_project_or_404(db: Session, project_id: UUID) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.post("/projects", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)) -> Project:
    project = Project(**payload.model_dump())
    db.add(project)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Project slug already exists") from exc
    db.refresh(project)
    return project


@router.get("/projects", response_model=list[ProjectRead])
def list_projects(
    project_status: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
) -> list[Project]:
    stmt = select(Project)
    if project_status:
        stmt = stmt.where(Project.status == project_status)
    stmt = stmt.order_by(Project.priority.desc(), Project.updated_at.desc())
    return list(db.scalars(stmt).all())


@router.get("/projects/{project_id}", response_model=ProjectRead)
def get_project(project_id: UUID, db: Session = Depends(get_db)) -> Project:
    return get_project_or_404(db, project_id)


@router.patch("/projects/{project_id}", response_model=ProjectRead)
def update_project(project_id: UUID, payload: ProjectUpdate, db: Session = Depends(get_db)) -> Project:
    project = get_project_or_404(db, project_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(project, field, value)
    project.updated_at = utcnow()
    db.commit()
    db.refresh(project)
    return project


@router.post(
    "/projects/{project_id}/sources",
    response_model=ProjectSourceRead,
    status_code=status.HTTP_201_CREATED,
)
def create_project_source(
    project_id: UUID,
    payload: ProjectSourceCreate,
    db: Session = Depends(get_db),
) -> ProjectSource:
    project = get_project_or_404(db, project_id)
    if payload.source_type == "github":
        repository = (payload.external_id or "").strip().strip("/")
        if not repository or "/" not in repository:
            raise HTTPException(status_code=422, detail="GitHub external_id must be owner/repository")

    existing_stmt = select(ProjectSource.id).where(
        ProjectSource.project_id == project_id,
        ProjectSource.source_type == payload.source_type,
        ProjectSource.external_id == payload.external_id,
    )
    if db.scalar(existing_stmt) is not None:
        raise HTTPException(status_code=409, detail="Project source already exists")

    source = ProjectSource(project_id=project_id, **payload.model_dump())
    project.last_activity_at = utcnow()
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


@router.get("/projects/{project_id}/sources", response_model=list[ProjectSourceRead])
def list_project_sources(project_id: UUID, db: Session = Depends(get_db)) -> list[ProjectSource]:
    get_project_or_404(db, project_id)
    stmt = (
        select(ProjectSource)
        .where(ProjectSource.project_id == project_id)
        .order_by(ProjectSource.source_type.asc(), ProjectSource.label.asc())
    )
    return list(db.scalars(stmt).all())


@router.post(
    "/projects/{project_id}/decisions",
    response_model=DecisionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_decision(project_id: UUID, payload: DecisionCreate, db: Session = Depends(get_db)) -> Decision:
    project = get_project_or_404(db, project_id)
    data = payload.model_dump(exclude={"decided_at"})
    decision = Decision(
        project_id=project_id,
        decided_at=payload.decided_at or utcnow(),
        **data,
    )
    project.last_activity_at = utcnow()
    db.add(decision)
    db.commit()
    db.refresh(decision)
    return decision


@router.get("/projects/{project_id}/decisions", response_model=list[DecisionRead])
def list_decisions(project_id: UUID, db: Session = Depends(get_db)) -> list[Decision]:
    get_project_or_404(db, project_id)
    stmt = (
        select(Decision)
        .where(Decision.project_id == project_id)
        .order_by(Decision.decided_at.desc())
    )
    return list(db.scalars(stmt).all())


@router.post(
    "/projects/{project_id}/tasks",
    response_model=TaskRead,
    status_code=status.HTTP_201_CREATED,
)
def create_task(project_id: UUID, payload: TaskCreate, db: Session = Depends(get_db)) -> Task:
    project = get_project_or_404(db, project_id)
    task = Task(project_id=project_id, **payload.model_dump())
    project.last_activity_at = utcnow()
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@router.get("/projects/{project_id}/tasks", response_model=list[TaskRead])
def list_tasks(
    project_id: UUID,
    task_status: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
) -> list[Task]:
    get_project_or_404(db, project_id)
    stmt = select(Task).where(Task.project_id == project_id)
    if task_status:
        stmt = stmt.where(Task.status == task_status)
    stmt = stmt.order_by(Task.priority.desc(), Task.created_at.desc())
    return list(db.scalars(stmt).all())


@router.patch("/tasks/{task_id}", response_model=TaskRead)
def update_task(task_id: UUID, payload: TaskUpdate, db: Session = Depends(get_db)) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(task, field, value)
    task.updated_at = utcnow()
    if task.project_id:
        project = db.get(Project, task.project_id)
        if project:
            project.last_activity_at = utcnow()
    db.commit()
    db.refresh(task)
    return task


@router.post(
    "/projects/{project_id}/summaries",
    response_model=SessionSummaryRead,
    status_code=status.HTTP_201_CREATED,
)
def create_summary(
    project_id: UUID,
    payload: SessionSummaryCreate,
    db: Session = Depends(get_db),
) -> SessionSummary:
    project = get_project_or_404(db, project_id)
    summary = SessionSummary(project_id=project_id, **payload.model_dump())
    project.last_activity_at = utcnow()
    if payload.next_action is not None:
        project.next_action = payload.next_action
    db.add(summary)
    db.commit()
    db.refresh(summary)
    return summary


@router.get("/projects/{project_id}/snapshot", response_model=ProjectSnapshot)
def get_project_snapshot(project_id: UUID, db: Session = Depends(get_db)) -> ProjectSnapshot:
    project = get_project_or_404(db, project_id)

    summary_stmt = (
        select(SessionSummary)
        .where(SessionSummary.project_id == project_id)
        .order_by(SessionSummary.created_at.desc())
        .limit(1)
    )
    latest_summary = db.scalars(summary_stmt).first()

    decisions_stmt = (
        select(Decision)
        .where(Decision.project_id == project_id, Decision.status == "active")
        .order_by(Decision.decided_at.desc())
        .limit(10)
    )
    decisions = list(db.scalars(decisions_stmt).all())

    tasks_stmt = (
        select(Task)
        .where(
            Task.project_id == project_id,
            Task.status.notin_(["done", "cancelled"]),
        )
        .order_by(Task.priority.desc(), Task.created_at.desc())
    )
    open_tasks = list(db.scalars(tasks_stmt).all())

    return ProjectSnapshot(
        project=ProjectRead.model_validate(project),
        summary=SessionSummaryRead.model_validate(latest_summary) if latest_summary else None,
        decisions=[DecisionRead.model_validate(item) for item in decisions],
        open_tasks=[TaskRead.model_validate(item) for item in open_tasks],
        generated_at=datetime.now(timezone.utc),
    )


@router.post(
    "/projects/{project_id}/context-items",
    response_model=ContextItemRead,
    status_code=status.HTTP_201_CREATED,
)
def create_context_item(
    project_id: UUID,
    payload: ContextItemCreate,
    db: Session = Depends(get_db),
) -> ContextItem:
    project = get_project_or_404(db, project_id)
    item = ContextItem(project_id=project_id, **payload.model_dump())
    project.last_activity_at = utcnow()
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/projects/{project_id}/context-items", response_model=list[ContextItemRead])
def list_context_items(project_id: UUID, db: Session = Depends(get_db)) -> list[ContextItem]:
    get_project_or_404(db, project_id)
    stmt = (
        select(ContextItem)
        .where(ContextItem.project_id == project_id)
        .order_by(ContextItem.importance.desc(), ContextItem.updated_at.desc())
    )
    return list(db.scalars(stmt).all())


@router.post("/context/build", response_model=ContextPackage)
def build_context(payload: ContextBuildRequest, db: Session = Depends(get_db)) -> dict:
    project = get_project_or_404(db, payload.project_id)
    return build_context_package(db, project, payload.query, payload.profile)


@router.get("/projects/{project_id}/continue", response_model=ContextPackage)
def continue_project(
    project_id: UUID,
    profile: ContextProfile = Query(default="standard"),
    query: str = Query(
        default="continuar projeto status próxima ação decisões tarefas pendências bloqueios commits PR issues actions",
        max_length=4000,
    ),
    db: Session = Depends(get_db),
) -> dict:
    project = get_project_or_404(db, project_id)
    return build_context_package(db, project, query, profile)


@router.post("/projects/{project_id}/github/sync", response_model=GitHubSyncResult)
def sync_github(project_id: UUID, db: Session = Depends(get_db)) -> dict:
    project = get_project_or_404(db, project_id)
    source_stmt = select(ProjectSource.id).where(
        ProjectSource.project_id == project_id,
        ProjectSource.source_type == "github",
        ProjectSource.is_active.is_(True),
    )
    if db.scalar(source_stmt) is None:
        raise HTTPException(status_code=400, detail="Project has no active GitHub source")
    try:
        return sync_project_github(db, project)
    except GitHubAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
