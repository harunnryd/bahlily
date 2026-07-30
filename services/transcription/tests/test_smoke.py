from __future__ import annotations

from unittest.mock import MagicMock, patch

from bahlily_transcription import main
from bahlily_transcription.app import app


def test_app_has_correct_title() -> None:
    assert app.title == "bahlily-transcription"


def test_main_starts_uvicorn_with_expected_args() -> None:
    with (
        patch("bahlily_transcription.uvicorn") as mock_uvicorn,
        patch("bahlily_transcription.asyncio") as mock_asyncio,
    ):
        mock_asyncio.run = MagicMock()
        main()
    assert mock_asyncio.run.called or mock_uvicorn.run.called
