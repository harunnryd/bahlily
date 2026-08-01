from __future__ import annotations

import asyncio
import os
from collections.abc import Coroutine
from typing import Any

import structlog
import uvicorn

_log = structlog.get_logger()


async def _serve_http(server: uvicorn.Server) -> None:
    """Run `server.serve()`, running `server.shutdown()` on cancellation.

    Uvicorn's own `_serve()` only calls `shutdown()` after its main loop
    returns normally (i.e. after a signal sets `should_exit`); a cancelled
    task never reaches that line, so connections are never drained and the
    FastAPI lifespan shutdown handlers never run. `_run_concurrently` cancels
    whichever task is still running when the other one finishes, so this
    wrapper is what gives the HTTP server a graceful shutdown in that case.
    """
    try:
        await server.serve()
    except asyncio.CancelledError:
        # `server.started` is only set once `startup()` finishes; `shutdown()`
        # assumes `self.servers` exists, which it doesn't if cancellation
        # landed mid-startup. Nothing was bound yet, so there's nothing to
        # drain.
        if server.started:
            await server.shutdown()
        raise


async def _run_concurrently(
    first: Coroutine[Any, Any, None],
    second: Coroutine[Any, Any, None],
) -> None:
    """Run two coroutines concurrently; when either finishes, cancel the other.

    Any exception raised by whichever coroutine(s) completed first is
    re-raised after teardown. Exceptions raised while awaiting a cancelled
    task are logged (except `CancelledError` itself, which is expected) so a
    real failure during shutdown isn't silently discarded.
    """
    first_task = asyncio.create_task(first)
    second_task = asyncio.create_task(second)

    try:
        done, _ = await asyncio.wait(
            {first_task, second_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
    finally:
        for task in (first_task, second_task):
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception as teardown_exc:
                    _log.warning("task_teardown_error", error=str(teardown_exc))

    first_exc: Exception | None = None
    for task in done:
        try:
            task.result()
        except Exception as e:
            if first_exc is None:
                first_exc = e
            else:
                _log.warning("discarded_secondary_exception", error=str(e))
    if first_exc is not None:
        raise first_exc


async def _serve_all(http_host: str, http_port: int, transcription_addr: str) -> None:
    from bahlily_storage import db
    from bahlily_storage.app import app
    from bahlily_storage.grpc_subscriber import TranscriptionSubscriber

    # Alembic (not `create_all`) so the database ends up with an
    # `alembic_version` row and later migrations can apply cleanly.
    await db.upgrade_to_head()

    subscriber = TranscriptionSubscriber(
        addr=transcription_addr,
        session_factory=db.async_session_factory,
    )

    config = uvicorn.Config(app, host=http_host, port=http_port, log_level="info")
    server = uvicorn.Server(config)

    await _run_concurrently(_serve_http(server), subscriber.run())


def main() -> None:
    # Storage is the single authoritative writer for this machine's own data;
    # it isn't meant to be reachable from the network, so bind loopback-only
    # unless explicitly overridden.
    http_host = os.environ.get("BAHLILY_STORAGE_HTTP_HOST", "127.0.0.1")
    http_port = int(os.environ.get("BAHLILY_STORAGE_HTTP_PORT", "8003"))
    transcription_addr = os.environ.get("TRANSCRIPTION_GRPC_ADDR", "localhost:50052")

    asyncio.run(_serve_all(http_host, http_port, transcription_addr))
