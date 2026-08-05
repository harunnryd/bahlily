from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from bahlily_transcription import app as app_module
from bahlily_transcription.app import _augment_diarization
from bahlily_transcription.diarize_engine import DiarizationResult
from bahlily_transcription.models import DiarizeRequest, TranscriptSegmentSchema
from bahlily_transcription.speaker_match_client import SpeakerMatchClient

PyannoteSpeakers = dict[str, list[float]]
PyannoteMockConfigurator = Callable[[PyannoteSpeakers], None]


def _seg(segment_id: int, cluster: str) -> TranscriptSegmentSchema:
    return TranscriptSegmentSchema(
        text="x",
        segment_id=segment_id,
        is_partial=False,
        engine="whisper",
        model_name="small",
        audio_start_time=0.0,
        audio_end_time=1.0,
        language="en",
        recording_id="r1",
        trace_id=f"t{segment_id}",
        speaker_cluster_label=cluster,
    )


async def _wait_for_diarize(
    client: TestClient, job_id: str, timeout_s: float = 5.0
) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        body: dict[str, Any] = client.get(f"/diarize/{job_id}").json()
        if body["status"] in {"completed", "failed"}:
            return body
        await asyncio.sleep(0.05)
    raise AssertionError(f"diarize job {job_id} never reached terminal status")


@pytest.fixture
def mocked_pyannote_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> PyannoteMockConfigurator:
    """Replace the pyannote Pipeline so DiarizeEngine.run produces
    deterministic output without loading the gated ML model. Returns a
    callable that takes a speakers mapping and configures the mock
    output for one test."""

    def configure(speakers: PyannoteSpeakers) -> None:
        ann = MagicMock()
        ann.itertracks.return_value = []
        ann.labels.return_value = list(speakers.keys())

        fake_output = MagicMock()
        fake_output.speaker_diarization = ann
        fake_output.speaker_embeddings = list(speakers.values())

        fake_pipeline = MagicMock()
        fake_pipeline.to = MagicMock(return_value=fake_pipeline)
        fake_pipeline.return_value = fake_output

        mock_class = MagicMock()
        mock_class.from_pretrained = MagicMock(return_value=fake_pipeline)

        monkeypatch.setattr("bahlily_transcription.diarize_engine.Pipeline", mock_class)
        app_module._diarize_engine._pipeline = None

    return configure


@pytest.mark.asyncio
async def test_augment_diarization_includes_matched_profile(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.post("https://storage/speaker-profiles/match-bulk").mock(
        return_value=httpx.Response(
            200,
            json={
                "matches": [
                    {"key": "SPEAKER_01", "profile": {"id": "p_alice", "name": "Alice"}},
                    {"key": "SPEAKER_02", "profile": None},
                ]
            },
        )
    )
    diarization = DiarizationResult(
        turns=[],
        speakers={
            "SPEAKER_01": [0.1] + [0.0] * 511,
            "SPEAKER_02": [0.0, 0.2] + [0.0] * 510,
        },
    )
    speakers = await _augment_diarization(
        diarization, SpeakerMatchClient(storage_url="https://storage"), "job1"
    )
    by_cluster = {s.cluster_label: s for s in speakers}
    assert by_cluster["SPEAKER_01"].matched_profile_id == "p_alice"
    assert by_cluster["SPEAKER_01"].matched_profile_name == "Alice"
    assert by_cluster["SPEAKER_02"].matched_profile_id is None
    assert by_cluster["SPEAKER_02"].matched_profile_name is None


@pytest.mark.asyncio
async def test_augment_diarization_preserves_speakers_when_storage_unreachable(
    respx_mock: respx.MockRouter,
) -> None:
    """When match_bulk raises, the diarization's clusters must still be
    preserved as DiarizeSpeaker records with matched fields unset. The
    previous behavior (return []) silently dropped every cluster on a
    transient storage failure."""
    respx_mock.post("https://storage/speaker-profiles/match-bulk").mock(
        side_effect=httpx.ConnectError("nope")
    )
    diarization = DiarizationResult(
        turns=[],
        speakers={
            "SPEAKER_01": [0.0] * 512,
            "SPEAKER_02": [0.0, 0.0] + [0.0] * 510,
        },
    )
    speakers = await _augment_diarization(
        diarization, SpeakerMatchClient(storage_url="https://storage"), "job2"
    )
    assert len(speakers) == 2
    assert {s.cluster_label for s in speakers} == {"SPEAKER_01", "SPEAKER_02"}
    for s in speakers:
        assert s.matched_profile_id is None
        assert s.matched_profile_name is None
        assert s.voice_embedding  # embedding preserved from the diarization


@pytest.mark.asyncio
async def test_augment_diarization_returns_empty_list_when_no_speakers() -> None:
    diarization = DiarizationResult(turns=[], speakers={})
    speakers = await _augment_diarization(
        diarization, SpeakerMatchClient(storage_url="https://storage"), "job3"
    )
    assert speakers == []


@pytest.mark.asyncio
async def test_augment_diarization_skips_storage_call_when_no_speakers(
    respx_mock: respx.MockRouter,
) -> None:
    """`match_bulk` is never called when there are no speakers to match.
    Confirms no spurious HTTP request when the diarization came back empty."""
    respx_mock.post("https://storage/speaker-profiles/match-bulk").mock(
        side_effect=AssertionError("match_bulk should not be called")
    )
    diarization = DiarizationResult(turns=[], speakers={})
    speakers = await _augment_diarization(
        diarization, SpeakerMatchClient(storage_url="https://storage"), "job4"
    )
    assert speakers == []


@pytest.mark.asyncio
async def test_diarize_endpoint_returns_matched_and_unmatched_profile_fields(
    mocked_pyannote_pipeline: PyannoteMockConfigurator,
    monkeypatch: pytest.MonkeyPatch,
    respx_mock: respx.MockRouter,
) -> None:
    monkeypatch.setenv("BAHLILY_TRANSCRIPTION_HF_TOKEN", "test")
    monkeypatch.setenv("BAHLILY_STORAGE_URL", "https://storage")
    monkeypatch.setattr(
        "bahlily_transcription.app._match_client",
        SpeakerMatchClient(storage_url="https://storage"),
    )
    mocked_pyannote_pipeline(
        {
            "SPEAKER_01": [0.1] + [0.0] * 511,
            "SPEAKER_02": [0.0, 0.2] + [0.0] * 510,
        }
    )
    respx_mock.post("https://storage/speaker-profiles/match-bulk").mock(
        return_value=httpx.Response(
            200,
            json={
                "matches": [
                    {"key": "SPEAKER_01", "profile": {"id": "p_alice", "name": "Alice"}},
                    {"key": "SPEAKER_02", "profile": None},
                ]
            },
        )
    )

    with TestClient(app_module.app) as client:
        start = client.post(
            "/diarize",
            json=DiarizeRequest(
                recording_path="/tmp/recording.flac",
                segments=[_seg(1, "SPEAKER_01"), _seg(2, "SPEAKER_02")],
            ).model_dump(),
        )
        job_id = start.json()["job_id"]
        body = await _wait_for_diarize(client, job_id)

    assert body["status"] == "completed"
    by_cluster = {s["cluster_label"]: s for s in body["speakers"]}
    assert by_cluster["SPEAKER_01"]["matched_profile_id"] == "p_alice"
    assert by_cluster["SPEAKER_01"]["matched_profile_name"] == "Alice"
    assert by_cluster["SPEAKER_02"]["matched_profile_id"] is None
    assert by_cluster["SPEAKER_02"]["matched_profile_name"] is None


@pytest.mark.asyncio
async def test_diarize_endpoint_falls_back_to_unmatched_when_storage_unreachable(
    mocked_pyannote_pipeline: PyannoteMockConfigurator,
    monkeypatch: pytest.MonkeyPatch,
    respx_mock: respx.MockRouter,
) -> None:
    monkeypatch.setenv("BAHLILY_TRANSCRIPTION_HF_TOKEN", "test")
    monkeypatch.setenv("BAHLILY_STORAGE_URL", "https://storage")
    monkeypatch.setattr(
        "bahlily_transcription.app._match_client",
        SpeakerMatchClient(storage_url="https://storage"),
    )
    mocked_pyannote_pipeline(
        {
            "SPEAKER_01": [0.0] * 512,
            "SPEAKER_02": [0.0, 0.0] + [0.0] * 510,
        }
    )
    respx_mock.post("https://storage/speaker-profiles/match-bulk").mock(
        side_effect=httpx.ConnectError("nope")
    )

    with TestClient(app_module.app) as client:
        start = client.post(
            "/diarize",
            json=DiarizeRequest(
                recording_path="/tmp/recording.flac",
                segments=[_seg(1, "SPEAKER_01"), _seg(2, "SPEAKER_02")],
            ).model_dump(),
        )
        job_id = start.json()["job_id"]
        body = await _wait_for_diarize(client, job_id)

    assert body["status"] == "completed"
    assert {s["cluster_label"] for s in body["speakers"]} == {"SPEAKER_01", "SPEAKER_02"}
    for s in body["speakers"]:
        assert s["matched_profile_id"] is None
        assert s["matched_profile_name"] is None


@pytest.mark.asyncio
async def test_diarize_endpoint_completes_with_empty_speakers_list(
    mocked_pyannote_pipeline: PyannoteMockConfigurator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BAHLILY_TRANSCRIPTION_HF_TOKEN", "test")
    monkeypatch.delenv("BAHLILY_STORAGE_URL", raising=False)
    monkeypatch.setattr(
        "bahlily_transcription.app._match_client",
        SpeakerMatchClient(storage_url=None),
    )
    mocked_pyannote_pipeline({})

    with TestClient(app_module.app) as client:
        start = client.post(
            "/diarize",
            json=DiarizeRequest(
                recording_path="/tmp/recording.flac",
                segments=[_seg(1, "SPEAKER_01")],
            ).model_dump(),
        )
        job_id = start.json()["job_id"]
        body = await _wait_for_diarize(client, job_id)

    assert body["status"] == "completed"
    assert body["speakers"] == []


@pytest.mark.asyncio
async def test_diarize_endpoint_makes_no_storage_request_when_diarization_empty(
    mocked_pyannote_pipeline: PyannoteMockConfigurator,
    monkeypatch: pytest.MonkeyPatch,
    respx_mock: respx.MockRouter,
) -> None:
    monkeypatch.setenv("BAHLILY_TRANSCRIPTION_HF_TOKEN", "test")
    monkeypatch.setenv("BAHLILY_STORAGE_URL", "https://storage")
    monkeypatch.setattr(
        "bahlily_transcription.app._match_client",
        SpeakerMatchClient(storage_url="https://storage"),
    )
    mocked_pyannote_pipeline({})
    respx_mock.post("https://storage/speaker-profiles/match-bulk").mock(
        side_effect=AssertionError("match_bulk should not be called")
    )

    with TestClient(app_module.app) as client:
        start = client.post(
            "/diarize",
            json=DiarizeRequest(
                recording_path="/tmp/recording.flac",
                segments=[_seg(1, "SPEAKER_01")],
            ).model_dump(),
        )
        job_id = start.json()["job_id"]
        body = await _wait_for_diarize(client, job_id)

    assert body["status"] == "completed"
    assert body["speakers"] == []
