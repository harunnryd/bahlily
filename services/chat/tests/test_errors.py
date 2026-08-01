from __future__ import annotations

from bahlily_chat.errors import (
    ChatMeetingNotIngestedError,
    ChatProviderAuthError,
    ChatProviderUnavailableError,
    ChatUnsupportedEmbeddingProviderError,
    ChatUnsupportedProviderError,
    classify_provider_exception,
)


def test_chat_meeting_not_ingested_error_code() -> None:
    exc = ChatMeetingNotIngestedError("m1")
    assert exc.code == "CHAT_MEETING_NOT_INGESTED"
    assert "m1" in str(exc)


def test_chat_unsupported_embedding_provider_error_code() -> None:
    error = ChatUnsupportedEmbeddingProviderError("bad")
    assert error.code == "CHAT_UNSUPPORTED_EMBEDDING_PROVIDER"


def test_chat_unsupported_provider_error_code() -> None:
    assert ChatUnsupportedProviderError("bad").code == "CHAT_UNSUPPORTED_PROVIDER"


def test_classify_provider_exception_auth_error() -> None:
    class FakeExc(Exception):
        status_code = 401

    result = classify_provider_exception(FakeExc())
    assert isinstance(result, ChatProviderAuthError)
    assert result.code == "CHAT_PROVIDER_AUTH_FAILED"


def test_classify_provider_exception_forbidden_is_auth_error() -> None:
    class FakeExc(Exception):
        status_code = 403

    assert isinstance(classify_provider_exception(FakeExc()), ChatProviderAuthError)


def test_classify_provider_exception_default_is_unavailable() -> None:
    result = classify_provider_exception(RuntimeError("timeout"))
    assert isinstance(result, ChatProviderUnavailableError)
    assert result.code == "CHAT_PROVIDER_UNAVAILABLE"
