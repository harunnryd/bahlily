from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
import sqlalchemy as sa


def test_alembic_upgrade_head(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("BAHLILY_STORAGE_DB", str(db_path))

    from alembic import command

    from bahlily_storage import db

    command.upgrade(db.alembic_config(), "head")

    conn = sqlite3.connect(str(db_path))
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    tables = {row[0] for row in rows}
    conn.close()
    assert "meetings" in tables
    assert "segments" in tables
    assert "summaries" in tables


async def test_upgrade_to_head_stamps_alembic_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The async startup helper must leave the DB alembic-tracked."""
    from bahlily_storage import db

    db_path = tmp_path / "startup.db"
    monkeypatch.setenv("BAHLILY_STORAGE_DB", str(db_path))
    await db.upgrade_to_head()

    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        tables = {row[0] for row in rows}
        versions = {row[0] for row in conn.execute("SELECT version_num FROM alembic_version")}
    finally:
        conn.close()

    assert {"meetings", "segments", "summaries", "alembic_version"}.issubset(tables)
    assert versions  # a revision is stamped, so the next migration can apply


async def test_upgrade_to_head_points_engine_at_the_migrated_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: `engine`/`async_session_factory` must target the same file
    `upgrade_to_head()` just migrated, not whatever `BAHLILY_STORAGE_DB`
    resolved to at import time. Without `_configure()` re-resolving on every
    call, a write through `db.async_session_factory` right after startup
    could silently land in a different file than the one just migrated."""
    import datetime

    from bahlily_storage import db
    from bahlily_storage.models import Meeting

    db_path = tmp_path / "shared-url.db"
    monkeypatch.setenv("BAHLILY_STORAGE_DB", str(db_path))
    await db.upgrade_to_head()

    async with db.async_session_factory() as session:
        session.add(
            Meeting(
                id="m-shared",
                status="recording",
                started_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
                segments_count=0,
            )
        )
        await session.commit()

    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute("SELECT id FROM meetings WHERE id = 'm-shared'").fetchone()
    finally:
        conn.close()
    assert row == ("m-shared",)


def test_find_alembic_ini_locates_service_root() -> None:
    from bahlily_storage import db

    ini = db.find_alembic_ini()
    assert ini.name == "alembic.ini"
    assert (ini.parent / "migrations" / "versions").is_dir()


async def test_migrated_schema_roundtrips_tz_aware_datetime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Against an alembic-built (not create_all) schema, tzinfo must survive."""
    import datetime

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from bahlily_storage import db
    from bahlily_storage.models import Meeting

    db_path = tmp_path / "tz.db"
    monkeypatch.setenv("BAHLILY_STORAGE_DB", str(db_path))
    await db.upgrade_to_head()

    started = datetime.datetime(2026, 5, 4, 3, 2, 1, tzinfo=datetime.UTC)
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as s:
            s.add(Meeting(id="m-tz", status="recording", started_at=started, segments_count=0))
            await s.commit()
        async with factory() as s:
            fetched = await s.get(Meeting, "m-tz")
            assert fetched is not None
            assert fetched.started_at.utcoffset() is not None
            assert fetched.started_at == started
    finally:
        await engine.dispose()


async def test_upgrade_to_head_stamps_preexisting_create_all_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: a DB from the old `init_db()` startup (tables present, no
    `alembic_version`) must be stamped to 0001 and upgraded, not crash with
    "table meetings already exists".
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    from bahlily_storage import db

    db_path = tmp_path / "legacy.db"
    monkeypatch.setenv("BAHLILY_STORAGE_DB", str(db_path))

    # Simulate the old create_all-based startup path: tables exist,
    # alembic_version does not. (Use a dedicated engine pointed at
    # db_path rather than db.init_db(), which binds to the module-level
    # `engine` fixed at import time, not the env var set here.) Build the
    # tables' columns explicitly, mirroring migration 0001's `create_table`
    # calls, rather than pulling them from `bahlily_storage.models.Base` —
    # the ORM models have since grown columns (0005's `recording_path`,
    # `diarization_status`, `speaker_cluster_label`, `speaker_profile_id`)
    # that a genuinely legacy pre-migrations DB would never have had, and
    # create_all-ing those in would make 0005's own `add_column` collide
    # with a column the "legacy" DB was never meant to contain.
    legacy_metadata = sa.MetaData()
    sa.Table(
        "meetings",
        legacy_metadata,
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("language", sa.String(), nullable=True),
        sa.Column("engine", sa.String(), nullable=True),
        sa.Column("model_name", sa.String(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("segments_count", sa.Integer(), nullable=False),
    )
    sa.Table(
        "segments",
        legacy_metadata,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("meeting_id", sa.String(), sa.ForeignKey("meetings.id"), nullable=False),
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
        sa.UniqueConstraint("meeting_id", "segment_id", name="uq_segments_meeting_segment"),
        sa.Index("ix_segments_meeting_id", "meeting_id"),
    )
    sa.Table(
        "summaries",
        legacy_metadata,
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "meeting_id", sa.String(), sa.ForeignKey("meetings.id"), nullable=False, unique=True
        ),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("overview", sa.String(), nullable=False),
        sa.Column("key_points", sa.String(), nullable=False),
        sa.Column("action_items", sa.String(), nullable=False),
        sa.Column("quotes", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    legacy_engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        async with legacy_engine.begin() as aconn:
            await aconn.run_sync(legacy_metadata.create_all)
    finally:
        await legacy_engine.dispose()

    sconn = sqlite3.connect(str(db_path))
    try:
        rows = sconn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        tables_before = {row[0] for row in rows}
    finally:
        sconn.close()
    assert "meetings" in tables_before
    assert "alembic_version" not in tables_before

    # Must not raise "table meetings already exists".
    await db.upgrade_to_head()

    sconn = sqlite3.connect(str(db_path))
    try:
        rows = sconn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        tables_after = {row[0] for row in rows}
        versions = {row[0] for row in sconn.execute("SELECT version_num FROM alembic_version")}
    finally:
        sconn.close()

    assert {"meetings", "segments", "summaries", "alembic_version"}.issubset(tables_after)
    assert versions == {"0007"}  # upgraded all the way to head, not stuck at 0001


async def test_upgrade_to_head_is_noop_when_already_at_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A DB already stamped at head must not error on a second upgrade call."""
    from bahlily_storage import db

    db_path = tmp_path / "already_head.db"
    monkeypatch.setenv("BAHLILY_STORAGE_DB", str(db_path))
    await db.upgrade_to_head()
    # Calling it again against an already-migrated DB must be a no-op.
    await db.upgrade_to_head()

    conn = sqlite3.connect(str(db_path))
    try:
        versions = {row[0] for row in conn.execute("SELECT version_num FROM alembic_version")}
    finally:
        conn.close()
    assert versions == {"0007"}


def test_migration_0007_is_head() -> None:
    from alembic.script import ScriptDirectory

    from bahlily_storage import db

    script = ScriptDirectory.from_config(db.alembic_config())
    assert script.get_current_head() == "0007"


# Mirrors migrations/versions/0002_timezone_aware_datetimes.py's `_COLUMNS` —
# the tables/columns that migration's `batch_alter_table` rebuild touches.
_0002_COLUMNS = (("meetings", "started_at"), ("meetings", "ended_at"), ("summaries", "created_at"))


def test_downgrade_from_head_preserves_data_in_rebuilt_columns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """0002's `batch_alter_table` rebuild (SQLite has no in-place `ALTER
    COLUMN TYPE`) must round-trip cleanly in both directions.

    SQLite compiles `sa.DateTime()` and `sa.DateTime(timezone=True)` to the
    same bare `DATETIME` column type, so there's no DDL-level signal to
    assert "naive" vs "aware" against the schema itself — tz-correctness
    comes from the `UtcDateTime` type decorator in `models.py`, which is
    independent of what migration revision the DB is stamped at. What's
    verifiable, and was untested before this: only `upgrade` was exercised,
    never `downgrade` — the rebuild it performs on live data could silently
    drop or corrupt exactly the columns it touches.

    Uses `command.upgrade`/`command.downgrade` directly (not
    `db.upgrade_to_head()`) so this stays a plain sync test: both are sync
    calls that internally run their own event loop via `migrations/env.py`,
    which cannot nest inside a running one.
    """
    from alembic import command

    from bahlily_storage import db

    db_path = tmp_path / "downgrade.db"
    monkeypatch.setenv("BAHLILY_STORAGE_DB", str(db_path))
    command.upgrade(db.alembic_config(), "head")

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO meetings (id, status, started_at, ended_at, segments_count) "
            "VALUES ('m1', 'stopped', '2026-01-01 00:00:00', '2026-01-01 01:00:00', 0)"
        )
        conn.execute(
            "INSERT INTO summaries "
            "(id, meeting_id, title, overview, key_points, action_items, quotes, "
            "provider, model, created_at) "
            "VALUES ('s1', 'm1', 'T', 'O', '[]', '[]', '[]', 'p', 'm', "
            "'2026-01-01 02:00:00')"
        )
        conn.commit()
    finally:
        conn.close()

    command.downgrade(db.alembic_config(), "0001")

    conn = sqlite3.connect(str(db_path))
    try:
        versions = {row[0] for row in conn.execute("SELECT version_num FROM alembic_version")}
        for table, column in _0002_COLUMNS:
            # Just confirms the column the rebuild touched still exists and
            # still holds a value after downgrading — SQLite reports the
            # same declared type either way (see docstring).
            row = conn.execute(f"SELECT {column} FROM {table} LIMIT 1").fetchone()
            assert row is not None and row[0] is not None
        meeting_row = conn.execute(
            "SELECT status, started_at, ended_at FROM meetings WHERE id = 'm1'"
        ).fetchone()
        summary_row = conn.execute(
            "SELECT title, created_at FROM summaries WHERE id = 's1'"
        ).fetchone()
    finally:
        conn.close()

    assert versions == {"0001"}
    assert meeting_row == ("stopped", "2026-01-01 00:00:00", "2026-01-01 01:00:00")
    assert summary_row == ("T", "2026-01-01 02:00:00")


def test_alembic_upgrade_head_creates_summary_templates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "templates.db"
    monkeypatch.setenv("BAHLILY_STORAGE_DB", str(db_path))

    from alembic import command

    from bahlily_storage import db

    command.upgrade(db.alembic_config(), "head")

    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        tables = {row[0] for row in rows}
        cols = {row[1] for row in conn.execute("PRAGMA table_info(summary_templates)")}
    finally:
        conn.close()

    assert "summary_templates" in tables
    assert cols == {
        "id",
        "name",
        "version",
        "system_prompt",
        "focus_instructions",
        "few_shot_examples",
        "created_at",
        "updated_at",
    }


def test_alembic_upgrade_head_creates_speaker_profiles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "speaker_profiles.db"
    monkeypatch.setenv("BAHLILY_STORAGE_DB", str(db_path))

    from alembic import command

    from bahlily_storage import db

    command.upgrade(db.alembic_config(), "head")

    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        tables = {row[0] for row in rows}
        cols = {row[1] for row in conn.execute("PRAGMA table_info(speaker_profiles)")}
    finally:
        conn.close()

    assert "speaker_profiles" in tables
    assert cols == {"id", "name", "voice_embedding", "created_at", "updated_at"}


def test_alembic_upgrade_head_adds_diarization_columns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "diarization_fields.db"
    monkeypatch.setenv("BAHLILY_STORAGE_DB", str(db_path))

    from alembic import command

    from bahlily_storage import db

    command.upgrade(db.alembic_config(), "head")

    conn = sqlite3.connect(str(db_path))
    try:
        segment_cols = {row[1] for row in conn.execute("PRAGMA table_info(segments)")}
        meeting_cols = {row[1] for row in conn.execute("PRAGMA table_info(meetings)")}
    finally:
        conn.close()

    assert {"speaker_cluster_label", "speaker_profile_id"}.issubset(segment_cols)
    assert {"recording_path", "diarization_status"}.issubset(meeting_cols)


def test_alembic_upgrade_head_sets_speaker_profile_fk_on_delete_null(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "fk_set_null.db"
    monkeypatch.setenv("BAHLILY_STORAGE_DB", str(db_path))

    from alembic import command

    from bahlily_storage import db

    command.upgrade(db.alembic_config(), "head")

    conn = sqlite3.connect(str(db_path))
    try:
        fks = conn.execute("PRAGMA foreign_key_list(segments)").fetchall()
    finally:
        conn.close()

    # PRAGMA foreign_key_list columns: (id, seq, table, from, to, on_update, on_delete, match)
    speaker_fk = next(fk for fk in fks if fk[2] == "speaker_profiles")
    assert speaker_fk[6] == "SET NULL"


def test_alembic_upgrade_head_dedupes_duplicate_speaker_profile_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Migration 0007 dedupes existing duplicate-named speaker profiles by
    SQLite rowid (insertion order, not the UUID TEXT primary key) before
    adding the UNIQUE constraint, preserving the earliest-inserted row."""
    from alembic import command

    from bahlily_storage import db

    db_path = tmp_path / "speaker_profiles_dedup.db"
    monkeypatch.setenv("BAHLILY_STORAGE_DB", str(db_path))

    # Apply migrations 0001..0006 only — 0007 has not run yet.
    command.upgrade(db.alembic_config(), "0006")

    # Seed two profiles sharing the same name. The lex-min id ('a') is
    # inserted SECOND so that `MIN(rowid)` (insertion order) and `MIN(id)`
    # (lexicographic) disagree on which row survives — this is the only
    # way the test can actually regress-protect against a reintroduction
    # of the lexical-sort mistake the migration was originally written to
    # avoid. With 'z' inserted first, `MIN(rowid)` keeps 'z' and `MIN(id)`
    # would keep 'a', so the assertion below would fail under the bug.
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO speaker_profiles "
            "(id, name, voice_embedding, created_at, updated_at) "
            "VALUES ('z', 'Alice', '[]', '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
        )
        conn.execute(
            "INSERT INTO speaker_profiles "
            "(id, name, voice_embedding, created_at, updated_at) "
            "VALUES ('a', 'Alice', '[]', '2026-01-02 00:00:00', '2026-01-02 00:00:00')"
        )
        conn.commit()
    finally:
        conn.close()

    # Apply 0007 — dedupe must run before the UNIQUE constraint is added.
    command.upgrade(db.alembic_config(), "head")

    # Only the earliest-inserted row ('z', lowest rowid) survives.
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute("SELECT id FROM speaker_profiles").fetchall()
    finally:
        conn.close()
    assert sorted(r[0] for r in rows) == ["z"]
