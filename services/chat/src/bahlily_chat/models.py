from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TranscriptSegment(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: str = Field(min_length=1)
    segment_id: int = Field(ge=0)
    speaker: str | None = None
    start_time: float | None = None
    end_time: float | None = None


class IngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segments: list[TranscriptSegment] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_unique_segment_ids(self) -> IngestRequest:
        segment_ids = [s.segment_id for s in self.segments]
        if len(segment_ids) != len(set(segment_ids)):
            raise ValueError("segments must have unique segment_id values")
        return self


class IngestResponse(BaseModel):
    meeting_id: str
    segments_indexed: int


_MAX_MESSAGE_LENGTH = 10_000
_MAX_HISTORY_TURNS = 50


class ChatTurn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=_MAX_MESSAGE_LENGTH)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(min_length=1, max_length=_MAX_MESSAGE_LENGTH)
    meeting_id: str | None = Field(default=None, min_length=1)
    history: list[ChatTurn] = Field(default=[], max_length=_MAX_HISTORY_TURNS)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)


class Citation(BaseModel):
    meeting_id: str
    segment_id: int
    text: str
    start_time: float | None
    end_time: float | None


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation]
