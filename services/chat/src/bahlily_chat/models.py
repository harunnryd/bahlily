from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TranscriptSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    segment_id: int
    speaker: str | None = None
    start_time: float | None = None
    end_time: float | None = None


class IngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segments: list[TranscriptSegment] = Field(min_length=1)


class IngestResponse(BaseModel):
    meeting_id: str
    segments_indexed: int


class ChatTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)
    meeting_id: str | None = None
    history: list[ChatTurn] = []
    provider: str
    model: str


class Citation(BaseModel):
    meeting_id: str
    segment_id: int
    text: str
    start_time: float | None
    end_time: float | None


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation]
