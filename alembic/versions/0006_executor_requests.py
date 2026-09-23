"""controlled executor requests

Revision ID: 0006_executor_requests
Revises: 0005_agent_executions
Create Date: 2026-09-18
"""

from alembic import op
import sqlalchemy as sa

revision = "0006_executor_requests"
down_revision = "0005_agent_executions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "executor_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("execution_id", sa.Uuid(), sa.ForeignKey("agent_executions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("handoff_id", sa.Uuid(), sa.ForeignKey("agent_handoffs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action", sa.String(length=60), nullable=False),
        sa.Column("adapter_type", sa.String(length=60), nullable=False, server_default="manual"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="prepared"),
        sa.Column("payload_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("execution_id", "fingerprint", name="uq_executor_requests_execution_fingerprint"),
    )
    op.create_index("ix_executor_requests_execution_id", "executor_requests", ["execution_id"])
    op.create_index("ix_executor_requests_handoff_id", "executor_requests", ["handoff_id"])
    op.create_index("ix_executor_requests_project_id", "executor_requests", ["project_id"])
    op.create_index("ix_executor_requests_action", "executor_requests", ["action"])
    op.create_index("ix_executor_requests_adapter_type", "executor_requests", ["adapter_type"])
    op.create_index("ix_executor_requests_status", "executor_requests", ["status"])
    op.create_index("ix_executor_requests_fingerprint", "executor_requests", ["fingerprint"])
    op.create_index("ix_executor_requests_created_at", "executor_requests", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_executor_requests_created_at", table_name="executor_requests")
    op.drop_index("ix_executor_requests_fingerprint", table_name="executor_requests")
    op.drop_index("ix_executor_requests_status", table_name="executor_requests")
    op.drop_index("ix_executor_requests_adapter_type", table_name="executor_requests")
    op.drop_index("ix_executor_requests_action", table_name="executor_requests")
    op.drop_index("ix_executor_requests_project_id", table_name="executor_requests")
    op.drop_index("ix_executor_requests_handoff_id", table_name="executor_requests")
    op.drop_index("ix_executor_requests_execution_id", table_name="executor_requests")
    op.drop_table("executor_requests")
