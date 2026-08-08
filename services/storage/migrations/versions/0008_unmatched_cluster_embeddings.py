"""unmatched cluster embeddings

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-08 12:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "unmatched_cluster_embeddings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("meeting_id", sa.String(), nullable=False),
        sa.Column("cluster_label", sa.String(), nullable=False),
        sa.Column("voice_embedding", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "meeting_id", "cluster_label", name="uq_unmatched_cluster_embeddings_meeting_cluster"
        ),
    )
    op.create_index(
        op.f("ix_unmatched_cluster_embeddings_meeting_id"),
        "unmatched_cluster_embeddings",
        ["meeting_id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_unmatched_cluster_embeddings_meeting_id"),
        table_name="unmatched_cluster_embeddings",
    )
    op.drop_table("unmatched_cluster_embeddings")
