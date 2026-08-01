from __future__ import annotations

import datetime
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

_XML_INVALID_CONTROL_CHARS = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")


def _reject_xml_invalid_control_chars(value: str) -> str:
    if _XML_INVALID_CONTROL_CHARS.search(value):
        raise ValueError("must not contain XML-incompatible control characters")
    return value


class ActionItem(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    description: str = Field(min_length=1)
    owner: str | None = None
    due_date: str | None = None

    @field_validator("description")
    @classmethod
    def _validate_description(cls, value: str) -> str:
        return _reject_xml_invalid_control_chars(value)

    @field_validator("owner", "due_date")
    @classmethod
    def _validate_optional_text(cls, value: str | None) -> str | None:
        return value if value is None else _reject_xml_invalid_control_chars(value)


class Quote(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    speaker: str | None = None
    text: str = Field(min_length=1)
    segment_id: int

    @field_validator("text")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        return _reject_xml_invalid_control_chars(value)

    @field_validator("speaker")
    @classmethod
    def _validate_speaker(cls, value: str | None) -> str | None:
        return value if value is None else _reject_xml_invalid_control_chars(value)


class ExportRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1)
    overview: str = Field(min_length=1)
    key_points: list[str] = []
    action_items: list[ActionItem] = []
    quotes: list[Quote] = []
    created_at: datetime.datetime

    @field_validator("title", "overview")
    @classmethod
    def _validate_no_control_chars(cls, value: str) -> str:
        return _reject_xml_invalid_control_chars(value)

    @field_validator("key_points")
    @classmethod
    def _validate_key_points(cls, value: list[str]) -> list[str]:
        for point in value:
            if not point:
                raise ValueError("key points must not be empty")
            _reject_xml_invalid_control_chars(point)
        return value
