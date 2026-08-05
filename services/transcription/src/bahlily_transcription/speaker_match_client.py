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
    _storage_url: str | None

    def __init__(self, storage_url: str | None, *, timeout: float = 2.0) -> None:
        if storage_url is not None:
            if not storage_url.startswith("https://"):
                raise ValueError(f"BAHLILY_STORAGE_URL must use https://; got '{storage_url}'")
            self._storage_url = storage_url.rstrip("/")
        else:
            self._storage_url = None
        self._timeout = timeout

    async def match_bulk(self, items: list[tuple[str, list[float]]]) -> dict[str, SpeakerMatchHit]:
        if self._storage_url is None or not items:
            return {}
        seen_keys: set[str] = set()
        for key, _ in items:
            if key in seen_keys:
                raise ValueError(f"duplicate key '{key}' in match_bulk items")
            seen_keys.add(key)
        body = {"embeddings": [{"key": key, "voice_embedding": emb} for key, emb in items]}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._storage_url}/speaker-profiles/match-bulk", json=body
                )
                resp.raise_for_status()
            response = _MatchBulkResponse.model_validate(resp.json())
            requested_keys = {key for key, _ in items}
            matched_keys: set[str] = set()
            hits: dict[str, SpeakerMatchHit] = {}
            for entry in response.matches:
                if entry.key not in requested_keys or entry.key in matched_keys:
                    raise ValueError("invalid speaker-match response key")
                matched_keys.add(entry.key)
                if entry.profile is not None:
                    hits[entry.key] = {
                        "profile_id": entry.profile.id,
                        "profile_name": entry.profile.name,
                    }
            if matched_keys != requested_keys:
                raise ValueError("incomplete speaker-match response")
            return hits
        except (httpx.HTTPError, ValueError) as exc:
            _log.warning(
                "speaker_match_bulk_failed",
                error=str(exc),
                item_count=len(items),
            )
            return {}
