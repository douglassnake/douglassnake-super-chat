"""auth sessions

Revision ID: 0009_auth_sessions
Revises: 0008_git_change_approvals
Create Date: 2026-09-23
"""

from alembic import op
import sqlalchemy as sa


revision = "0009_auth_sessions"
down_revision = "0008_git_change_approvals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_token_hash", sa.String(length=64), nullable=False),
        sa.Column("username", sa.String(length=160), nullable=False),
        sa.Column("role", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    for name, column in (
        ("ix_auth_sessions_token_hash", "token_hash"),
        ("ix_auth_sessions_username", "username"),
        ("ix_auth_sessions_expires_at", "expires_at"),
        ("ix_auth_sessions_revoked_at", "revoked_at"),
    ):
        op.create_index(name, "auth_sessions", [column], unique=False)


def downgrade() -> None:
    op.drop_table("auth_sessions")
