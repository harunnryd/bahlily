from __future__ import annotations

import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from bahlily_storage.models import Meeting, Summary
from bahlily_storage.repos import MeetingRepo, SegmentRepo, SummaryRepo


def _meeting(id: str = "m1") -> Meeting:
    return Meeting(
        id=id,
        status="recording",
        started_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        segments_count=0,
    )


async def test_meeting_create_and_get(session: AsyncSession) -> None:
    repo = MeetingRepo(session)
    await repo.create(_meeting())
    await session.commit()
    fetched = await repo.get("m1")
    assert fetched is not None
    assert fetched.id == "m1"


async def test_meeting_not_found_returns_none(session: AsyncSession) -> None:
    repo = MeetingRepo(session)
    assert await repo.get("nonexistent") is None


async def test_meeting_update_status(session: AsyncSession) -> None:
    repo = MeetingRepo(session)
    await repo.create(_meeting())
    await session.commit()
    updated = await repo.update("m1", status="stopped")
    assert updated is not None
    assert updated.status == "stopped"


async def test_meeting_delete(session: AsyncSession) -> None:
    repo = MeetingRepo(session)
    await repo.create(_meeting())
    await session.commit()
    deleted = await repo.delete("m1")
    assert deleted is True
    assert await repo.get("m1") is None


async def test_meeting_increment_segments_count(session: AsyncSession) -> None:
    repo = MeetingRepo(session)
    await repo.create(_meeting())
    await session.commit()
    await repo.increment_segments_count("m1")
    await session.commit()
    m = await repo.get("m1")
    assert m is not None
    assert m.segments_count == 1


async def test_meeting_list_all(session: AsyncSession) -> None:
    repo = MeetingRepo(session)
    # Create three meetings with different started_at times
    m1 = Meeting(
        id="m1",
        status="recording",
        started_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        segments_count=0,
    )
    m2 = Meeting(
        id="m2",
        status="recording",
        started_at=datetime.datetime(2026, 1, 3, tzinfo=datetime.UTC),
        segments_count=0,
    )
    m3 = Meeting(
        id="m3",
        status="recording",
        started_at=datetime.datetime(2026, 1, 2, tzinfo=datetime.UTC),
        segments_count=0,
    )
    await repo.create(m1)
    await repo.create(m2)
    await repo.create(m3)
    await session.commit()

    # Test ordering by started_at DESC
    all_meetings = await repo.list_all()
    assert len(all_meetings) == 3
    assert [m.id for m in all_meetings] == ["m2", "m3", "m1"]

    # Test limit
    limited = await repo.list_all(limit=2)
    assert len(limited) == 2
    assert [m.id for m in limited] == ["m2", "m3"]

    # Test offset
    offset_meetings = await repo.list_all(limit=2, offset=1)
    assert len(offset_meetings) == 2
    assert [m.id for m in offset_meetings] == ["m3", "m1"]


async def test_meeting_update_engine_metadata(session: AsyncSession) -> None:
    repo = MeetingRepo(session)
    await repo.create(_meeting())
    await session.commit()

    # Update engine metadata with specific values
    await repo.update_engine_metadata("m1", engine="whisper", model_name="base", language="en")
    await session.commit()

    # Fetch and verify all three fields were persisted
    m = await repo.get("m1")
    assert m is not None
    assert m.engine == "whisper"
    assert m.model_name == "base"
    assert m.language == "en"


async def test_segment_upsert_idempotent(session: AsyncSession) -> None:
    repo_m = MeetingRepo(session)
    await repo_m.create(_meeting())
    await session.commit()

    repo_s = SegmentRepo(session)
    data = dict(
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
    await repo_s.upsert(data)
    await session.commit()
    await repo_s.upsert(data)  # second upsert must not raise
    await session.commit()
    segments = await repo_s.list_by_meeting("m1")
    assert len(segments) == 1
    assert segments[0].text == "hello"


async def test_segment_upsert_updates_existing(session: AsyncSession) -> None:
    repo_m = MeetingRepo(session)
    await repo_m.create(_meeting())
    await session.commit()

    repo_s = SegmentRepo(session)
    base = dict(
        meeting_id="m1",
        segment_id=0,
        engine="whisper",
        model_name="tiny",
        audio_start_time=0.0,
        audio_end_time=1.0,
        is_partial=False,
        trace_id="t1",
    )
    await repo_s.upsert({**base, "text": "original"})
    await session.commit()
    await repo_s.upsert({**base, "text": "updated"})
    await session.commit()
    segments = await repo_s.list_by_meeting("m1")
    assert segments[0].text == "updated"


async def test_segment_list_ordered(session: AsyncSession) -> None:
    repo_m = MeetingRepo(session)
    await repo_m.create(_meeting())
    await session.commit()

    repo_s = SegmentRepo(session)
    base = dict(
        meeting_id="m1",
        engine="whisper",
        model_name="tiny",
        audio_start_time=0.0,
        audio_end_time=1.0,
        is_partial=False,
        trace_id="t",
    )
    await repo_s.upsert({**base, "segment_id": 2, "text": "second"})
    await repo_s.upsert({**base, "segment_id": 0, "text": "first"})
    await repo_s.upsert({**base, "segment_id": 1, "text": "middle"})
    await session.commit()
    segments = await repo_s.list_by_meeting("m1")
    assert [s.segment_id for s in segments] == [0, 1, 2]


async def test_summary_create_and_get(session: AsyncSession) -> None:
    repo_m = MeetingRepo(session)
    await repo_m.create(_meeting())
    await session.commit()

    import json
    import uuid

    repo_s = SummaryRepo(session)
    summary = Summary(
        id=str(uuid.uuid4()),
        meeting_id="m1",
        title="Test Meeting",
        overview="A test.",
        key_points=json.dumps(["point 1"]),
        action_items=json.dumps([]),
        quotes=json.dumps([]),
        provider="anthropic",
        model="claude-sonnet-4-6",
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
    )
    await repo_s.create(summary)
    await session.commit()
    fetched = await repo_s.get_by_meeting("m1")
    assert fetched is not None
    assert fetched.title == "Test Meeting"


async def test_summary_missing_returns_none(session: AsyncSession) -> None:
    repo_s = SummaryRepo(session)
    assert await repo_s.get_by_meeting("nonexistent") is None
