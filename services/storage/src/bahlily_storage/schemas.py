from __future__ import annotations

import datetime
from typing import Any

from pydantic import BaseModel


class CreateMeetingRequest(BaseModel):
    id: str
    title: str | None = None
    language: str | None = None
    started_at: datetime.datetime | None = None


class PatchMeetingRequest(BaseModel):
    title: str | None = None
    status: str | None = None
    ended_at: datetime.datetime | None = None


class MeetingResponse(BaseModel):
    id: str
    title: str | None
    status: str
    language: str | None
    engine: str | None
    model_name: str | None
    started_at: datetime.datetime
    ended_at: datetime.datetime | None
    segments_count: int
    has_summary: bool


class SegmentResponse(BaseModel):
    segment_id: int
    text: str
    confidence: float | None
    engine: str
    model_name: str
    audio_start_time: float
    audio_end_time: float
    language: str | None
    is_partial: bool
    trace_id: str


class BatchSegmentItem(BaseModel):
    segment_id: int
    text: str
    confidence: float | None = None
    engine: str
    model_name: str
    audio_start_time: float
    audio_end_time: float
    language: str | None = None
    is_partial: bool
    trace_id: str


class BatchSegmentsRequest(BaseModel):
    segments: list[BatchSegmentItem]


class CreateSummaryRequest(BaseModel):
    title: str
    overview: str
    key_points: list[str]
    action_items: list[dict[str, Any]]
    quotes: list[dict[str, Any]] = []
    provider: str
    model: str


class SummaryResponse(BaseModel):
    id: str
    meeting_id: str
    title: str
    overview: str
    key_points: list[str]
    action_items: list[dict[str, Any]]
    quotes: list[dict[str, Any]]
    provider: str
    model: str
    created_at: datetime.datetime
