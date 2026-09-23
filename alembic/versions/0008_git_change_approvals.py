"""git change approvals

Revision ID: 0008_git_change_approvals
Revises: 0007_worker_attempts
Create Date: 2026-09-21
"""

from alembic import op
import sqlalchemy as sa


revision = "0008_git_change_approvals"
down_revision = "0007_worker_attempts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "git_change_approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("executor_request_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("patch_digest", sa.String(length=64), nullable=False),
        sa.Column("proposal_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("changed_files_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["executor_request_id"], ["executor_requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["execution_id"], ["agent_executions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("executor_request_id", name="uq_git_change_approval_executor_request"),
        sa.UniqueConstraint("proposal_fingerprint"),
    )
    for name, column in (
        ("ix_git_change_approvals_executor_request_id", "executor_request_id"),
        ("ix_git_change_approvals_execution_id", "execution_id"),
        ("ix_git_change_approvals_project_id", "project_id"),
        ("ix_git_change_approvals_status", "status"),
        ("ix_git_change_approvals_patch_digest", "patch_digest"),
        ("ix_git_change_approvals_proposal_fingerprint", "proposal_fingerprint"),
        ("ix_git_change_approvals_created_at", "created_at"),
    ):
        op.create_index(name, "git_change_approvals", [column], unique=False)


def downgrade() -> None:
    op.drop_table("git_change_approvals")
