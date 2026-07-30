import itertools
from typing import Any
from unittest.mock import patch

import pytest

from bahlily_orchestration.errors import (
    ProviderAuthError,
    StructuredOutputValidationFailedError,
    UnsupportedProviderError,
)
from bahlily_orchestration.models import (
    SummarizeRequest,
    TemplateSpec,
    TranscriptSegment,
)
from bahlily_orchestration.summarize import (
    _PROVIDER_MAX_RETRIES,
    _PROVIDER_TIMEOUT,
    summarize,
)
from tests.utils import FakeToolCallingModel, tool_call_message


def _request(provider: str = "anthropic", model: str = "claude-sonnet-4-6") -> SummarizeRequest:
    return SummarizeRequest(
        segments=[TranscriptSegment(text="Ship Friday.", segment_id=0, speaker="Alice")],
        template=TemplateSpec(name="general", version="1.0.0", system_prompt="Summarize this."),
        provider=provider,
        model=model,
    )


def test_summarize_returns_structured_summary_on_first_attempt(make_fake_model: Any) -> None:
    fake_model = make_fake_model(
        [
            tool_call_message(
                "StructuredSummary",
                {
                    "title": "Standup",
                    "overview": "Quick sync on shipping.",
                    "key_points": ["Ship Friday"],
                    "action_items": [],
                },
            )
        ]
    )
    with patch(
        "bahlily_orchestration.summarize.init_chat_model", return_value=fake_model
    ) as mock_init:
        response = summarize(_request())

    mock_init.assert_called_once_with(
        "anthropic:claude-sonnet-4-6",
        timeout=_PROVIDER_TIMEOUT,
        max_retries=_PROVIDER_MAX_RETRIES,
    )
    assert response.summary.title == "Standup"
    assert response.attempts == 1
    assert response.provider == "anthropic"


def test_summarize_counts_a_retry_as_two_attempts(make_fake_model: Any) -> None:
    fake_model = make_fake_model(
        [
            tool_call_message("StructuredSummary", {"title": "x"}),
            tool_call_message(
                "StructuredSummary",
                {
                    "title": "Standup",
                    "overview": "Fixed on retry.",
                    "key_points": [],
                    "action_items": [],
                },
            ),
        ]
    )
    with patch("bahlily_orchestration.summarize.init_chat_model", return_value=fake_model):
        response = summarize(_request())

    assert response.attempts == 2
    assert response.summary.overview == "Fixed on retry."


def test_summarize_raises_unsupported_provider_error_for_bad_provider_string() -> None:
    with patch(
        "bahlily_orchestration.summarize.init_chat_model",
        side_effect=ValueError("Unable to infer model provider"),
    ):
        with pytest.raises(UnsupportedProviderError):
            summarize(_request(provider="not-a-real-provider"))


def test_summarize_raises_structured_output_validation_failed_when_retries_exhausted() -> None:

    def always_invalid() -> Any:
        while True:
            yield tool_call_message("StructuredSummary", {"title": "x"})

    fake_model = FakeToolCallingModel(messages=always_invalid())
    with patch("bahlily_orchestration.summarize.init_chat_model", return_value=fake_model):
        with pytest.raises(StructuredOutputValidationFailedError):
            summarize(_request())


def test_summarize_maps_provider_auth_failure_to_provider_auth_error() -> None:
    class FakeAuthError(Exception):
        status_code = 401

    class RaisingModel:
        _llm_type: str = "anthropic-chat"

        def bind_tools(self, *args: Any, **kwargs: Any) -> "RaisingModel":
            return self

        def invoke(self, *args: Any, **kwargs: Any) -> Any:
            raise FakeAuthError("invalid api key")

    with patch("bahlily_orchestration.summarize.init_chat_model", return_value=RaisingModel()):
        with pytest.raises(ProviderAuthError):
            summarize(_request())


def test_summarize_does_not_swallow_internal_errors_as_provider_errors() -> None:
    with patch(
        "bahlily_orchestration.summarize.init_chat_model",
        side_effect=RuntimeError("internal bug"),
    ):
        with pytest.raises(RuntimeError):
            summarize(_request())


def test_pii_middleware_redacts_email_and_phone_before_model_sees_them() -> None:
    received_content: list[str] = []

    class RecordingModel(FakeToolCallingModel):
        def _generate(
            self,
            messages: Any,
            stop: Any = None,
            run_manager: Any = None,
            **kwargs: Any,
        ) -> Any:
            for msg in messages:
                content = getattr(msg, "content", "")
                if isinstance(content, str) and content:
                    received_content.append(content)
            return super()._generate(messages, stop, run_manager, **kwargs)

    fake_model = RecordingModel(
        messages=itertools.cycle(
            [
                tool_call_message(
                    "StructuredSummary",
                    {
                        "title": "Standup",
                        "overview": "Quick sync.",
                        "key_points": [],
                        "action_items": [],
                    },
                )
            ]
        )
    )

    request = SummarizeRequest(
        segments=[
            TranscriptSegment(
                text="Contact alice@example.com or call 555-123-4567 about the report.",
                segment_id=0,
                speaker="Bob",
            )
        ],
        template=TemplateSpec(name="general", version="1.0.0", system_prompt="Summarize."),
        provider="anthropic",
        model="claude-sonnet-4-6",
    )
    with patch("bahlily_orchestration.summarize.init_chat_model", return_value=fake_model):
        summarize(request)

    all_text = "\n".join(received_content)
    assert "alice@example.com" not in all_text
    assert "555-123-4567" not in all_text
