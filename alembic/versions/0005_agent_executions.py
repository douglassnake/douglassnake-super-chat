"""agent execution tracking

Revision ID: 0005_agent_executions
Revises: 0004_agent_handoffs
Create Date: 2026-09-18
"""

from alembic import op
import sqlalchemy as sa

revision = "0005_agent_executions"
down_revision = "0004_agent_handoffs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_executions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("handoff_id", sa.Uuid(), sa.ForeignKey("agent_handoffs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("pack_id", sa.Uuid(), sa.ForeignKey("agent_task_packs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="running"),
        sa.Column("branch_ref", sa.Text(), nullable=True),
        sa.Column("commit_sha", sa.String(length=128), nullable=True),
        sa.Column("pr_url", sa.Text(), nullable=True),
        sa.Column("progress_percent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("current_step", sa.Text(), nullable=True),
        sa.Column("event_sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("result_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("handoff_id", name="uq_agent_executions_handoff_id"),
    )
    op.create_index("ix_agent_executions_handoff_id", "agent_executions", ["handoff_id"])
    op.create_index("ix_agent_executions_pack_id", "agent_executions", ["pack_id"])
    op.create_index("ix_agent_executions_project_id", "agent_executions", ["project_id"])
    op.create_index("ix_agent_executions_status", "agent_executions", ["status"])
    op.create_index("ix_agent_executions_created_at", "agent_executions", ["created_at"])

    op.create_table(
        "agent_execution_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("execution_id", sa.Uuid(), sa.ForeignKey("agent_executions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("criterion_index", sa.Integer(), nullable=True),
        sa.Column("criterion_status", sa.String(length=20), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("execution_id", "sequence", name="uq_agent_execution_events_execution_sequence"),
    )
    op.create_index("ix_agent_execution_events_execution_id", "agent_execution_events", ["execution_id"])
    op.create_index("ix_agent_execution_events_event_type", "agent_execution_events", ["event_type"])
    op.create_index("ix_agent_execution_events_criterion_index", "agent_execution_events", ["criterion_index"])
    op.create_index("ix_agent_execution_events_created_at", "agent_execution_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_agent_execution_events_created_at", table_name="agent_execution_events")
    op.drop_index("ix_agent_execution_events_criterion_index", table_name="agent_execution_events")
    op.drop_index("ix_agent_execution_events_event_type", table_name="agent_execution_events")
    op.drop_index("ix_agent_execution_events_execution_id", table_name="agent_execution_events")
    op.drop_table("agent_execution_events")

    op.drop_index("ix_agent_executions_created_at", table_name="agent_executions")
    op.drop_index("ix_agent_executions_status", table_name="agent_executions")
    op.drop_index("ix_agent_executions_project_id", table_name="agent_executions")
    op.drop_index("ix_agent_executions_pack_id", table_name="agent_executions")
    op.drop_index("ix_agent_executions_handoff_id", table_name="agent_executions")
    op.drop_table("agent_executions")
