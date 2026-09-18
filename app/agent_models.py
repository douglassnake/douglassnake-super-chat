from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models import utcnow


class AgentTaskPack(Base):
    __tablename__ = "agent_task_packs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
    )
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    objective: Mapped[str] = mapped_column(Text)
    profile: Mapped[str] = mapped_column(String(30))
    query_text: Mapped[str] = mapped_column(Text)
    acceptance_criteria_json: Mapped[list] = mapped_column(JSON, default=list)
    constraints_json: Mapped[list] = mapped_column(JSON, default=list)
    suggested_areas_json: Mapped[list] = mapped_column(JSON, default=list)
    context_json: Mapped[list] = mapped_column(JSON, default=list)
    sources_json: Mapped[list] = mapped_column(JSON, default=list)
    budget_json: Mapped[dict] = mapped_column(JSON, default=dict)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
