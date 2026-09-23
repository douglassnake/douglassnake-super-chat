from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ProjectCreate(BaseModel):
    slug: str = Field(min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    status: str = "active"
    priority: int = 0
    next_action: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    status: str | None = None
    priority: int | None = None
    next_action: str | None = None
    last_activity_at: datetime | None = None


class ProjectRead(ORMModel):
    id: UUID
    slug: str
    name: str
    description: str | None
    status: str
    priority: int
    next_action: str | None
    last_activity_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DecisionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1)
    rationale: str | None = None
    status: str = "active"
    decided_at: datetime | None = None
    source_ref: str | None = None


class DecisionRead(ORMModel):
    id: UUID
    project_id: UUID | None
    title: str
    body: str
    rationale: str | None
    status: str
    decided_at: datetime
    source_ref: str | None
    created_at: datetime


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    status: str = "todo"
    priority: int = 0
    due_at: datetime | None = None
    blocked_by: str | None = None
    source_ref: str | None = None


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    status: str | None = None
    priority: int | None = None
    due_at: datetime | None = None
    blocked_by: str | None = None
    source_ref: str | None = None


class TaskRead(ORMModel):
    id: UUID
    project_id: UUID | None
    title: str
    description: str | None
    status: str
    priority: int
    due_at: datetime | None
    blocked_by: str | None
    source_ref: str | None
    created_at: datetime
    updated_at: datetime


class SessionSummaryCreate(BaseModel):
    session_key: str | None = None
    summary: str = Field(min_length=1)
    next_action: str | None = None
    source_ref: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None


class SessionSummaryRead(ORMModel):
    id: UUID
    project_id: UUID | None
    session_key: str | None
    summary: str
    next_action: str | None
    source_ref: str | None
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime


class ProjectSnapshot(BaseModel):
    project: ProjectRead
    summary: SessionSummaryRead | None
    decisions: list[DecisionRead]
    open_tasks: list[TaskRead]
    generated_at: datetime
