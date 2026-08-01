from __future__ import annotations

import re
from collections.abc import Callable
from typing import Annotated, Literal

from fastapi import FastAPI, Query
from fastapi.responses import Response

from bahlily_export.docx_renderer import render_docx
from bahlily_export.markdown_renderer import render_markdown
from bahlily_export.models import ExportRequest
from bahlily_export.pdf_renderer import render_pdf

app = FastAPI(title="bahlily-export")

ExportFormat = Literal["markdown", "docx", "pdf"]

_CONTENT_TYPES: dict[ExportFormat, str] = {
    "markdown": "text/markdown",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
}

_EXTENSIONS: dict[ExportFormat, str] = {
    "markdown": "md",
    "docx": "docx",
    "pdf": "pdf",
}

_RENDERERS: dict[ExportFormat, Callable[[ExportRequest], bytes]] = {
    "markdown": render_markdown,
    "docx": render_docx,
    "pdf": render_pdf,
}


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    slug = slug[:60].strip("-")
    return slug or "summary"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/export")
def export(
    req: ExportRequest,
    export_format: Annotated[ExportFormat, Query(alias="format")],
) -> Response:
    try:
        data = _RENDERERS[export_format](req)
    except Exception:
        return Response(
            content=b"failed to render export", status_code=500, media_type="text/plain"
        )
    filename = f"{_slugify(req.title)}.{_EXTENSIONS[export_format]}"
    return Response(
        content=data,
        media_type=_CONTENT_TYPES[export_format],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
