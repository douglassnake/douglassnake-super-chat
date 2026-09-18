"""session memory deltas

Revision ID: 0002_session_deltas
Revises: 0001_m1
Create Date: 2026-09-18
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_session_deltas"
down_revision = "0001_m1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "session_deltas",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_key", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("decisions_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("tasks_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("close_task_ids_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("status_change", sa.String(length=80), nullable=True),
        sa.Column("next_action", sa.Text(), nullable=True),
        sa.Column("source_refs_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("discarded_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("project_id", "session_key", name="uq_session_deltas_project_session_key"),
    )
    op.create_index("ix_session_deltas_project_id", "session_deltas", ["project_id"])
    op.create_index("ix_session_deltas_status", "session_deltas", ["status"])
    op.create_index("ix_session_deltas_created_at", "session_deltas", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_session_deltas_created_at", table_name="session_deltas")
    op.drop_index("ix_session_deltas_status", table_name="session_deltas")
    op.drop_index("ix_session_deltas_project_id", table_name="session_deltas")
    op.drop_table("session_deltas")
