from __future__ import annotations

import asyncio
import os

import uvicorn


def main() -> None:
    http_port = int(os.environ.get("BAHLILY_STORAGE_HTTP_PORT", "8003"))
    transcription_addr = os.environ.get("TRANSCRIPTION_GRPC_ADDR", "localhost:50052")

    async def _serve_all() -> None:
        from bahlily_storage.app import app
        from bahlily_storage.db import async_session_factory, init_db
        from bahlily_storage.grpc_subscriber import TranscriptionSubscriber

        await init_db()

        subscriber = TranscriptionSubscriber(
            addr=transcription_addr,
            session_factory=async_session_factory,
        )

        config = uvicorn.Config(app, host="0.0.0.0", port=http_port, log_level="info")
        server = uvicorn.Server(config)

        http_task = asyncio.create_task(server.serve())
        subscriber_task = asyncio.create_task(subscriber.run())

        try:
            done, _ = await asyncio.wait(
                {http_task, subscriber_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            for task in (http_task, subscriber_task):
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass

        exc: Exception | None = None
        for task in done:
            try:
                task.result()
            except Exception as e:
                if exc is None:
                    exc = e
        if exc is not None:
            raise exc

    asyncio.run(_serve_all())
