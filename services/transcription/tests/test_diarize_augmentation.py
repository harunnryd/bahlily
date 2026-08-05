from __future__ import annotations

import httpx
import pytest
import respx

from bahlily_transcription.app import _augment_diarization
from bahlily_transcription.diarize_engine import DiarizationResult
from bahlily_transcription.speaker_match_client import SpeakerMatchClient


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
async def test_augment_diarization_leaves_matches_none_when_storage_unreachable(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.post("https://storage/speaker-profiles/match-bulk").mock(
        side_effect=httpx.ConnectError("nope")
    )
    diarization = DiarizationResult(
        turns=[],
        speakers={"SPEAKER_01": [0.0] * 512},
    )
    speakers = await _augment_diarization(
        diarization, SpeakerMatchClient(storage_url="https://storage"), "job2"
    )
    assert speakers[0].matched_profile_id is None
    assert speakers[0].matched_profile_name is None


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
