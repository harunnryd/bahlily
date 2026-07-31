from __future__ import annotations

import asyncio
import inspect
from unittest.mock import patch

import pytest

from bahlily_transcription import _run_until_first_exits, main
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
    """Regression: _run_until_first_exits propagates exceptions from completed tasks."""

    async def failing_serve() -> None:
        raise OSError("grpc bind failed")

    async def long_running_serve() -> None:
        await asyncio.sleep(100)

    task_fail: asyncio.Task[None] = asyncio.create_task(failing_serve())
    task_long: asyncio.Task[None] = asyncio.create_task(long_running_serve())

    with pytest.raises(OSError, match="grpc bind failed"):
        await _run_until_first_exits({task_fail, task_long})
