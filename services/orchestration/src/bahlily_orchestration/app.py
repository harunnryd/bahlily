from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.requests import Request

from bahlily_orchestration.errors import (
    ProviderAuthError,
    ProviderUnavailableError,
    StructuredOutputValidationFailedError,
    UnsupportedProviderError,
)
from bahlily_orchestration.models import SummarizeRequest, SummarizeResponse, TemplateSpec
from bahlily_orchestration.summarize import summarize
from bahlily_orchestration.template_loader import list_templates

app = FastAPI(title="bahlily-orchestration")

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
def get_templates() -> list[TemplateSpec]:
    return list_templates()


@app.post("/summarize")
def post_summarize(request: SummarizeRequest) -> SummarizeResponse:
    return summarize(request)
