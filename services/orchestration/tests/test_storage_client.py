from __future__ import annotations

import httpx
import pytest
import respx

from bahlily_orchestration.storage_client import StorageTemplateClient


@pytest.mark.asyncio
async def test_list_custom_templates_returns_empty_when_storage_url_unset() -> None:
    client = StorageTemplateClient(storage_url=None)
    assert await client.list_custom_templates() == []


def test_constructor_rejects_http_storage_url() -> None:
    with pytest.raises(ValueError, match="https://"):
        StorageTemplateClient(storage_url="http://storage")


@pytest.mark.asyncio
async def test_list_custom_templates_maps_storage_response(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://storage/templates").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": "t1",
                    "name": "Standup",
                    "version": "1.0.0",
                    "system_prompt": "summarize standups",
                    "focus_instructions": None,
                    "few_shot_examples": [],
                    "created_at": "2026-08-01T00:00:00Z",
                    "updated_at": "2026-08-01T00:00:00Z",
                }
            ],
        )
    )
    client = StorageTemplateClient(storage_url="https://storage")
    result = await client.list_custom_templates()
    assert len(result) == 1
    assert result[0].id == "t1"
    assert result[0].source == "custom"
    assert result[0].name == "Standup"


@pytest.mark.asyncio
async def test_list_custom_templates_returns_empty_on_connect_error(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("https://storage/templates").mock(side_effect=httpx.ConnectError("nope"))
    client = StorageTemplateClient(storage_url="https://storage")
    assert await client.list_custom_templates() == []


@pytest.mark.asyncio
async def test_list_custom_templates_returns_empty_on_malformed_response(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("https://storage/templates").mock(
        return_value=httpx.Response(200, json=[{"id": "t1"}])
    )
    client = StorageTemplateClient(storage_url="https://storage")
    assert await client.list_custom_templates() == []
