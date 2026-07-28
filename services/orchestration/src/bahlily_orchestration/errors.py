from __future__ import annotations

from bahlily_logging.errors import BahlilyError


class UnsupportedProviderError(BahlilyError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="ORCHESTRATION_UNSUPPORTED_PROVIDER")


class ProviderAuthError(BahlilyError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="ORCHESTRATION_PROVIDER_AUTH_FAILED")


class ProviderUnavailableError(BahlilyError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="ORCHESTRATION_PROVIDER_UNAVAILABLE")


class StructuredOutputValidationFailedError(BahlilyError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="ORCHESTRATION_STRUCTURED_OUTPUT_FAILED")


def classify_provider_exception(exc: Exception) -> BahlilyError:
    status_code = getattr(exc, "status_code", None)
    if status_code in (401, 403):
        return ProviderAuthError(str(exc))
    return ProviderUnavailableError(str(exc))
