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


def test_migration_0002_is_head() -> None:
    from alembic.script import ScriptDirectory

    from bahlily_storage import db

    script = ScriptDirectory.from_config(db.alembic_config())
    assert script.get_current_head() == "0002"
