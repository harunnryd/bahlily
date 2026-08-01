from __future__ import annotations

import asyncio
import inspect
from unittest.mock import patch

import pytest
import structlog

from bahlily_storage import _run_concurrently, main
from bahlily_storage.app import app


def test_app_has_correct_title() -> None:
    assert app.title == "bahlily-storage"


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
