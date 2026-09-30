"""semantic graph relations

Revision ID: 0010_semantic_graph_relations
Revises: 0009_auth_sessions
Create Date: 2026-09-30
"""

from alembic import op
import sqlalchemy as sa


revision = "0010_semantic_graph_relations"
down_revision = "0009_auth_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_entities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=60), nullable=False),
        sa.Column("canonical_key", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("kind", "canonical_key", name="uq_knowledge_entities_kind_key"),
    )
    op.create_index("ix_knowledge_entities_kind", "knowledge_entities", ["kind"], unique=False)
    op.create_index("ix_knowledge_entities_canonical_key", "knowledge_entities", ["canonical_key"], unique=False)
    op.create_index("ix_knowledge_entities_is_active", "knowledge_entities", ["is_active"], unique=False)

    op.create_table(
        "project_relations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("relation_type", sa.String(length=60), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("source_ref", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["entity_id"], ["knowledge_entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "entity_id",
            "relation_type",
            name="uq_project_relations_project_entity_type",
        ),
    )
    op.create_index("ix_project_relations_project_id", "project_relations", ["project_id"], unique=False)
    op.create_index("ix_project_relations_entity_id", "project_relations", ["entity_id"], unique=False)
    op.create_index("ix_project_relations_relation_type", "project_relations", ["relation_type"], unique=False)
    op.create_index("ix_project_relations_is_active", "project_relations", ["is_active"], unique=False)


def downgrade() -> None:
    op.drop_table("project_relations")
    op.drop_table("knowledge_entities")
