from bahlily_logging.errors import BahlilyError

from bahlily_orchestration.errors import (
    ProviderAuthError,
    ProviderUnavailableError,
    StructuredOutputValidationFailedError,
    UnsupportedProviderError,
    classify_provider_exception,
)


def test_unsupported_provider_error_carries_its_code() -> None:
    error = UnsupportedProviderError("bad provider")
    assert isinstance(error, BahlilyError)
    assert error.code == "ORCHESTRATION_UNSUPPORTED_PROVIDER"


def test_provider_auth_error_carries_its_code() -> None:
    error = ProviderAuthError("bad key")
    assert error.code == "ORCHESTRATION_PROVIDER_AUTH_FAILED"


def test_provider_unavailable_error_carries_its_code() -> None:
    error = ProviderUnavailableError("timed out")
    assert error.code == "ORCHESTRATION_PROVIDER_UNAVAILABLE"


def test_structured_output_validation_failed_error_carries_its_code() -> None:
    error = StructuredOutputValidationFailedError("gave up")
    assert error.code == "ORCHESTRATION_STRUCTURED_OUTPUT_FAILED"


def test_classify_provider_exception_maps_401_to_auth_error() -> None:
    class FakeAPIError(Exception):
        status_code = 401

    result = classify_provider_exception(FakeAPIError("unauthorized"))
    assert isinstance(result, ProviderAuthError)


def test_classify_provider_exception_maps_403_to_auth_error() -> None:
    class FakeAPIError(Exception):
        status_code = 403

    result = classify_provider_exception(FakeAPIError("forbidden"))
    assert isinstance(result, ProviderAuthError)


def test_classify_provider_exception_maps_other_status_to_unavailable() -> None:
    class FakeAPIError(Exception):
        status_code = 503

    result = classify_provider_exception(FakeAPIError("unavailable"))
    assert isinstance(result, ProviderUnavailableError)


def test_classify_provider_exception_maps_missing_status_to_unavailable() -> None:
    result = classify_provider_exception(TimeoutError("connection timed out"))
    assert isinstance(result, ProviderUnavailableError)
