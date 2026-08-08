from __future__ import annotations

import httpx
import structlog
from pydantic import BaseModel

from bahlily_orchestration.models import FewShotExample, TemplateSpec

_log = structlog.get_logger()


class _StorageTemplate(BaseModel):
    id: str
    name: str
    version: str
    system_prompt: str
    focus_instructions: str | None = None
    few_shot_examples: list[FewShotExample] = []


class StorageTemplateClient:
    _storage_url: str | None

    def __init__(self, storage_url: str | None, *, timeout: float = 2.0) -> None:
        if storage_url is not None:
            if not storage_url.startswith("https://"):
                raise ValueError(f"BAHLILY_STORAGE_URL must use https://; got '{storage_url}'")
            self._storage_url = storage_url.rstrip("/")
        else:
            self._storage_url = None
        self._timeout = timeout

    async def list_custom_templates(self) -> list[TemplateSpec]:
        if self._storage_url is None:
            return []
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(f"{self._storage_url}/templates")
                resp.raise_for_status()
            templates = [_StorageTemplate.model_validate(item) for item in resp.json()]
        except (httpx.HTTPError, ValueError) as exc:
            _log.warning("list_custom_templates_failed", error=str(exc))
            return []
        return [
            TemplateSpec(
                id=t.id,
                source="custom",
                name=t.name,
                version=t.version,
                system_prompt=t.system_prompt,
                focus_instructions=t.focus_instructions,
                few_shot_examples=t.few_shot_examples,
            )
            for t in templates
        ]
