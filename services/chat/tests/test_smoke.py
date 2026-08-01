from __future__ import annotations

from unittest.mock import patch

import pytest

from bahlily_chat import main
from bahlily_chat.app import app


def test_app_has_correct_title() -> None:
    assert app.title == "bahlily-chat"


def _set_required_embedding_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BAHLILY_CHAT_EMBEDDING_PROVIDER", "ollama")
    monkeypatch.setenv("BAHLILY_CHAT_EMBEDDING_MODEL", "nomic-embed-text")
    monkeypatch.setenv("BAHLILY_CHAT_EMBEDDING_DIMENSION", "4")


def test_main_starts_uvicorn_with_default_args(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_embedding_env(monkeypatch)
    with patch("uvicorn.run") as mock_run:
        main()
    mock_run.assert_called_once_with("bahlily_chat.app:app", host="127.0.0.1", port=8005)


def test_main_respects_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_embedding_env(monkeypatch)
    monkeypatch.setenv("BAHLILY_CHAT_HTTP_HOST", "0.0.0.0")
    monkeypatch.setenv("BAHLILY_CHAT_HTTP_PORT", "9999")
    with patch("uvicorn.run") as mock_run:
        main()
    mock_run.assert_called_once_with("bahlily_chat.app:app", host="0.0.0.0", port=9999)


@pytest.mark.parametrize(
    "missing_var",
    [
        "BAHLILY_CHAT_EMBEDDING_PROVIDER",
        "BAHLILY_CHAT_EMBEDDING_MODEL",
        "BAHLILY_CHAT_EMBEDDING_DIMENSION",
    ],
)
def test_main_raises_clearly_when_required_env_var_missing(
    monkeypatch: pytest.MonkeyPatch, missing_var: str
) -> None:
    _set_required_embedding_env(monkeypatch)
    monkeypatch.delenv(missing_var, raising=False)
    with patch("uvicorn.run"), pytest.raises(KeyError, match=missing_var):
        main()
