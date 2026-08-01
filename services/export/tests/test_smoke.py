from __future__ import annotations

from unittest.mock import patch

import pytest

from bahlily_export import main
from bahlily_export.app import app


def test_app_has_correct_title() -> None:
    assert app.title == "bahlily-export"


def test_main_starts_uvicorn_with_default_args() -> None:
    with patch("uvicorn.run") as mock_run:
        main()
    mock_run.assert_called_once_with("bahlily_export.app:app", host="127.0.0.1", port=8004)


def test_main_respects_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BAHLILY_EXPORT_HTTP_HOST", "0.0.0.0")
    monkeypatch.setenv("BAHLILY_EXPORT_HTTP_PORT", "9999")
    with patch("uvicorn.run") as mock_run:
        main()
    mock_run.assert_called_once_with("bahlily_export.app:app", host="0.0.0.0", port=9999)
