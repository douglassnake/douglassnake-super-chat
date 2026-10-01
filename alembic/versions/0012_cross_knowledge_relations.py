"""cross knowledge relations

Revision ID: 0012_cross_knowledge_relations
Revises: 0011_graph_suggestion_batches
Create Date: 2026-10-01
"""

from alembic import op
import sqlalchemy as sa


revision = "0012_cross_knowledge_relations"
down_revision = "0011_graph_suggestion_batches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_relations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_entity_id", sa.Uuid(), nullable=False),
        sa.Column("target_entity_id", sa.Uuid(), nullable=False),
        sa.Column("relation_type", sa.String(length=60), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("source_ref", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_entity_id"], ["knowledge_entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_entity_id"], ["knowledge_entities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_entity_id",
            "target_entity_id",
            "relation_type",
            name="uq_knowledge_relations_source_target_type",
        ),
    )
    op.create_index(
        "ix_knowledge_relations_source_entity_id",
        "knowledge_relations",
        ["source_entity_id"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_relations_target_entity_id",
        "knowledge_relations",
        ["target_entity_id"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_relations_relation_type",
        "knowledge_relations",
        ["relation_type"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_relations_is_active",
        "knowledge_relations",
        ["is_active"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("knowledge_relations")
