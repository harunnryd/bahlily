from __future__ import annotations

import re
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


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    slug = slug[:60].strip("-")
    return slug or "summary"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/export")
async def export(
    req: ExportRequest,
    format: Annotated[ExportFormat, Query()],
) -> Response:
    data = {
        "markdown": render_markdown,
        "docx": render_docx,
        "pdf": render_pdf,
    }[format](req)
    filename = f"{_slugify(req.title)}.{_EXTENSIONS[format]}"
    return Response(
        content=data,
        media_type=_CONTENT_TYPES[format],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
