from __future__ import annotations

import asyncio
from unittest.mock import patch

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from bahlily_transcription.app import app
from bahlily_transcription.diarize_engine import DiarizationResult
from bahlily_transcription.models import DiarizeRequest, TranscriptSegmentSchema
from bahlily_transcription.speaker_match_client import SpeakerMatchClient


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


@pytest.mark.asyncio
async def test_diarize_response_includes_matched_profile_when_storage_finds_it(
    monkeypatch: pytest.MonkeyPatch,
    respx_mock: respx.MockRouter,
) -> None:
    monkeypatch.setenv("BAHLILY_TRANSCRIPTION_HF_TOKEN", "test")
    monkeypatch.setenv("BAHLILY_STORAGE_URL", "http://storage")
    monkeypatch.setattr(
        "bahlily_transcription.app._match_client",
        SpeakerMatchClient(storage_url="http://storage"),
    )

    fake_cluster_a = [0.1] + [0.0] * 511
    fake_cluster_b = [0.0, 0.2] + [0.0] * 510
    fake_result = DiarizationResult(
        turns=[],
        speakers={"SPEAKER_01": fake_cluster_a, "SPEAKER_02": fake_cluster_b},
    )

    respx_mock.post("http://storage/speaker-profiles/match-bulk").mock(
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

    with patch(
        "bahlily_transcription.app._diarize_engine.run",
        return_value=fake_result,
    ):
        with TestClient(app) as client:
            req = DiarizeRequest(
                recording_path="/tmp/recording.flac",
                segments=[_seg(1, "SPEAKER_01"), _seg(2, "SPEAKER_02")],
            )
            start = client.post("/diarize", json=req.model_dump())
            job_id = start.json()["job_id"]

            for _ in range(50):
                resp = client.get(f"/diarize/{job_id}")
                if resp.json()["status"] in {"completed", "failed"}:
                    break
                await asyncio.sleep(0.05)
            else:
                raise AssertionError("diarize job never reached a terminal status")

    body = resp.json()
    assert body["status"] == "completed"
    by_cluster = {speaker["cluster_label"]: speaker for speaker in body["speakers"]}
    assert by_cluster["SPEAKER_01"]["matched_profile_id"] == "p_alice"
    assert by_cluster["SPEAKER_01"]["matched_profile_name"] == "Alice"
    assert by_cluster["SPEAKER_02"]["matched_profile_id"] is None


@pytest.mark.asyncio
async def test_diarize_response_leaves_matches_none_when_storage_unreachable(
    monkeypatch: pytest.MonkeyPatch,
    respx_mock: respx.MockRouter,
) -> None:
    monkeypatch.setenv("BAHLILY_TRANSCRIPTION_HF_TOKEN", "test")
    monkeypatch.setenv("BAHLILY_STORAGE_URL", "http://storage")
    monkeypatch.setattr(
        "bahlily_transcription.app._match_client",
        SpeakerMatchClient(storage_url="http://storage"),
    )

    respx_mock.post("http://storage/speaker-profiles/match-bulk").mock(
        side_effect=httpx.ConnectError("nope")
    )
    fake_result = DiarizationResult(
        turns=[],
        speakers={"SPEAKER_01": [0.0] * 512},
    )

    with patch(
        "bahlily_transcription.app._diarize_engine.run",
        return_value=fake_result,
    ):
        with TestClient(app) as client:
            req = DiarizeRequest(
                recording_path="/tmp/recording.flac",
                segments=[_seg(1, "SPEAKER_01")],
            )
            start = client.post("/diarize", json=req.model_dump())
            job_id = start.json()["job_id"]

            for _ in range(50):
                resp = client.get(f"/diarize/{job_id}")
                if resp.json()["status"] in {"completed", "failed"}:
                    break
                await asyncio.sleep(0.05)
            else:
                raise AssertionError("diarize job never reached a terminal status")

    body = resp.json()
    assert body["status"] == "completed"
    assert body["speakers"][0]["matched_profile_id"] is None


@pytest.mark.asyncio
async def test_diarize_response_without_storage_url_leaves_matches_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BAHLILY_TRANSCRIPTION_HF_TOKEN", "test")
    monkeypatch.delenv("BAHLILY_STORAGE_URL", raising=False)
    monkeypatch.setattr(
        "bahlily_transcription.app._match_client",
        SpeakerMatchClient(storage_url=None),
    )
    fake_result = DiarizationResult(
        turns=[],
        speakers={"SPEAKER_01": [0.0] * 512},
    )

    with patch(
        "bahlily_transcription.app._diarize_engine.run",
        return_value=fake_result,
    ):
        with TestClient(app) as client:
            req = DiarizeRequest(
                recording_path="/tmp/recording.flac",
                segments=[_seg(1, "SPEAKER_01")],
            )
            start = client.post("/diarize", json=req.model_dump())
            job_id = start.json()["job_id"]

            for _ in range(50):
                resp = client.get(f"/diarize/{job_id}")
                if resp.json()["status"] in {"completed", "failed"}:
                    break
                await asyncio.sleep(0.05)
            else:
                raise AssertionError("diarize job never reached a terminal status")

    body = resp.json()
    assert body["status"] == "completed"
    assert body["speakers"][0]["matched_profile_id"] is None
