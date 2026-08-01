from __future__ import annotations

from sqlalchemy import CursorResult, select, update
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
            select(Meeting)
            .order_by(Meeting.started_at.desc(), Meeting.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    _UPDATABLE_FIELDS = frozenset({"title", "status", "ended_at", "segments_count"})

    async def update(self, meeting_id: str, **fields: object) -> Meeting | None:
        unknown = set(fields) - self._UPDATABLE_FIELDS
        if unknown:
            raise ValueError(f"unsupported Meeting field(s): {sorted(unknown)}")
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

    async def add_segments_count(self, meeting_id: str, delta: int) -> None:
        """Atomically add `delta` to `segments_count`, in SQL rather than a
        read-modify-write — a caller holding a stale in-memory `Meeting` (e.g.
        loaded before a concurrent write landed) would otherwise overwrite the
        other write's count instead of adding to it."""
        await self._s.execute(
            update(Meeting)
            .where(Meeting.id == meeting_id)
            .values(segments_count=Meeting.segments_count + delta)
        )

    async def increment_segments_count(self, meeting_id: str) -> None:
        await self.add_segments_count(meeting_id, 1)

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

        Determines insert-vs-update from the outcome of an atomic
        `INSERT ... ON CONFLICT DO NOTHING`, rather than a preliminary SELECT:
        a SELECT-then-INSERT is not atomic, so two sessions racing on the same
        `(meeting_id, segment_id)` could both observe "absent" and both report
        a genuine insert, double-counting `segments_count` even though only one
        row was actually created.
        """
        insert_stmt = (
            sqlite_insert(Segment)
            .values(**data)
            .on_conflict_do_nothing(
                index_elements=["meeting_id", "segment_id"],
            )
        )
        result = await self._s.execute(insert_stmt)
        assert isinstance(result, CursorResult)
        inserted = result.rowcount == 1
        if not inserted:
            update_cols = {k: v for k, v in data.items() if k not in ("meeting_id", "segment_id")}
            await self._s.execute(
                update(Segment)
                .where(
                    Segment.meeting_id == data["meeting_id"],
                    Segment.segment_id == data["segment_id"],
                )
                .values(**update_cols)
            )
        return inserted

    async def upsert_batch(self, rows: list[dict[str, object]]) -> int:
        """Upsert many segments in two batched statements; returns how many
        were genuine inserts.

        Every row must have the same set of keys: the update-column list is
        derived from `rows[0]` alone, and the batched SQLite `VALUES` clause
        assumes a single, homogeneous column set across all rows.

        A per-row Python loop over `upsert()` would issue up to two DB
        round-trips per row; this does it in exactly two round-trips total,
        regardless of batch size:

        1. A single `INSERT ... ON CONFLICT DO NOTHING RETURNING` — rows that
           already exist are silently skipped, so the returned keys are
           exactly the genuine inserts.
        2. A single `INSERT ... ON CONFLICT DO UPDATE` applying every row's
           values, which updates whichever rows conflicted in step 1.
        """
        if not rows:
            return 0

        index_elements = ("meeting_id", "segment_id")

        insert_only = (
            sqlite_insert(Segment)
            .values(rows)
            .on_conflict_do_nothing(index_elements=index_elements)
            .returning(Segment.meeting_id, Segment.segment_id)
        )
        inserted_count = len((await self._s.execute(insert_only)).all())

        upsert_stmt = sqlite_insert(Segment).values(rows)
        update_cols = {
            col: upsert_stmt.excluded[col] for col in rows[0] if col not in index_elements
        }
        upsert_stmt = upsert_stmt.on_conflict_do_update(
            index_elements=index_elements, set_=update_cols
        )
        await self._s.execute(upsert_stmt)

        return inserted_count

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
