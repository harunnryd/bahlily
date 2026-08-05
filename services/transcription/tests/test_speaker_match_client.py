from __future__ import annotations

import httpx
import pytest
import respx

from bahlily_transcription.speaker_match_client import SpeakerMatchClient


@pytest.mark.asyncio
async def test_match_bulk_returns_empty_dict_when_storage_url_unset() -> None:
    client = SpeakerMatchClient(storage_url=None)
    result = await client.match_bulk([("S1", [0.0] * 512)])
    assert result == {}


@pytest.mark.asyncio
async def test_match_bulk_returns_profile_map_on_success(respx_mock: respx.MockRouter) -> None:
    respx_mock.post("http://storage/speaker-profiles/match-bulk").mock(
        return_value=httpx.Response(
            200,
            json={
                "matches": [
                    {"key": "S1", "profile": {"id": "p1", "name": "Alice"}},
                    {"key": "S2", "profile": None},
                ]
            },
        )
    )
    client = SpeakerMatchClient(storage_url="http://storage")
    result = await client.match_bulk([("S1", [0.0] * 512), ("S2", [1.0] * 512)])
    assert result == {"S1": {"profile_id": "p1", "profile_name": "Alice"}}


@pytest.mark.asyncio
async def test_match_bulk_returns_empty_dict_on_connect_error(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.post("http://storage/speaker-profiles/match-bulk").mock(
        side_effect=httpx.ConnectError("nope")
    )
    client = SpeakerMatchClient(storage_url="http://storage")
    assert await client.match_bulk([("S1", [0.0] * 512)]) == {}


@pytest.mark.asyncio
async def test_match_bulk_returns_empty_dict_on_malformed_json(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.post("http://storage/speaker-profiles/match-bulk").mock(
        return_value=httpx.Response(200, content=b"not json")
    )
    client = SpeakerMatchClient(storage_url="http://storage")
    assert await client.match_bulk([("S1", [0.0] * 512)]) == {}


@pytest.mark.asyncio
async def test_match_bulk_returns_empty_dict_on_invalid_match_entry(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.post("http://storage/speaker-profiles/match-bulk").mock(
        return_value=httpx.Response(
            200,
            json={"matches": [{"key": "S1", "profile": {"id": "p1"}}]},
        )
    )
    client = SpeakerMatchClient(storage_url="http://storage")
    assert await client.match_bulk([("S1", [0.0] * 512)]) == {}
