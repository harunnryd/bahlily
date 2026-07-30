import pytest
from pydantic import ValidationError

from bahlily_orchestration.models import (
    ActionItem,
    Quote,
    StructuredSummary,
    SummarizeRequest,
    SummarizeResponse,
    TemplateSpec,
    TranscriptSegment,
)


def test_transcript_segment_requires_text_and_segment_id() -> None:
    segment = TranscriptSegment(text="Let's ship Friday.", segment_id=0)
    assert segment.speaker is None
    assert segment.start_time is None

    with pytest.raises(ValidationError):
        TranscriptSegment(segment_id=0)  # type: ignore[call-arg]

    with pytest.raises(ValidationError):
        TranscriptSegment(text="Let's ship Friday.")  # type: ignore[call-arg]


def test_transcript_segment_accepts_optional_diarization_fields() -> None:
    segment = TranscriptSegment(
        text="Agreed.",
        segment_id=1,
        speaker="Bob",
        start_time=1.5,
        end_time=2.0,
        language="en",
    )
    assert segment.speaker == "Bob"


def test_template_spec_defaults_to_no_few_shot_examples() -> None:
    template = TemplateSpec(
        name="general",
        version="1.0.0",
        system_prompt="Summarize this meeting.",
    )
    assert template.few_shot_examples == []
    assert template.focus_instructions is None


def test_structured_summary_defaults_to_empty_quotes() -> None:
    summary = StructuredSummary(
        title="Standup",
        overview="Quick sync.",
        key_points=["Ship Friday"],
        action_items=[ActionItem(description="Draft report", owner="Bob")],
    )
    assert summary.quotes == []


def test_quote_carries_segment_id_for_traceability() -> None:
    quote = Quote(speaker="Alice", text="Let's ship Friday.", segment_id=0)
    assert quote.segment_id == 0


def test_summarize_request_bundles_segments_template_and_provider() -> None:
    request = SummarizeRequest(
        segments=[TranscriptSegment(text="Hi", segment_id=0)],
        template=TemplateSpec(name="general", version="1.0.0", system_prompt="Summarize."),
        provider="anthropic",
        model="claude-sonnet-4-6",
    )
    assert request.provider == "anthropic"
    assert len(request.segments) == 1


def test_summarize_response_carries_attempts_and_provider() -> None:
    response = SummarizeResponse(
        summary=StructuredSummary(
            title="Standup",
            overview="Quick sync.",
            key_points=[],
            action_items=[],
        ),
        attempts=1,
        provider="ollama",
        model="llama3.1",
    )
    assert response.attempts == 1


def test_template_spec_rejects_malformed_few_shot_example() -> None:
    with pytest.raises(ValidationError):
        TemplateSpec(
            name="general",
            version="1.0.0",
            system_prompt="Summarize.",
            few_shot_examples=[{"wrong_key": "x"}],  # type: ignore[list-item]
        )


def test_summarize_request_rejects_empty_segments() -> None:
    with pytest.raises(ValidationError):
        SummarizeRequest(
            segments=[],
            template=TemplateSpec(name="general", version="1.0.0", system_prompt="S."),
            provider="anthropic",
            model="claude-sonnet-4-6",
        )
