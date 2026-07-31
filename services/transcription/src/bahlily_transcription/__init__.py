from __future__ import annotations

import asyncio
import os

import uvicorn


async def _run_until_first_exits(tasks: set[asyncio.Task[None]]) -> None:
    # Runs tasks concurrently. When the first one exits (normally or with an
    # exception), the rest are cancelled and the completed task's result is
    # re-raised so the caller sees the failure.
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

    for task in done:
        task.result()


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
        await _run_until_first_exits({http_task, grpc_task})

    asyncio.run(_serve_all())
