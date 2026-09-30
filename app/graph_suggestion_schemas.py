from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.knowledge_schemas import SemanticRelationType


class GraphRelationSuggestion(BaseModel):
    entity_name: str
    entity_kind: str
    entity_key: str
    entity_description: str | None = None
    relation_type: SemanticRelationType
    rationale: str
    evidence: str
    source_ref: str | None = None
    confidence: float = Field(ge=0, le=1)


class GraphSuggestionBatchRead(BaseModel):
    id: UUID
    project_id: UUID
    status: str
    summary: str
    suggestions: list[GraphRelationSuggestion]
    source_refs: list[str]
    created_at: datetime
    applied_at: datetime | None = None
    discarded_at: datetime | None = None


class GraphSuggestionApplyRequest(BaseModel):
    selected_indexes: list[int] = Field(default_factory=list)


class GraphSuggestionApplyResult(BaseModel):
    batch: GraphSuggestionBatchRead
    applied_count: int
    skipped_count: int
