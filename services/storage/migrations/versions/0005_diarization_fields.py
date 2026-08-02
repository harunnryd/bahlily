"""diarization fields

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-02 13:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("segments") as batch_op:
        batch_op.add_column(sa.Column("speaker_cluster_label", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("speaker_profile_id", sa.String(), nullable=True))
        batch_op.create_foreign_key(
            "fk_segments_speaker_profile_id",
            "speaker_profiles",
            ["speaker_profile_id"],
            ["id"],
        )
    with op.batch_alter_table("meetings") as batch_op:
        batch_op.add_column(sa.Column("recording_path", sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "diarization_status",
                sa.String(),
                nullable=False,
                server_default="not_started",
            )
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("meetings") as batch_op:
        batch_op.drop_column("diarization_status")
        batch_op.drop_column("recording_path")
    with op.batch_alter_table("segments") as batch_op:
        batch_op.drop_constraint("fk_segments_speaker_profile_id", type_="foreignkey")
        batch_op.drop_column("speaker_profile_id")
        batch_op.drop_column("speaker_cluster_label")
