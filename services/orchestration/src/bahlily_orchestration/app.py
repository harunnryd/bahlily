from __future__ import annotations

import os

from bahlily_capability import require_capability
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.requests import Request

from bahlily_orchestration.errors import (
    ProviderAuthError,
    ProviderUnavailableError,
    StructuredOutputValidationFailedError,
    UnsupportedProviderError,
)
from bahlily_orchestration.models import SummarizeRequest, SummarizeResponse, TemplateSpec
from bahlily_orchestration.storage_client import StorageTemplateClient
from bahlily_orchestration.summarize import summarize
from bahlily_orchestration.template_loader import list_templates

app = FastAPI(
    title="bahlily-orchestration",
    dependencies=[Depends(require_capability)],
)

_storage_client = StorageTemplateClient(storage_url=os.environ.get("BAHLILY_STORAGE_URL"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=["tauri://localhost", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_ERROR_STATUS_CODES: dict[type[Exception], int] = {
    UnsupportedProviderError: 400,
    ProviderAuthError: 401,
    ProviderUnavailableError: 502,
    StructuredOutputValidationFailedError: 502,
}


@app.exception_handler(UnsupportedProviderError)
@app.exception_handler(ProviderAuthError)
@app.exception_handler(ProviderUnavailableError)
@app.exception_handler(StructuredOutputValidationFailedError)
async def bahlily_error_handler(request: Request, exc: Exception) -> JSONResponse:
    status_code = _ERROR_STATUS_CODES[type(exc)]
    return JSONResponse(status_code=status_code, content={"code": exc.code, "message": str(exc)})  # type: ignore[attr-defined]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/templates")
async def get_templates() -> list[TemplateSpec]:
    custom = await _storage_client.list_custom_templates()
    return [*list_templates(), *custom]


@app.post("/summarize")
def post_summarize(request: SummarizeRequest) -> SummarizeResponse:
    return summarize(request)
