"""worker attempts, leases and provenance

Revision ID: 0007_worker_attempts
Revises: 0006_executor_requests
Create Date: 2026-09-21
"""

from alembic import op
import sqlalchemy as sa


revision = "0007_worker_attempts"
down_revision = "0006_executor_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "worker_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("executor_request_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("worker_id", sa.String(length=128), nullable=True),
        sa.Column("backend", sa.String(length=60), nullable=True),
        sa.Column("job_digest", sa.String(length=64), nullable=True),
        sa.Column("result_digest", sa.String(length=64), nullable=True),
        sa.Column("lease_token_hash", sa.String(length=64), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provenance_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("orphaned_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["executor_request_id"], ["executor_requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["execution_id"], ["agent_executions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("executor_request_id", "attempt_number", name="uq_worker_attempt_request_number"),
    )
    for name, column in (
        ("ix_worker_attempts_executor_request_id", "executor_request_id"),
        ("ix_worker_attempts_execution_id", "execution_id"),
        ("ix_worker_attempts_project_id", "project_id"),
        ("ix_worker_attempts_status", "status"),
        ("ix_worker_attempts_worker_id", "worker_id"),
        ("ix_worker_attempts_job_digest", "job_digest"),
        ("ix_worker_attempts_result_digest", "result_digest"),
        ("ix_worker_attempts_lease_token_hash", "lease_token_hash"),
        ("ix_worker_attempts_lease_expires_at", "lease_expires_at"),
        ("ix_worker_attempts_heartbeat_at", "heartbeat_at"),
        ("ix_worker_attempts_created_at", "created_at"),
    ):
        op.create_index(name, "worker_attempts", [column], unique=False)


def downgrade() -> None:
    op.drop_table("worker_attempts")
