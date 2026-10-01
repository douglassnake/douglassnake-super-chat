from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


SemanticRelationType = Literal[
    "uses",
    "runs_on",
    "depends_on",
    "part_of",
    "created_from",
    "supports",
    "blocks",
    "implements",
    "decided_by",
    "related_to",
    "has_document",
    "mentions",
    "describes",
]


class KnowledgeEntityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: str
    canonical_key: str
    name: str
    description: str | None
    metadata_json: dict
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ProjectRelationCreate(BaseModel):
    entity_name: str = Field(min_length=1, max_length=255)
    entity_kind: str = Field(default="system", min_length=1, max_length=60)
    entity_key: str | None = Field(default=None, max_length=255)
    entity_description: str | None = None
    entity_metadata_json: dict = Field(default_factory=dict)
    relation_type: SemanticRelationType
    rationale: str | None = None
    source_ref: str | None = None


class ProjectRelationRead(BaseModel):
    id: UUID
    project_id: UUID
    entity_id: UUID
    relation_type: SemanticRelationType
    rationale: str | None
    source_ref: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    entity: KnowledgeEntityRead
