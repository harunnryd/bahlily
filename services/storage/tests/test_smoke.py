from __future__ import annotations

import asyncio
import inspect
from typing import cast
from unittest.mock import patch

import pytest
import structlog
import uvicorn

from bahlily_storage import _run_concurrently, _serve_all, _serve_http, main
from bahlily_storage.app import app


def test_app_has_correct_title() -> None:
    assert app.title == "bahlily-storage"


async def test_serve_all_runs_alembic_upgrade(monkeypatch: pytest.MonkeyPatch) -> None:
    """Startup must make the DB alembic-tracked, not just `create_all` the schema."""
    calls: list[str] = []

    async def fake_upgrade() -> None:
        calls.append("upgrade")

    async def fake_run_concurrently(first: object, second: object) -> None:
        for coro in (first, second):
            if inspect.iscoroutine(coro):
                coro.close()

    import bahlily_storage.db as db_module

    monkeypatch.setattr(db_module, "upgrade_to_head", fake_upgrade)
    monkeypatch.setattr("bahlily_storage._run_concurrently", fake_run_concurrently)

    await _serve_all(http_port=0, transcription_addr="localhost:1")

    assert calls == ["upgrade"]


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


async def test_serve_http_calls_shutdown_on_cancellation() -> None:
    """Cancelling `server.serve()` bypasses uvicorn's own shutdown call
    (it only runs after its internal loop exits normally), so `_serve_http`
    must invoke `server.shutdown()` itself when cancelled."""
    shutdown_calls = 0

    class FakeServer:
        started = True

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
    calling it after a cancellation mid-startup would raise `AttributeError`."""
    shutdown_calls = 0

    class FakeServer:
        started = False

        async def serve(self) -> None:
            await asyncio.sleep(10)

        async def shutdown(self) -> None:
            nonlocal shutdown_calls
            shutdown_calls += 1

    async def quick() -> None:
        await asyncio.sleep(0)

    await _run_concurrently(quick(), _serve_http(cast(uvicorn.Server, FakeServer())))

    assert shutdown_calls == 0
