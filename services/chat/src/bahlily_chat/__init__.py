from __future__ import annotations

import os


def main() -> None:
    import uvicorn

    from bahlily_chat import app as app_module

    host = os.environ.get("BAHLILY_CHAT_HTTP_HOST", "127.0.0.1")
    port = int(os.environ.get("BAHLILY_CHAT_HTTP_PORT", "8005"))
    db_path = os.environ.get("BAHLILY_CHAT_DB", app_module.DEFAULT_DB)
    dimension = int(os.environ["BAHLILY_CHAT_EMBEDDING_DIMENSION"])
    if dimension <= 0:
        raise ValueError(
            f"BAHLILY_CHAT_EMBEDDING_DIMENSION must be a positive integer, got {dimension}"
        )
    embedding_provider = os.environ["BAHLILY_CHAT_EMBEDDING_PROVIDER"]
    embedding_model = os.environ["BAHLILY_CHAT_EMBEDDING_MODEL"]

    app_module.configure_at_startup(
        db_path=db_path,
        dimension=dimension,
        embedding_provider=embedding_provider,
        embedding_model=embedding_model,
    )
    uvicorn.run("bahlily_chat.app:app", host=host, port=port)
