from __future__ import annotations

import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from bahlily_storage.models import Meeting, SpeakerProfile, Summary, SummaryTemplate
from bahlily_storage.repos import (
    MeetingRepo,
    SegmentRepo,
    SpeakerProfileRepo,
    SummaryRepo,
    TemplateRepo,
)


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

    all_meetings = await repo.list_all()
    assert len(all_meetings) == 3
    assert [m.id for m in all_meetings] == ["m2", "m3", "m1"]

    limited = await repo.list_all(limit=2)
    assert len(limited) == 2
    assert [m.id for m in limited] == ["m2", "m3"]

    offset_meetings = await repo.list_all(limit=2, offset=1)
    assert len(offset_meetings) == 2
    assert [m.id for m in offset_meetings] == ["m3", "m1"]


async def test_meeting_list_all_breaks_started_at_ties_by_id(session: AsyncSession) -> None:
    """Meetings sharing a `started_at` need a deterministic tiebreaker, or
    pagination could show the same row twice (or skip one) across pages
    depending on how SQLite happens to order otherwise-equal rows."""
    repo = MeetingRepo(session)
    same_time = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    for meeting_id in ("m1", "m2", "m3"):
        await repo.create(
            Meeting(id=meeting_id, status="recording", started_at=same_time, segments_count=0)
        )
    await session.commit()

    all_meetings = await repo.list_all()
    assert [m.id for m in all_meetings] == ["m3", "m2", "m1"]

    limited = await repo.list_all(limit=2)
    assert [m.id for m in limited] == ["m3", "m2"]

    offset_meetings = await repo.list_all(limit=2, offset=1)
    assert [m.id for m in offset_meetings] == ["m2", "m1"]


async def test_meeting_update_engine_metadata(session: AsyncSession) -> None:
    repo = MeetingRepo(session)
    await repo.create(_meeting())
    await session.commit()

    await repo.update_engine_metadata("m1", engine="whisper", model_name="base", language="en")
    await session.commit()

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


async def test_upsert_reports_insert_then_update(session: AsyncSession) -> None:
    session.add(
        Meeting(
            id="m-up",
            status="recording",
            started_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
            segments_count=0,
        )
    )
    await session.flush()

    repo = SegmentRepo(session)
    row: dict[str, object] = {
        "meeting_id": "m-up",
        "segment_id": 0,
        "text": "first",
        "confidence": None,
        "engine": "whisper",
        "model_name": "tiny",
        "audio_start_time": 0.0,
        "audio_end_time": 1.0,
        "language": None,
        "is_partial": False,
        "trace_id": "t1",
    }
    assert await repo.upsert(row) is True
    assert await repo.upsert({**row, "text": "second"}) is False

    segments = await repo.list_by_meeting("m-up")
    assert len(segments) == 1
    assert segments[0].text == "second"


async def test_upsert_batch_counts_only_new_rows(session: AsyncSession) -> None:
    session.add(
        Meeting(
            id="m-batch",
            status="recording",
            started_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
            segments_count=0,
        )
    )
    await session.flush()

    repo = SegmentRepo(session)

    def _row(segment_id: int) -> dict[str, object]:
        return {
            "meeting_id": "m-batch",
            "segment_id": segment_id,
            "text": f"s{segment_id}",
            "confidence": None,
            "engine": "whisper",
            "model_name": "tiny",
            "audio_start_time": 0.0,
            "audio_end_time": 1.0,
            "language": None,
            "is_partial": False,
            "trace_id": "t",
        }

    assert await repo.upsert_batch([_row(0), _row(1)]) == 2
    assert await repo.upsert_batch([_row(1), _row(2)]) == 1


async def test_upsert_batch_mixes_inserts_and_updates_in_one_call(
    session: AsyncSession,
) -> None:
    """A single batch containing both a new row and an already-existing row
    must report only the genuine insert, and must still apply the new
    values to the existing row (not skip it)."""
    session.add(
        Meeting(
            id="m-mixed",
            status="recording",
            started_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
            segments_count=0,
        )
    )
    await session.flush()

    def _row(segment_id: int, text: str) -> dict[str, object]:
        return {
            "meeting_id": "m-mixed",
            "segment_id": segment_id,
            "text": text,
            "confidence": None,
            "engine": "whisper",
            "model_name": "tiny",
            "audio_start_time": 0.0,
            "audio_end_time": 1.0,
            "language": None,
            "is_partial": False,
            "trace_id": "t",
        }

    repo = SegmentRepo(session)
    assert await repo.upsert_batch([_row(0, "original")]) == 1

    assert await repo.upsert_batch([_row(0, "updated"), _row(1, "brand-new")]) == 1

    segments = await repo.list_by_meeting("m-mixed")
    assert [(s.segment_id, s.text) for s in segments] == [(0, "updated"), (1, "brand-new")]


async def test_upsert_batch_uses_two_round_trips_regardless_of_size(
    session: AsyncSession,
) -> None:
    """Regression: a per-row Python loop would issue up to 2 round-trips per
    row; the batched implementation must issue exactly 2 total, however many
    rows are in the batch."""
    from sqlalchemy import event

    session.add(
        Meeting(
            id="m-rt",
            status="recording",
            started_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
            segments_count=0,
        )
    )
    await session.flush()

    def _row(segment_id: int) -> dict[str, object]:
        return {
            "meeting_id": "m-rt",
            "segment_id": segment_id,
            "text": f"s{segment_id}",
            "confidence": None,
            "engine": "whisper",
            "model_name": "tiny",
            "audio_start_time": 0.0,
            "audio_end_time": 1.0,
            "language": None,
            "is_partial": False,
            "trace_id": "t",
        }

    statement_count = 0

    def _count_statements(*args: object, **kwargs: object) -> None:
        nonlocal statement_count
        statement_count += 1

    sync_engine = session.get_bind().engine
    event.listen(sync_engine, "before_cursor_execute", _count_statements)
    try:
        rows = [_row(i) for i in range(20)]
        assert await SegmentRepo(session).upsert_batch(rows) == 20
    finally:
        event.remove(sync_engine, "before_cursor_execute", _count_statements)

    assert statement_count == 2


async def test_meeting_update_rejects_unknown_field(session: AsyncSession) -> None:
    repo = MeetingRepo(session)
    await repo.create(_meeting())
    await session.commit()

    with pytest.raises(ValueError):
        await repo.update("m1", id="not-allowed")


async def test_meeting_delete_cascades_to_segments(session: AsyncSession) -> None:
    """Regression: `Meeting.segments` is lazy-loaded (not eager `selectin`), so
    the cascade delete must still remove child rows without a prior explicit
    load — otherwise the `segments.meeting_id` foreign key would reject the
    delete.
    """
    repo_m = MeetingRepo(session)
    await repo_m.create(_meeting())
    await session.commit()

    repo_s = SegmentRepo(session)
    await repo_s.upsert(
        {
            "meeting_id": "m1",
            "segment_id": 0,
            "text": "hello",
            "confidence": None,
            "engine": "whisper",
            "model_name": "tiny",
            "audio_start_time": 0.0,
            "audio_end_time": 1.0,
            "language": None,
            "is_partial": False,
            "trace_id": "t1",
        }
    )
    await session.commit()

    assert await repo_m.delete("m1") is True
    await session.commit()

    assert await repo_s.list_by_meeting("m1") == []


def _template(id: str = "tmpl-1", name: str = "Custom") -> SummaryTemplate:
    now = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    return SummaryTemplate(
        id=id,
        name=name,
        version="1.0.0",
        system_prompt="Summarize this.",
        focus_instructions=None,
        few_shot_examples="[]",
        created_at=now,
        updated_at=now,
    )


async def test_template_create_and_get(session: AsyncSession) -> None:
    repo = TemplateRepo(session)
    await repo.create(_template())
    await session.commit()
    fetched = await repo.get("tmpl-1")
    assert fetched is not None
    assert fetched.name == "Custom"


async def test_template_not_found_returns_none(session: AsyncSession) -> None:
    repo = TemplateRepo(session)
    assert await repo.get("nonexistent") is None


async def test_template_list_all_orders_and_paginates(session: AsyncSession) -> None:
    repo = TemplateRepo(session)
    same_time = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    for template_id in ("t1", "t2", "t3"):
        await repo.create(
            SummaryTemplate(
                id=template_id,
                name="Custom",
                version="1.0.0",
                system_prompt="P",
                few_shot_examples="[]",
                created_at=same_time,
                updated_at=same_time,
            )
        )
    await session.commit()

    all_templates = await repo.list_all()
    assert [t.id for t in all_templates] == ["t3", "t2", "t1"]

    limited = await repo.list_all(limit=2)
    assert [t.id for t in limited] == ["t3", "t2"]

    offset_templates = await repo.list_all(limit=2, offset=1)
    assert [t.id for t in offset_templates] == ["t2", "t1"]


async def test_template_update(session: AsyncSession) -> None:
    repo = TemplateRepo(session)
    await repo.create(_template())
    await session.commit()
    updated = await repo.update("tmpl-1", name="Renamed", system_prompt="New prompt.")
    assert updated is not None
    assert updated.name == "Renamed"
    assert updated.system_prompt == "New prompt."


async def test_template_update_not_found_returns_none(session: AsyncSession) -> None:
    repo = TemplateRepo(session)
    assert await repo.update("nonexistent", name="X") is None


async def test_template_update_rejects_unknown_field(session: AsyncSession) -> None:
    repo = TemplateRepo(session)
    await repo.create(_template())
    await session.commit()
    with pytest.raises(ValueError):
        await repo.update("tmpl-1", id="not-allowed")


async def test_template_delete(session: AsyncSession) -> None:
    repo = TemplateRepo(session)
    await repo.create(_template())
    await session.commit()
    deleted = await repo.delete("tmpl-1")
    assert deleted is True
    assert await repo.get("tmpl-1") is None


async def test_template_delete_not_found_returns_false(session: AsyncSession) -> None:
    repo = TemplateRepo(session)
    assert await repo.delete("nonexistent") is False


async def test_speaker_profile_create_and_get(session: AsyncSession) -> None:
    repo = SpeakerProfileRepo(session)
    now = datetime.datetime.now(datetime.UTC)
    profile = SpeakerProfile(
        id="p1", name="Alice", voice_embedding="[0.1, 0.2]", created_at=now, updated_at=now
    )
    await repo.create(profile)
    await session.commit()

    fetched = await repo.get("p1")
    assert fetched is not None
    assert fetched.name == "Alice"


async def test_speaker_profile_not_found_returns_none(session: AsyncSession) -> None:
    repo = SpeakerProfileRepo(session)
    assert await repo.get("missing") is None


async def test_speaker_profile_list_all_orders_and_paginates(session: AsyncSession) -> None:
    repo = SpeakerProfileRepo(session)
    now = datetime.datetime.now(datetime.UTC)
    for i in range(3):
        await repo.create(
            SpeakerProfile(
                id=f"p{i}",
                name=f"Speaker {i}",
                voice_embedding="[]",
                created_at=now + datetime.timedelta(seconds=i),
                updated_at=now,
            )
        )
    await session.commit()

    page = await repo.list_all(limit=2, offset=0)
    assert [p.id for p in page] == ["p2", "p1"]


async def test_speaker_profile_update(session: AsyncSession) -> None:
    repo = SpeakerProfileRepo(session)
    now = datetime.datetime.now(datetime.UTC)
    await repo.create(
        SpeakerProfile(id="p1", name="Alice", voice_embedding="[]", created_at=now, updated_at=now)
    )
    await session.commit()

    updated = await repo.update("p1", name="Alicia")
    assert updated is not None
    assert updated.name == "Alicia"


async def test_speaker_profile_update_rejects_unknown_field(session: AsyncSession) -> None:
    repo = SpeakerProfileRepo(session)
    with pytest.raises(ValueError, match="unsupported"):
        await repo.update("p1", nonexistent_field="x")


async def test_speaker_profile_delete(session: AsyncSession) -> None:
    repo = SpeakerProfileRepo(session)
    now = datetime.datetime.now(datetime.UTC)
    await repo.create(
        SpeakerProfile(id="p1", name="Alice", voice_embedding="[]", created_at=now, updated_at=now)
    )
    await session.commit()

    assert await repo.delete("p1") is True
    assert await repo.get("p1") is None


async def test_speaker_profile_get_by_name_returns_matching_or_none(
    session: AsyncSession,
) -> None:
    repo = SpeakerProfileRepo(session)
    p1 = SpeakerProfile(
        id="p1",
        name="Alice",
        voice_embedding="[]",
        created_at=datetime.datetime.now(datetime.UTC),
        updated_at=datetime.datetime.now(datetime.UTC),
    )
    await repo.create(p1)
    found = await repo.get_by_name("Alice")
    assert found is not None and found.id == "p1"
    assert await repo.get_by_name("Bob") is None
