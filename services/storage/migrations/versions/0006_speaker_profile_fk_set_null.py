"""speaker profile fk set null

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-02 14:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("segments") as batch_op:
        batch_op.drop_constraint("fk_segments_speaker_profile_id", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_segments_speaker_profile_id",
            "speaker_profiles",
            ["speaker_profile_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("segments") as batch_op:
        batch_op.drop_constraint("fk_segments_speaker_profile_id", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_segments_speaker_profile_id",
            "speaker_profiles",
            ["speaker_profile_id"],
            ["id"],
        )
