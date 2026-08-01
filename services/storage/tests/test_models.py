from __future__ import annotations

import datetime
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bahlily_storage.models import Base, Meeting, Segment, Summary


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


async def test_meeting_datetimes_roundtrip_timezone_aware(session: AsyncSession) -> None:
    started = datetime.datetime(2026, 1, 1, 12, 0, tzinfo=datetime.UTC)
    ended = datetime.datetime(2026, 1, 1, 13, 30, tzinfo=datetime.UTC)
    session.add(
        Meeting(id="tz-1", status="completed", started_at=started, ended_at=ended, segments_count=0)
    )
    await session.commit()
    session.expunge_all()

    fetched = await session.get(Meeting, "tz-1")
    assert fetched is not None
    assert fetched.started_at.utcoffset() is not None
    assert fetched.started_at == started
    assert fetched.ended_at is not None
    assert fetched.ended_at.utcoffset() is not None
    assert fetched.ended_at == ended


async def test_meeting_non_utc_offset_preserved_as_instant(session: AsyncSession) -> None:
    """A non-UTC aware value must come back as the same instant, still aware."""
    plus7 = datetime.timezone(datetime.timedelta(hours=7))
    started = datetime.datetime(2026, 1, 1, 19, 0, tzinfo=plus7)
    session.add(Meeting(id="tz-2", status="recording", started_at=started, segments_count=0))
    await session.commit()
    session.expunge_all()

    fetched = await session.get(Meeting, "tz-2")
    assert fetched is not None
    assert fetched.started_at.utcoffset() is not None
    assert fetched.started_at == started


async def test_summary_created_at_roundtrips_timezone_aware(session: AsyncSession) -> None:
    created = datetime.datetime(2026, 2, 3, 4, 5, 6, tzinfo=datetime.UTC)
    session.add(
        Meeting(
            id="tz-3",
            status="completed",
            started_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
            segments_count=0,
        )
    )
    await session.flush()
    session.add(
        Summary(
            id="s-tz",
            meeting_id="tz-3",
            title="T",
            overview="O",
            key_points="[]",
            action_items="[]",
            quotes="[]",
            provider="p",
            model="m",
            created_at=created,
        )
    )
    await session.commit()
    session.expunge_all()

    fetched = await session.get(Summary, "s-tz")
    assert fetched is not None
    assert fetched.created_at.utcoffset() is not None
    assert fetched.created_at == created
