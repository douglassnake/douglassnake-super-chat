"""graph suggestion batches

Revision ID: 0011_graph_suggestion_batches
Revises: 0010_semantic_graph_relations
Create Date: 2026-09-30
"""

from alembic import op
import sqlalchemy as sa


revision = "0011_graph_suggestion_batches"
down_revision = "0010_semantic_graph_relations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "graph_suggestion_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("suggestions_json", sa.JSON(), nullable=False),
        sa.Column("source_refs_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("discarded_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_graph_suggestion_batches_project_id",
        "graph_suggestion_batches",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_graph_suggestion_batches_status",
        "graph_suggestion_batches",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_graph_suggestion_batches_created_at",
        "graph_suggestion_batches",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("graph_suggestion_batches")
