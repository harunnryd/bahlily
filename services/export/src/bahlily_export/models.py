from __future__ import annotations

import datetime

from pydantic import BaseModel, ConfigDict, Field


class ActionItem(BaseModel):
    description: str
    owner: str | None = None
    due_date: str | None = None


class Quote(BaseModel):
    speaker: str | None = None
    text: str
    segment_id: int


class ExportRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1)
    overview: str = Field(min_length=1)
    key_points: list[str] = []
    action_items: list[ActionItem] = []
    quotes: list[Quote] = []
    created_at: datetime.datetime
