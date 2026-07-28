import pytest

from bahlily_logging.errors import BahlilyError


def test_error_carries_code_and_message() -> None:
    error = BahlilyError("model failed to load", code="AUDIO_VAD_MODEL_LOAD_FAILED")

    assert error.code == "AUDIO_VAD_MODEL_LOAD_FAILED"
    assert str(error) == "model failed to load"


def test_error_requires_code_keyword() -> None:
    with pytest.raises(TypeError):
        BahlilyError("missing code")  # type: ignore[call-arg]


def test_subclass_inherits_code_behavior() -> None:
    class StorageError(BahlilyError):
        pass

    error = StorageError("db locked", code="STORAGE_RESERVED")

    assert isinstance(error, BahlilyError)
    assert error.code == "STORAGE_RESERVED"
