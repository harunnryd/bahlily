from __future__ import annotations

import datetime
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bahlily_storage.models import Base, Meeting, Segment


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def test_meeting_roundtrip(session: AsyncSession) -> None:
    meeting = Meeting(
        id="meeting-1",
        status="recording",
        started_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        segments_count=0,
    )
    session.add(meeting)
    await session.commit()
    fetched = await session.get(Meeting, "meeting-1")
    assert fetched is not None
    assert fetched.status == "recording"
    assert fetched.segments_count == 0


async def test_segment_unique_constraint(session: AsyncSession) -> None:
    meeting = Meeting(
        id="m1",
        status="recording",
        started_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        segments_count=0,
    )
    session.add(meeting)
    await session.flush()
    segment = Segment(
        meeting_id="m1",
        segment_id=0,
        text="hello",
        engine="whisper",
        model_name="tiny",
        audio_start_time=0.0,
        audio_end_time=1.0,
        is_partial=False,
        trace_id="t1",
    )
    session.add(segment)
    await session.commit()
    assert segment.id is not None

    duplicate = Segment(
        meeting_id="m1",
        segment_id=0,
        text="dup",
        engine="whisper",
        model_name="tiny",
        audio_start_time=0.0,
        audio_end_time=1.0,
        is_partial=False,
        trace_id="t2",
    )
    session.add(duplicate)
    with pytest.raises(IntegrityError):
        await session.commit()
