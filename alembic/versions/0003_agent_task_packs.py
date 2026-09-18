"""agent task packs

Revision ID: 0003_agent_task_packs
Revises: 0002_session_deltas
Create Date: 2026-09-18
"""

from alembic import op
import sqlalchemy as sa

revision = "0003_agent_task_packs"
down_revision = "0002_session_deltas"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_task_packs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("project_snapshot_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("profile", sa.String(length=30), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("acceptance_criteria_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("constraints_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("suggested_areas_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("context_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("sources_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("budget_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("fingerprint", name="uq_agent_task_packs_fingerprint"),
    )
    op.create_index("ix_agent_task_packs_project_id", "agent_task_packs", ["project_id"])
    op.create_index("ix_agent_task_packs_status", "agent_task_packs", ["status"])
    op.create_index("ix_agent_task_packs_fingerprint", "agent_task_packs", ["fingerprint"])
    op.create_index("ix_agent_task_packs_created_at", "agent_task_packs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_agent_task_packs_created_at", table_name="agent_task_packs")
    op.drop_index("ix_agent_task_packs_fingerprint", table_name="agent_task_packs")
    op.drop_index("ix_agent_task_packs_status", table_name="agent_task_packs")
    op.drop_index("ix_agent_task_packs_project_id", table_name="agent_task_packs")
    op.drop_table("agent_task_packs")
