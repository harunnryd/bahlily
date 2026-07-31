from __future__ import annotations

import asyncio
import contextlib
import inspect
from unittest.mock import patch

import pytest

from bahlily_transcription import main
from bahlily_transcription.app import app


def test_app_has_correct_title() -> None:
    assert app.title == "bahlily-transcription"


def test_main_calls_asyncio_run_with_serve_coroutine() -> None:
    captured: list[object] = []

    def fake_run(coro: object) -> None:
        captured.append(coro)
        if inspect.iscoroutine(coro):
            coro.close()

    with patch("bahlily_transcription.asyncio.run", side_effect=fake_run):
        main()

    assert len(captured) == 1
    assert inspect.iscoroutine(captured[0])


@pytest.mark.asyncio
async def test_serve_all_propagates_grpc_serve_failure() -> None:
    """Regression: _serve_all calls result() on completed tasks so exceptions propagate."""

    async def failing_serve() -> None:
        raise OSError("grpc bind failed")

    async def long_running_serve() -> None:
        await asyncio.sleep(100)

    task_fail: asyncio.Task[None] = asyncio.create_task(failing_serve())
    task_long: asyncio.Task[None] = asyncio.create_task(long_running_serve())

    done: set[asyncio.Task[None]]
    try:
        done, _ = await asyncio.wait(
            {task_fail, task_long},
            return_when=asyncio.FIRST_COMPLETED,
        )
    finally:
        for task in (task_fail, task_long):
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task

    with pytest.raises(OSError, match="grpc bind failed"):
        for task in done:
            task.result()
