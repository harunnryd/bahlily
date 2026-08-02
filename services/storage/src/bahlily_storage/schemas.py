from __future__ import annotations

import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CreateMeetingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str | None = None
    language: str | None = None
    started_at: datetime.datetime | None = None


class PatchMeetingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    status: str | None = None
    ended_at: datetime.datetime | None = None
    recording_path: str | None = None
    diarization_status: str | None = None


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
    recording_path: str | None
    diarization_status: str
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
    speaker_cluster_label: str | None
    speaker_profile_id: str | None


class BatchSegmentItem(BaseModel):
    segment_id: int = Field(ge=0)
    text: str
    confidence: float | None = None
    engine: str
    model_name: str
    audio_start_time: float = Field(ge=0)
    audio_end_time: float = Field(ge=0)
    language: str | None = None
    is_partial: bool
    trace_id: str
    speaker_cluster_label: str | None = None
    speaker_profile_id: str | None = None

    @model_validator(mode="after")
    def _check_audio_range(self) -> BatchSegmentItem:
        if self.audio_end_time < self.audio_start_time:
            raise ValueError("audio_end_time must not be earlier than audio_start_time")
        return self


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


class TemplateExample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input: str = Field(min_length=1)
    output: str = Field(min_length=1)


class CreateTemplateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    version: str = "1.0.0"
    system_prompt: str = Field(min_length=1)
    focus_instructions: str | None = None
    few_shot_examples: list[TemplateExample] = []


class PatchTemplateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    version: str | None = None
    system_prompt: str | None = Field(default=None, min_length=1)
    focus_instructions: str | None = None
    few_shot_examples: list[TemplateExample] | None = None


class TemplateResponse(BaseModel):
    id: str
    name: str
    version: str
    system_prompt: str
    focus_instructions: str | None
    few_shot_examples: list[TemplateExample]
    created_at: datetime.datetime
    updated_at: datetime.datetime


class CreateSpeakerProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    voice_embedding: list[float] = Field(min_length=1)


class PatchSpeakerProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1)
    voice_embedding: list[float] | None = Field(default=None, min_length=1)


class SpeakerProfileResponse(BaseModel):
    id: str
    name: str
    voice_embedding: list[float]
    created_at: datetime.datetime
    updated_at: datetime.datetime


class MatchSpeakerProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    voice_embedding: list[float] = Field(min_length=1)


class MatchSpeakerProfileResponse(BaseModel):
    profile: SpeakerProfileResponse | None
