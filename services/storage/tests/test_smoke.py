from __future__ import annotations

import inspect
from unittest.mock import patch

from bahlily_storage import main
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
