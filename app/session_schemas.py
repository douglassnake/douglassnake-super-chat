from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ProposedDecision(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1)
    rationale: str | None = None
    source_ref: str | None = None


class ProposedTask(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    priority: int = 0
    due_at: datetime | None = None
    blocked_by: str | None = None
    source_ref: str | None = None


class SessionDeltaCreate(BaseModel):
    session_key: str = Field(min_length=1, max_length=255)
    summary: str = Field(min_length=1)
    decisions: list[ProposedDecision] = Field(default_factory=list, max_length=50)
    tasks: list[ProposedTask] = Field(default_factory=list, max_length=100)
    close_task_ids: list[UUID] = Field(default_factory=list, max_length=100)
    status_change: str | None = Field(default=None, max_length=80)
    next_action: str | None = None
    source_refs: list[str] = Field(default_factory=list, max_length=100)
    started_at: datetime | None = None
    ended_at: datetime | None = None

    @model_validator(mode="after")
    def validate_time_range(self):
        if self.started_at and self.ended_at and self.ended_at < self.started_at:
            raise ValueError("ended_at must be greater than or equal to started_at")
        return self


SessionDeltaStatus = Literal["pending", "applied", "discarded"]


class SessionDeltaRead(ORMModel):
    id: UUID
    project_id: UUID
    session_key: str
    status: SessionDeltaStatus
    summary: str
    decisions_json: list[dict]
    tasks_json: list[dict]
    close_task_ids_json: list[str]
    status_change: str | None
    next_action: str | None
    source_refs_json: list[str]
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime
    applied_at: datetime | None
    discarded_at: datetime | None


class SessionDeltaPreview(BaseModel):
    delta: SessionDeltaRead
    effects: dict


class SessionDeltaApplyResult(BaseModel):
    delta: SessionDeltaRead
    created_summary_id: UUID
    created_decision_ids: list[UUID]
    created_task_ids: list[UUID]
    closed_task_ids: list[UUID]
    project_status: str
    project_next_action: str | None
