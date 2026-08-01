from __future__ import annotations

import pytest
from pydantic import ValidationError

from bahlily_chat.models import (
    ChatRequest,
    ChatResponse,
    ChatTurn,
    Citation,
    IngestRequest,
    IngestResponse,
    TranscriptSegment,
)


def test_transcript_segment_minimal() -> None:
    seg = TranscriptSegment(text="hello", segment_id=1)
    assert seg.speaker is None
    assert seg.start_time is None


def test_ingest_request_requires_at_least_one_segment() -> None:
    with pytest.raises(ValidationError):
        IngestRequest(segments=[])


def test_ingest_request_rejects_duplicate_segment_ids() -> None:
    with pytest.raises(ValidationError):
        IngestRequest(
            segments=[
                TranscriptSegment(text="first", segment_id=1),
                TranscriptSegment(text="second", segment_id=1),
            ]
        )


def test_transcript_segment_strips_whitespace_only_text() -> None:
    with pytest.raises(ValidationError):
        TranscriptSegment(text="   ", segment_id=1)


def test_transcript_segment_rejects_negative_segment_id() -> None:
    with pytest.raises(ValidationError):
        TranscriptSegment(text="hi", segment_id=-1)


def test_ingest_request_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        IngestRequest(
            segments=[TranscriptSegment(text="hi", segment_id=1)],
            extra="nope",  # type: ignore[call-arg]
        )


def test_ingest_response_roundtrip() -> None:
    resp = IngestResponse(meeting_id="m1", segments_indexed=3)
    assert resp.meeting_id == "m1"
    assert resp.segments_indexed == 3


def test_chat_turn_rejects_invalid_role() -> None:
    with pytest.raises(ValidationError):
        ChatTurn(role="system", content="hi")  # type: ignore[arg-type]


def test_chat_turn_rejects_whitespace_only_content() -> None:
    with pytest.raises(ValidationError):
        ChatTurn(role="user", content="   ")


def test_chat_request_defaults() -> None:
    req = ChatRequest(question="What did we decide?", provider="openai", model="gpt-4o-mini")
    assert req.meeting_id is None
    assert req.history == []


def test_chat_request_rejects_empty_question() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(question="", provider="openai", model="gpt-4o-mini")


def test_chat_request_rejects_whitespace_only_question() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(question="   ", provider="openai", model="gpt-4o-mini")


def test_chat_request_rejects_whitespace_only_meeting_id() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(question="hi", meeting_id="   ", provider="openai", model="gpt-4o-mini")


def test_chat_request_rejects_whitespace_only_provider() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(question="hi", provider="   ", model="gpt-4o-mini")


def test_chat_request_rejects_whitespace_only_model() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(question="hi", provider="openai", model="   ")


def test_chat_request_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(
            question="hi",
            provider="openai",
            model="gpt-4o-mini",
            extra="nope",  # type: ignore[call-arg]
        )


def test_chat_response_roundtrip() -> None:
    resp = ChatResponse(
        answer="You decided to ship on Friday.",
        citations=[
            Citation(
                meeting_id="m1",
                segment_id=3,
                text="Let's ship Friday",
                start_time=1.0,
                end_time=2.0,
            )
        ],
    )
    assert resp.citations[0].meeting_id == "m1"
