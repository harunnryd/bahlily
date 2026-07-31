from __future__ import annotations

import datetime
from typing import Optional

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


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
    started_at: Mapped[datetime.datetime]
    ended_at: Mapped[Optional[datetime.datetime]] = mapped_column(nullable=True, default=None)
    segments_count: Mapped[int] = mapped_column(default=0)

    segments: Mapped[list[Segment]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan", lazy="selectin"
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
    created_at: Mapped[datetime.datetime]

    meeting: Mapped[Meeting] = relationship(back_populates="summary")
