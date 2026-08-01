from __future__ import annotations

import os
import sqlite3
from pathlib import Path


def test_alembic_upgrade_head(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    os.environ["BAHLILY_STORAGE_DB"] = str(db_path)
    try:
        from alembic import command
        from alembic.config import Config

        cfg = Config("alembic.ini")
        command.upgrade(cfg, "head")

        conn = sqlite3.connect(str(db_path))
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        tables = {row[0] for row in rows}
        conn.close()
        assert "meetings" in tables
        assert "segments" in tables
        assert "summaries" in tables
    finally:
        del os.environ["BAHLILY_STORAGE_DB"]


async def test_upgrade_to_head_stamps_alembic_version(tmp_path: Path) -> None:
    """The async startup helper must leave the DB alembic-tracked."""
    from bahlily_storage import db

    db_path = tmp_path / "startup.db"
    os.environ["BAHLILY_STORAGE_DB"] = str(db_path)
    try:
        await db.upgrade_to_head()
    finally:
        del os.environ["BAHLILY_STORAGE_DB"]

    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        tables = {row[0] for row in rows}
        versions = {row[0] for row in conn.execute("SELECT version_num FROM alembic_version")}
    finally:
        conn.close()

    assert {"meetings", "segments", "summaries", "alembic_version"}.issubset(tables)
    assert versions  # a revision is stamped, so the next migration can apply


def test_find_alembic_ini_locates_service_root() -> None:
    from bahlily_storage import db

    ini = db.find_alembic_ini()
    assert ini.name == "alembic.ini"
    assert (ini.parent / "migrations" / "versions").is_dir()


async def test_migrated_schema_roundtrips_tz_aware_datetime(tmp_path: Path) -> None:
    """Against an alembic-built (not create_all) schema, tzinfo must survive."""
    import datetime

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from bahlily_storage import db
    from bahlily_storage.models import Meeting

    db_path = tmp_path / "tz.db"
    os.environ["BAHLILY_STORAGE_DB"] = str(db_path)
    try:
        await db.upgrade_to_head()
    finally:
        del os.environ["BAHLILY_STORAGE_DB"]

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


async def test_upgrade_to_head_stamps_preexisting_create_all_db(tmp_path: Path) -> None:
    """Regression: a DB from the old `init_db()` startup (tables present, no
    `alembic_version`) must be stamped to 0001 and upgraded, not crash with
    "table meetings already exists".
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    from bahlily_storage import db
    from bahlily_storage.models import Base

    db_path = tmp_path / "legacy.db"
    os.environ["BAHLILY_STORAGE_DB"] = str(db_path)
    try:
        # Simulate the old create_all-based startup path: tables exist,
        # alembic_version does not. (Use a dedicated engine pointed at
        # db_path rather than db.init_db(), which binds to the module-level
        # `engine` fixed at import time, not the env var set here.)
        legacy_engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        try:
            async with legacy_engine.begin() as aconn:
                await aconn.run_sync(Base.metadata.create_all)
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
    finally:
        del os.environ["BAHLILY_STORAGE_DB"]

    sconn = sqlite3.connect(str(db_path))
    try:
        rows = sconn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        tables_after = {row[0] for row in rows}
        versions = {row[0] for row in sconn.execute("SELECT version_num FROM alembic_version")}
    finally:
        sconn.close()

    assert {"meetings", "segments", "summaries", "alembic_version"}.issubset(tables_after)
    assert versions == {"0002"}  # upgraded all the way to head, not stuck at 0001


async def test_upgrade_to_head_is_noop_when_already_at_head(tmp_path: Path) -> None:
    """A DB already stamped at head must not error on a second upgrade call."""
    from bahlily_storage import db

    db_path = tmp_path / "already_head.db"
    os.environ["BAHLILY_STORAGE_DB"] = str(db_path)
    try:
        await db.upgrade_to_head()
        # Calling it again against an already-migrated DB must be a no-op.
        await db.upgrade_to_head()
    finally:
        del os.environ["BAHLILY_STORAGE_DB"]

    conn = sqlite3.connect(str(db_path))
    try:
        versions = {row[0] for row in conn.execute("SELECT version_num FROM alembic_version")}
    finally:
        conn.close()
    assert versions == {"0002"}


def test_migration_0002_is_head() -> None:
    from alembic.script import ScriptDirectory

    from bahlily_storage import db

    script = ScriptDirectory.from_config(db.alembic_config())
    assert script.get_current_head() == "0002"
