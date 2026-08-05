"""speaker profile unique name

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-05 12:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Dedupe existing rows then add the UNIQUE constraint.

    The label endpoint silently merged profiles by name before this revision,
    so a DB at 0006 may already contain duplicate names. Ordering the dedupe
    by `rowid` rather than the TEXT primary key `id` matters: `id` is a UUID4
    string with no ordering relationship to creation time, while SQLite's
    implicit `rowid` always tracks insertion order. Downgrading keeps whatever
    dedupe landed and only drops the constraint.
    """
    op.execute(
        "UPDATE segments "
        "SET speaker_profile_id = ("
        "  SELECT retained.id "
        "  FROM speaker_profiles AS duplicate "
        "  JOIN speaker_profiles AS retained "
        "    ON retained.name = duplicate.name "
        "  WHERE duplicate.id = segments.speaker_profile_id "
        "    AND retained.rowid = ("
        "      SELECT MIN(rowid) FROM speaker_profiles sp2 "
        "      WHERE sp2.name = duplicate.name"
        "    )"
        ") "
        "WHERE speaker_profile_id IN ("
        "  SELECT id FROM speaker_profiles "
        "  WHERE rowid NOT IN ("
        "    SELECT MIN(rowid) FROM speaker_profiles GROUP BY name"
        "  )"
        ")"
    )
    op.execute(
        "DELETE FROM speaker_profiles "
        "WHERE rowid NOT IN (SELECT MIN(rowid) FROM speaker_profiles GROUP BY name)"
    )
    with op.batch_alter_table("speaker_profiles") as batch_op:
        batch_op.create_unique_constraint("uq_speaker_profiles_name", ["name"])


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("speaker_profiles") as batch_op:
        batch_op.drop_constraint("uq_speaker_profiles_name", type_="unique")
