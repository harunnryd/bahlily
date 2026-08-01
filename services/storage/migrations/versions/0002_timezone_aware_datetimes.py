"""timezone aware datetimes

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-01 08:52:56.343310

Marks the meeting/summary timestamp columns as timezone-aware. SQLite does not
enforce column types, and the actual tz-correctness is delivered by the
`UtcDateTime` type decorator in `models.py`; this migration exists so the
tracked schema matches the ORM metadata (autogenerate reflects both variants as
plain DATETIME on SQLite, so it cannot produce these ops itself).

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS: tuple[tuple[str, str, bool], ...] = (
    ("meetings", "started_at", False),
    ("meetings", "ended_at", True),
    ("summaries", "created_at", False),
)


def upgrade() -> None:
    """Upgrade schema."""
    for table, column, nullable in _COLUMNS:
        with op.batch_alter_table(table) as batch_op:
            batch_op.alter_column(
                column,
                existing_type=sa.DateTime(),
                type_=sa.DateTime(timezone=True),
                existing_nullable=nullable,
            )


def downgrade() -> None:
    """Downgrade schema."""
    for table, column, nullable in _COLUMNS:
        with op.batch_alter_table(table) as batch_op:
            batch_op.alter_column(
                column,
                existing_type=sa.DateTime(timezone=True),
                type_=sa.DateTime(),
                existing_nullable=nullable,
            )
