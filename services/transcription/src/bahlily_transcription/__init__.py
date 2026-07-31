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

        http_task = asyncio.create_task(server.serve())
        grpc_task = asyncio.create_task(grpc_serve(_broadcast, grpc_port))
        try:
            done, pending = await asyncio.wait(
                {http_task, grpc_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            for task in (http_task, grpc_task):
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass

    asyncio.run(_serve_all())
