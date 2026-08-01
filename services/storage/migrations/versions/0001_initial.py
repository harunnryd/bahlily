"""initial

Revision ID: 0001
Revises:
Create Date: 2026-08-01 07:21:34.516589

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "meetings",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("language", sa.String(), nullable=True),
        sa.Column("engine", sa.String(), nullable=True),
        sa.Column("model_name", sa.String(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("segments_count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "segments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("meeting_id", sa.String(), nullable=False),
        sa.Column("segment_id", sa.Integer(), nullable=False),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("engine", sa.String(), nullable=False),
        sa.Column("model_name", sa.String(), nullable=False),
        sa.Column("audio_start_time", sa.Float(), nullable=False),
        sa.Column("audio_end_time", sa.Float(), nullable=False),
        sa.Column("language", sa.String(), nullable=True),
        sa.Column("is_partial", sa.Boolean(), nullable=False),
        sa.Column("trace_id", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("meeting_id", "segment_id", name="uq_segments_meeting_segment"),
    )
    op.create_index(op.f("ix_segments_meeting_id"), "segments", ["meeting_id"], unique=False)
    op.create_table(
        "summaries",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("meeting_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("overview", sa.String(), nullable=False),
        sa.Column("key_points", sa.String(), nullable=False),
        sa.Column("action_items", sa.String(), nullable=False),
        sa.Column("quotes", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("meeting_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("summaries")
    op.drop_index(op.f("ix_segments_meeting_id"), table_name="segments")
    op.drop_table("segments")
    op.drop_table("meetings")
