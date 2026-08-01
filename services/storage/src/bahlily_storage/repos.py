from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from bahlily_storage.models import Meeting, Segment, Summary


class MeetingRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def create(self, meeting: Meeting) -> Meeting:
        self._s.add(meeting)
        await self._s.flush()
        return meeting

    async def get(self, meeting_id: str) -> Meeting | None:
        return await self._s.get(Meeting, meeting_id)

    async def list_all(self, limit: int = 20, offset: int = 0) -> list[Meeting]:
        result = await self._s.execute(
            select(Meeting).order_by(Meeting.started_at.desc()).limit(limit).offset(offset)
        )
        return list(result.scalars().all())

    async def update(self, meeting_id: str, **fields: object) -> Meeting | None:
        meeting = await self.get(meeting_id)
        if meeting is None:
            return None
        for key, value in fields.items():
            setattr(meeting, key, value)
        await self._s.flush()
        return meeting

    async def delete(self, meeting_id: str) -> bool:
        meeting = await self.get(meeting_id)
        if meeting is None:
            return False
        await self._s.delete(meeting)
        await self._s.flush()
        return True

    async def increment_segments_count(self, meeting_id: str) -> None:
        await self._s.execute(
            update(Meeting)
            .where(Meeting.id == meeting_id)
            .values(segments_count=Meeting.segments_count + 1)
        )

    async def update_engine_metadata(
        self,
        meeting_id: str,
        engine: str,
        model_name: str,
        language: str | None,
    ) -> None:
        await self._s.execute(
            update(Meeting)
            .where(Meeting.id == meeting_id)
            .values(engine=engine, model_name=model_name, language=language)
        )


class SegmentRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def upsert(self, data: dict[str, object]) -> bool:
        """Insert or update one segment. Returns True only for a genuine INSERT.

        Callers that maintain a running `segments_count` must key off the return
        value: a redelivered `(meeting_id, segment_id)` is an UPDATE and would
        otherwise overcount.
        """
        existing = await self._s.execute(
            select(Segment.id).where(
                Segment.meeting_id == data["meeting_id"],
                Segment.segment_id == data["segment_id"],
            )
        )
        inserted = existing.scalar_one_or_none() is None

        stmt = sqlite_insert(Segment).values(**data)
        update_cols = {k: stmt.excluded[k] for k in data if k not in ("meeting_id", "segment_id")}
        stmt = stmt.on_conflict_do_update(
            index_elements=["meeting_id", "segment_id"],
            set_=update_cols,
        )
        await self._s.execute(stmt)
        return inserted

    async def upsert_batch(self, rows: list[dict[str, object]]) -> int:
        """Upsert many segments; returns how many were genuine inserts."""
        return sum([await self.upsert(row) for row in rows])

    async def list_by_meeting(self, meeting_id: str) -> list[Segment]:
        result = await self._s.execute(
            select(Segment).where(Segment.meeting_id == meeting_id).order_by(Segment.segment_id)
        )
        return list(result.scalars().all())


class SummaryRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def create(self, summary: Summary) -> Summary:
        self._s.add(summary)
        await self._s.flush()
        return summary

    async def get_by_meeting(self, meeting_id: str) -> Summary | None:
        result = await self._s.execute(select(Summary).where(Summary.meeting_id == meeting_id))
        return result.scalar_one_or_none()
