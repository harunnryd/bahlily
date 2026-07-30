from __future__ import annotations

import asyncio
import os

import uvicorn


def main() -> None:
    grpc_port = int(os.environ.get("TRANSCRIPTION_GRPC_PORT", "50052"))
    http_port = int(os.environ.get("TRANSCRIPTION_HTTP_PORT", "8002"))

    async def _serve_all() -> None:
        from bahlily_transcription.app import _broadcast, app
        from bahlily_transcription.grpc_server import serve as grpc_serve

        config = uvicorn.Config(app, host="0.0.0.0", port=http_port, log_level="info")
        server = uvicorn.Server(config)

        await asyncio.gather(
            server.serve(),
            grpc_serve(_broadcast, grpc_port),
        )

    asyncio.run(_serve_all())
