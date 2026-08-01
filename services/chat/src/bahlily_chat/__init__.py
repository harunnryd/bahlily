from __future__ import annotations

import os


def main() -> None:
    import uvicorn

    host = os.environ.get("BAHLILY_CHAT_HTTP_HOST", "127.0.0.1")
    port = int(os.environ.get("BAHLILY_CHAT_HTTP_PORT", "8005"))
    uvicorn.run("bahlily_chat.app:app", host=host, port=port)
