from __future__ import annotations

from bahlily_logging.errors import BahlilyError


class ChatMeetingNotIngestedError(BahlilyError):
    def __init__(self, meeting_id: str) -> None:
        super().__init__(
            f"meeting '{meeting_id}' has not been ingested", code="CHAT_MEETING_NOT_INGESTED"
        )


class ChatUnsupportedEmbeddingProviderError(BahlilyError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="CHAT_UNSUPPORTED_EMBEDDING_PROVIDER")


class ChatUnsupportedProviderError(BahlilyError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="CHAT_UNSUPPORTED_PROVIDER")


class ChatProviderAuthError(BahlilyError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="CHAT_PROVIDER_AUTH_FAILED")


class ChatProviderUnavailableError(BahlilyError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="CHAT_PROVIDER_UNAVAILABLE")


def classify_provider_exception(exc: Exception) -> BahlilyError:
    status_code = getattr(exc, "status_code", None)
    if status_code in (401, 403):
        return ChatProviderAuthError("provider authentication failed")
    return ChatProviderUnavailableError("provider unavailable or timed out")
