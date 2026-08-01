from __future__ import annotations

import asyncio
import contextlib
import inspect
import sqlite3
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import httpx
import pytest
import structlog
import uvicorn

from bahlily_storage import _run_concurrently, _serve_all, _serve_http, main
from bahlily_storage.app import app


def test_app_has_correct_title() -> None:
    assert app.title == "bahlily-storage"


async def test_serve_all_runs_alembic_upgrade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unused_tcp_port: int
) -> None:
    """Startup must make the DB alembic-tracked, not just `create_all` the
    schema — and the HTTP server it starts must actually be reachable.

    Runs the real `_serve_all`: no mocked `upgrade_to_head` or
    `_run_concurrently`. A real migration runs against a real sqlite file, a
    real uvicorn server binds a real port, and the real (never-connecting,
    since `transcription_addr` is bogus) gRPC subscriber runs alongside it —
    exactly the concurrent composition production uses.
    """
    db_path = tmp_path / "serve-all.db"
    monkeypatch.setenv("BAHLILY_STORAGE_DB", str(db_path))

    task = asyncio.create_task(
        _serve_all(
            http_host="127.0.0.1",
            http_port=unused_tcp_port,
            transcription_addr="localhost:1",
        )
    )
    try:
        response = None
        async with httpx.AsyncClient() as client:
            deadline = asyncio.get_running_loop().time() + 5.0
            while response is None and asyncio.get_running_loop().time() < deadline:
                try:
                    response = await client.get(
                        f"http://127.0.0.1:{unused_tcp_port}/health", timeout=0.5
                    )
                except httpx.TransportError:
                    await asyncio.sleep(0.05)
        assert response is not None
        assert response.status_code == 200
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    conn = sqlite3.connect(str(db_path))
    try:
        versions = {row[0] for row in conn.execute("SELECT version_num FROM alembic_version")}
    finally:
        conn.close()
    assert versions  # a revision is stamped, proving a real alembic upgrade ran


def test_main_calls_asyncio_run() -> None:
    captured: list[object] = []

    def fake_run(coro: object) -> None:
        captured.append(coro)
        if inspect.iscoroutine(coro):
            coro.close()

    with patch("bahlily_storage.asyncio.run", side_effect=fake_run):
        main()

    assert len(captured) == 1
    assert inspect.iscoroutine(captured[0])


async def test_run_concurrently_cancels_other_task_on_completion() -> None:
    cancelled = False

    async def quick() -> None:
        await asyncio.sleep(0)

    async def slow() -> None:
        nonlocal cancelled
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled = True
            raise

    await _run_concurrently(quick(), slow())

    assert cancelled is True


async def test_run_concurrently_propagates_exception_and_cancels_other() -> None:
    cancelled = False

    async def boom() -> None:
        await asyncio.sleep(0)
        raise ValueError("boom")

    async def slow() -> None:
        nonlocal cancelled
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled = True
            raise

    with pytest.raises(ValueError, match="boom"):
        await _run_concurrently(boom(), slow())

    assert cancelled is True


async def test_run_concurrently_logs_teardown_error_from_other_task() -> None:
    async def quick() -> None:
        await asyncio.sleep(0)

    async def swallows_cancellation() -> None:
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            raise RuntimeError("teardown blew up") from None

    with structlog.testing.capture_logs() as logs:
        await _run_concurrently(quick(), swallows_cancellation())

    assert any(
        log.get("event") == "task_teardown_error"
        and "teardown blew up" in str(log.get("error", ""))
        for log in logs
    )


async def test_run_concurrently_logs_discarded_secondary_exception() -> None:
    """When both tasks complete with an exception in the same wait cycle,
    only the first is re-raised — the other must not be silently dropped."""

    async def boom_first() -> None:
        await asyncio.sleep(0)
        raise ValueError("first")

    async def boom_second() -> None:
        await asyncio.sleep(0)
        raise RuntimeError("second")

    with structlog.testing.capture_logs() as logs:
        with pytest.raises(Exception):  # noqa: B017
            await _run_concurrently(boom_first(), boom_second())

    assert any(log.get("event") == "discarded_secondary_exception" for log in logs)


class _FakeLifespan:
    """Mirrors the one attribute `_serve_http` reads on uvicorn's real
    `Lifespan` implementations: an `asyncio.Event` set once the ASGI app's
    startup handler has run (successfully or not)."""

    def __init__(self, *, startup_completed: bool) -> None:
        self.startup_event = asyncio.Event()
        if startup_completed:
            self.startup_event.set()
        self.shutdown_calls = 0

    async def shutdown(self) -> None:
        self.shutdown_calls += 1


async def test_serve_http_calls_shutdown_on_cancellation() -> None:
    """Cancelling `server.serve()` bypasses uvicorn's own shutdown call
    (it only runs after its internal loop exits normally), so `_serve_http`
    must invoke `server.shutdown()` itself when cancelled."""
    shutdown_calls = 0

    class FakeServer:
        started = True
        lifespan = _FakeLifespan(startup_completed=True)

        async def serve(self) -> None:
            await asyncio.sleep(10)

        async def shutdown(self) -> None:
            nonlocal shutdown_calls
            shutdown_calls += 1

    async def quick() -> None:
        await asyncio.sleep(0)

    await _run_concurrently(quick(), _serve_http(cast(uvicorn.Server, FakeServer())))

    assert shutdown_calls == 1


async def test_serve_http_skips_shutdown_when_never_started() -> None:
    """`shutdown()` reads `self.servers`, set only at the end of `startup()`;
    calling it after a cancellation before lifespan startup even ran would
    raise `AttributeError`. Neither `server.shutdown()` nor
    `lifespan.shutdown()` should run here."""
    shutdown_calls = 0
    lifespan = _FakeLifespan(startup_completed=False)

    class FakeServer:
        started = False

        async def serve(self) -> None:
            await asyncio.sleep(10)

        async def shutdown(self) -> None:
            nonlocal shutdown_calls
            shutdown_calls += 1

    fake_server = FakeServer()
    fake_server.lifespan = lifespan  # type: ignore[attr-defined]

    async def quick() -> None:
        await asyncio.sleep(0)

    await _run_concurrently(quick(), _serve_http(cast(uvicorn.Server, fake_server)))

    assert shutdown_calls == 0
    assert lifespan.shutdown_calls == 0


async def test_serve_http_shuts_down_lifespan_cancelled_during_listener_creation() -> None:
    """Real `uvicorn.Server`/`Config`, not a fake: `lifespan.startup()` runs
    *before* listener sockets are created, so a cancellation landing in that
    gap (startup handlers already ran, `server.started` still `False`) must
    still run the ASGI app's shutdown handler — otherwise whatever startup
    acquired (connections, background tasks) leaks silently, since nothing
    else will ever call it.
    """
    events = {"startup": False, "shutdown": False}

    async def lifespan_app(
        scope: dict[str, object],
        receive: object,
        send: object,
    ) -> None:
        assert scope["type"] == "lifespan"
        while True:
            message = await receive()  # type: ignore[operator]
            if message["type"] == "lifespan.startup":
                events["startup"] = True
                await send({"type": "lifespan.startup.complete"})  # type: ignore[operator]
            elif message["type"] == "lifespan.shutdown":
                events["shutdown"] = True
                await send({"type": "lifespan.shutdown.complete"})  # type: ignore[operator]
                return

    config = uvicorn.Config(lifespan_app, host="127.0.0.1", port=0, lifespan="on")
    server = uvicorn.Server(config)

    loop: Any = asyncio.get_running_loop()
    real_create_server = loop.create_server
    listener_gate = asyncio.Event()

    async def blocked_create_server(*args: Any, **kwargs: Any) -> Any:
        await listener_gate.wait()
        return await real_create_server(*args, **kwargs)

    loop.create_server = blocked_create_server

    task = asyncio.create_task(_serve_http(server))
    try:
        deadline = loop.time() + 2.0
        while not events["startup"] and loop.time() < deadline:
            await asyncio.sleep(0.01)
        assert events["startup"] is True
        assert server.started is False
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    assert events["shutdown"] is True
