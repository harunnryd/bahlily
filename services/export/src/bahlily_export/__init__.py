from __future__ import annotations

import os


def main() -> None:
    import uvicorn

    host = os.environ.get("BAHLILY_EXPORT_HTTP_HOST", "127.0.0.1")
    port = int(os.environ.get("BAHLILY_EXPORT_HTTP_PORT", "8004"))
    uvicorn.run("bahlily_export.app:app", host=host, port=port)
