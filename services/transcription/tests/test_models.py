from __future__ import annotations

import dataclasses

import pytest

from bahlily_transcription.errors import (
    TranscriptionAlreadyDownloadingError,
    TranscriptionModelNotFoundError,
    TranscriptionModelNotLoadedError,
)
from bahlily_transcription.models import (
    DownloadProgress,
    ModelStatus,
    TranscriptResult,
)


def test_transcript_result_is_frozen() -> None:
    r = TranscriptResult(
        text="hello",
        confidence=0.9,
        language="en",
        audio_start_time=0.0,
        audio_end_time=2.5,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.text = "changed"  # type: ignore[misc]


def test_model_status_values_exist() -> None:
    assert ModelStatus.AVAILABLE.value == "available"
    assert ModelStatus.MISSING.value == "missing"
    assert ModelStatus.DOWNLOADING.value == "downloading"
    assert ModelStatus.ERROR.value == "error"
    assert ModelStatus.CORRUPTED.value == "corrupted"


def test_download_progress_is_frozen() -> None:
    p = DownloadProgress(
        model_name="large-v3-turbo",
        engine="whisper",
        bytes_downloaded=500,
        total_bytes=1000,
        status=ModelStatus.DOWNLOADING,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.bytes_downloaded = 600  # type: ignore[misc]


def test_error_codes_are_set() -> None:
    assert TranscriptionModelNotLoadedError("whisper").code == "TRANSCRIPTION_MODEL_NOT_LOADED"
    assert TranscriptionModelNotFoundError("bad-name").code == "TRANSCRIPTION_MODEL_NOT_FOUND"
    assert (
        TranscriptionAlreadyDownloadingError("large-v3").code == "TRANSCRIPTION_ALREADY_DOWNLOADING"
    )
