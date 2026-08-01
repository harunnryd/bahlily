from __future__ import annotations

import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator


class UtcDateTime(TypeDecorator[datetime.datetime]):
    """A `DateTime(timezone=True)` that actually round-trips tz-aware values.

    SQLite has no native datetime type, and SQLAlchemy's SQLite storage format
    for `DateTime` carries no UTC offset — so a tz-aware value written in comes
    back naive, and any client that isn't already assuming UTC reads the wrong
    timestamp. This decorator normalizes aware values to UTC on the way in and
    re-attaches `datetime.UTC` on the way out.

    Naive values are assumed to already be UTC (the service always writes
    `datetime.now(datetime.UTC)`), which also makes rows written before this
    type existed read back correctly.
    """

    impl = sa.DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(
        self, value: datetime.datetime | None, dialect: Dialect
    ) -> datetime.datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=datetime.UTC)
        return value.astimezone(datetime.UTC)

    def process_result_value(
        self, value: datetime.datetime | None, dialect: Dialect
    ) -> datetime.datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=datetime.UTC)
        return value.astimezone(datetime.UTC)


class Base(DeclarativeBase):
    pass


class Meeting(Base):
    __tablename__ = "meetings"

    id: Mapped[str] = mapped_column(primary_key=True)
    title: Mapped[Optional[str]] = mapped_column(nullable=True, default=None)
    status: Mapped[str] = mapped_column(default="recording")
    language: Mapped[Optional[str]] = mapped_column(nullable=True, default=None)
    engine: Mapped[Optional[str]] = mapped_column(nullable=True, default=None)
    model_name: Mapped[Optional[str]] = mapped_column(nullable=True, default=None)
    started_at: Mapped[datetime.datetime] = mapped_column(UtcDateTime())
    ended_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        UtcDateTime(), nullable=True, default=None
    )
    segments_count: Mapped[int] = mapped_column(default=0)

    segments: Mapped[list[Segment]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan"
    )
    summary: Mapped[Optional[Summary]] = relationship(
        back_populates="meeting",
        cascade="all, delete-orphan",
        uselist=False,
        lazy="selectin",
    )


class Segment(Base):
    __tablename__ = "segments"
    __table_args__ = (
        UniqueConstraint("meeting_id", "segment_id", name="uq_segments_meeting_segment"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    meeting_id: Mapped[str] = mapped_column(ForeignKey("meetings.id"), index=True)
    segment_id: Mapped[int]
    text: Mapped[str]
    confidence: Mapped[Optional[float]] = mapped_column(nullable=True, default=None)
    engine: Mapped[str]
    model_name: Mapped[str]
    audio_start_time: Mapped[float]
    audio_end_time: Mapped[float]
    language: Mapped[Optional[str]] = mapped_column(nullable=True, default=None)
    is_partial: Mapped[bool]
    trace_id: Mapped[str]

    meeting: Mapped[Meeting] = relationship(back_populates="segments")


class Summary(Base):
    __tablename__ = "summaries"

    id: Mapped[str] = mapped_column(primary_key=True)
    meeting_id: Mapped[str] = mapped_column(ForeignKey("meetings.id"), unique=True)
    title: Mapped[str]
    overview: Mapped[str]
    key_points: Mapped[str]
    action_items: Mapped[str]
    quotes: Mapped[str]
    provider: Mapped[str]
    model: Mapped[str]
    created_at: Mapped[datetime.datetime] = mapped_column(UtcDateTime())

    meeting: Mapped[Meeting] = relationship(back_populates="summary")
