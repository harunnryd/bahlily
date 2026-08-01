from __future__ import annotations

import asyncio
import datetime
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import event, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from bahlily_storage import db
from bahlily_storage.models import Base, Meeting, Segment, Summary


@pytest.fixture
async def memory_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[AsyncEngine, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def _set_pragma(dbapi_conn: Any, _: Any) -> None:
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()

    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "async_session_factory", factory)
    yield engine
    await engine.dispose()


async def test_summary_roundtrip(memory_engine: AsyncEngine) -> None:
    async with memory_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with db.async_session_factory() as session:
        meeting = Meeting(
            id="meeting-sum",
            status="completed",
            started_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
            segments_count=0,
        )
        summary = Summary(
            id="summary-1",
            meeting_id="meeting-sum",
            title="Standup",
            overview="Short sync.",
            key_points="[]",
            action_items="[]",
            quotes="[]",
            provider="openai",
            model="gpt-4o",
            created_at=datetime.datetime(2026, 1, 1, 1, 0, tzinfo=datetime.UTC),
        )
        session.add(meeting)
        session.add(summary)
        await session.commit()

    async with db.async_session_factory() as session:
        fetched = await session.get(Summary, "summary-1")
        assert fetched is not None
        assert fetched.title == "Standup"
        assert fetched.overview == "Short sync."
        assert fetched.meeting_id == "meeting-sum"
        assert fetched.provider == "openai"


async def test_init_db_creates_tables(memory_engine: AsyncEngine) -> None:
    await db.init_db()

    def _get_table_names(sync_conn: Any) -> set[str]:
        return set(inspect(sync_conn).get_table_names())

    async with memory_engine.connect() as conn:
        tables = await conn.run_sync(_get_table_names)
    assert {"meetings", "segments", "summaries"}.issubset(tables)


async def test_get_session_yields_session(memory_engine: AsyncEngine) -> None:
    sessions: list[AsyncSession] = []
    async for session in db.get_session():
        sessions.append(session)
    assert len(sessions) == 1
    assert isinstance(sessions[0], AsyncSession)


async def test_foreign_key_pragma_enforced(memory_engine: AsyncEngine) -> None:
    await db.init_db()
    async with db.async_session_factory() as session:
        orphan = Segment(
            meeting_id="does-not-exist",
            segment_id=0,
            text="orphan",
            engine="whisper",
            model_name="tiny",
            audio_start_time=0.0,
            audio_end_time=1.0,
            is_partial=False,
            trace_id="t-orphan",
        )
        session.add(orphan)
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_concurrency_pragmas_in_effect_on_file_db(tmp_path: Path) -> None:
    """WAL + busy_timeout must be set, or concurrent writers hit 'database is locked'."""
    engine = db._make_engine(f"sqlite+aiosqlite:///{tmp_path / 'pragma.db'}")
    try:
        async with engine.connect() as conn:
            journal_mode = (await conn.exec_driver_sql("PRAGMA journal_mode")).scalar_one()
            busy_timeout = (await conn.exec_driver_sql("PRAGMA busy_timeout")).scalar_one()
            foreign_keys = (await conn.exec_driver_sql("PRAGMA foreign_keys")).scalar_one()
    finally:
        await engine.dispose()

    assert str(journal_mode).lower() == "wal"
    assert busy_timeout == db.BUSY_TIMEOUT_MS
    assert foreign_keys == 1


async def test_concurrent_writers_do_not_deadlock(tmp_path: Path) -> None:
    """Two independent engines writing the same file must not raise 'database is locked'."""
    url = f"sqlite+aiosqlite:///{tmp_path / 'concurrent.db'}"
    writer_a = db._make_engine(url)
    writer_b = db._make_engine(url)
    try:
        async with writer_a.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async def write(eng: AsyncEngine, prefix: str) -> None:
            factory = async_sessionmaker(eng, expire_on_commit=False)
            for i in range(10):
                async with factory() as s:
                    s.add(
                        Meeting(
                            id=f"{prefix}-{i}",
                            status="recording",
                            started_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
                            segments_count=0,
                        )
                    )
                    await s.commit()

        await asyncio.gather(write(writer_a, "a"), write(writer_b, "b"))

        async with writer_a.connect() as conn:
            total = (await conn.exec_driver_sql("SELECT count(*) FROM meetings")).scalar_one()
        assert total == 20
    finally:
        await writer_a.dispose()
        await writer_b.dispose()
