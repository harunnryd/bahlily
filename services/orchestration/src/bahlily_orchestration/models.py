from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class TranscriptSegment(BaseModel):
    text: str
    segment_id: int
    speaker: str | None = None
    start_time: float | None = None
    end_time: float | None = None
    language: str | None = None


class FewShotExample(BaseModel):
    input: str
    output: str


class TemplateSpec(BaseModel):
    name: str
    version: str
    system_prompt: str
    focus_instructions: str | None = None
    few_shot_examples: list[FewShotExample] = []
    id: str | None = None
    source: Literal["bundled", "custom"] | None = None


class ActionItem(BaseModel):
    description: str
    owner: str | None = None
    due_date: str | None = None


class Quote(BaseModel):
    speaker: str | None = None
    text: str
    segment_id: int


class StructuredSummary(BaseModel):
    title: str
    overview: str
    key_points: list[str]
    action_items: list[ActionItem]
    quotes: list[Quote] = []


class SummarizeRequest(BaseModel):
    segments: list[TranscriptSegment] = Field(min_length=1)
    template: TemplateSpec
    provider: str
    model: str


class SummarizeResponse(BaseModel):
    summary: StructuredSummary
    attempts: int
    provider: str
    model: str
