from __future__ import annotations

import dataclasses

import pydantic
import pytest

from bahlily_transcription.errors import (
    TranscriptionAlreadyDownloadingError,
    TranscriptionModelNotFoundError,
    TranscriptionModelNotLoadedError,
)
from bahlily_transcription.models import (
    DiarizeJobResponse,
    DiarizeJobStatus,
    DiarizeRequest,
    DiarizeSpeaker,
    DownloadProgress,
    ModelFile,
    ModelInfo,
    ModelStatus,
    TranscriptResult,
    TranscriptSegmentSchema,
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


def test_diarize_request_round_trips_through_json() -> None:
    req = DiarizeRequest(
        recording_path="/data/recordings/m1.flac",
        segments=[
            TranscriptSegmentSchema(
                text="hello",
                segment_id=0,
                is_partial=False,
                engine="whisper",
                model_name="tiny",
                audio_start_time=0.0,
                audio_end_time=1.0,
                recording_id="m1",
                trace_id="t1",
            )
        ],
    )
    restored = DiarizeRequest.model_validate_json(req.model_dump_json())
    assert restored == req


def _segment() -> TranscriptSegmentSchema:
    return TranscriptSegmentSchema(
        text="hello",
        segment_id=0,
        is_partial=False,
        engine="whisper",
        model_name="tiny",
        audio_start_time=0.0,
        audio_end_time=1.0,
        recording_id="m1",
        trace_id="t1",
    )


def test_diarize_request_rejects_a_relative_recording_path() -> None:
    with pytest.raises(pydantic.ValidationError):
        DiarizeRequest(recording_path="recordings/foo.flac", segments=[_segment()])


def test_diarize_request_rejects_a_path_traversal_segment() -> None:
    with pytest.raises(pydantic.ValidationError):
        DiarizeRequest(
            recording_path="/data/recordings/../../etc/passwd",
            segments=[_segment()],
        )


def test_diarize_request_accepts_a_legitimate_absolute_recording_path() -> None:
    req = DiarizeRequest(
        recording_path="/Users/someone/.local/share/bahlily/recordings/abc123.flac",
        segments=[_segment()],
    )
    assert req.recording_path.endswith("abc123.flac")


def test_diarize_job_response_defaults_to_no_result_fields() -> None:
    resp = DiarizeJobResponse(status=DiarizeJobStatus.PENDING)
    assert resp.segments is None
    assert resp.speakers is None
    assert resp.error is None


def test_diarize_job_response_completed_carries_segments_and_speakers() -> None:
    resp = DiarizeJobResponse(
        status=DiarizeJobStatus.COMPLETED,
        segments=[
            TranscriptSegmentSchema(
                text="hi",
                segment_id=0,
                is_partial=False,
                engine="whisper",
                model_name="tiny",
                audio_start_time=0.0,
                audio_end_time=1.0,
                recording_id="m1",
                trace_id="t1",
                speaker_cluster_label="Speaker 1",
            )
        ],
        speakers=[DiarizeSpeaker(cluster_label="Speaker 1", voice_embedding=[0.1, 0.2])],
    )
    assert resp.segments is not None
    assert resp.speakers is not None
    assert resp.segments[0].speaker_cluster_label == "Speaker 1"
    assert resp.speakers[0].voice_embedding == [0.1, 0.2]


def test_model_file_is_frozen() -> None:
    file = ModelFile(path="model.bin", sha256="abc")
    with pytest.raises(dataclasses.FrozenInstanceError):
        file.path = "other.bin"  # type: ignore[misc]


def test_model_info_with_files() -> None:
    f1 = ModelFile(path="config.json", sha256="abc")
    f2 = ModelFile(path="model.bin", sha256="def")
    info = ModelInfo(
        name="m",
        engine="whisper",
        size_bytes=200,
        repo_id="owner/repo",
        files=(f1, f2),
        tier="test",
    )
    assert info.name == "m"
    assert info.engine == "whisper"
    assert info.size_bytes == 200
    assert info.repo_id == "owner/repo"
    assert info.tier == "test"
    assert info.files == (f1, f2)
    assert len(info.files) == 2


def test_model_info_equality_with_same_files() -> None:
    f = ModelFile(path="model.bin", sha256="abc")
    a = ModelInfo("m", "whisper", 100, "owner/repo", (f,), "test")
    b = ModelInfo("m", "whisper", 100, "owner/repo", (f,), "test")
    assert a == b
