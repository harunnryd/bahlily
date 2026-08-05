from __future__ import annotations

from typing import TypedDict

import httpx
import structlog
from pydantic import BaseModel

_log = structlog.get_logger()


class SpeakerMatchHit(TypedDict):
    profile_id: str
    profile_name: str


class _SpeakerProfile(BaseModel):
    id: str
    name: str


class _MatchBulkEntry(BaseModel):
    key: str
    profile: _SpeakerProfile | None = None


class _MatchBulkResponse(BaseModel):
    matches: list[_MatchBulkEntry]


class SpeakerMatchClient:
    def __init__(self, storage_url: str | None, *, timeout: float = 2.0) -> None:
        self._storage_url = storage_url.rstrip("/") if storage_url else None
        self._timeout = timeout

    async def match_bulk(self, items: list[tuple[str, list[float]]]) -> dict[str, SpeakerMatchHit]:
        if self._storage_url is None or not items:
            return {}
        body = {"embeddings": [{"key": key, "voice_embedding": emb} for key, emb in items]}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._storage_url}/speaker-profiles/match-bulk", json=body
                )
                resp.raise_for_status()
            response = _MatchBulkResponse.model_validate(resp.json())
            return {
                entry.key: {
                    "profile_id": entry.profile.id,
                    "profile_name": entry.profile.name,
                }
                for entry in response.matches
                if entry.profile is not None
            }
        except (httpx.HTTPError, ValueError) as exc:
            _log.warning(
                "speaker_match_bulk_failed",
                error=str(exc),
                item_count=len(items),
            )
            return {}
