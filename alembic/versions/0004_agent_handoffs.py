"""agent handoffs

Revision ID: 0004_agent_handoffs
Revises: 0003_agent_task_packs
Create Date: 2026-09-18
"""

from alembic import op
import sqlalchemy as sa

revision = "0004_agent_handoffs"
down_revision = "0003_agent_task_packs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_handoffs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("pack_id", sa.Uuid(), sa.ForeignKey("agent_task_packs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="prepared"),
        sa.Column("executor_type", sa.String(length=60), nullable=False),
        sa.Column("executor_target", sa.Text(), nullable=True),
        sa.Column("allowed_actions_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("pack_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("pack_snapshot_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_agent_handoffs_pack_id", "agent_handoffs", ["pack_id"])
    op.create_index("ix_agent_handoffs_project_id", "agent_handoffs", ["project_id"])
    op.create_index("ix_agent_handoffs_status", "agent_handoffs", ["status"])
    op.create_index("ix_agent_handoffs_executor_type", "agent_handoffs", ["executor_type"])
    op.create_index("ix_agent_handoffs_pack_fingerprint", "agent_handoffs", ["pack_fingerprint"])
    op.create_index("ix_agent_handoffs_created_at", "agent_handoffs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_agent_handoffs_created_at", table_name="agent_handoffs")
    op.drop_index("ix_agent_handoffs_pack_fingerprint", table_name="agent_handoffs")
    op.drop_index("ix_agent_handoffs_executor_type", table_name="agent_handoffs")
    op.drop_index("ix_agent_handoffs_status", table_name="agent_handoffs")
    op.drop_index("ix_agent_handoffs_project_id", table_name="agent_handoffs")
    op.drop_index("ix_agent_handoffs_pack_id", table_name="agent_handoffs")
    op.drop_table("agent_handoffs")
