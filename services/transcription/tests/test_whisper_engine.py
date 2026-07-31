from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from bahlily_transcription.engine import TranscriptionEngine
from bahlily_transcription.whisper_engine import WhisperEngine


@pytest.fixture
def models_dir(tmp_path: Path) -> Path:
    d = tmp_path / "models" / "whisper"
    d.mkdir(parents=True)
    return d


@pytest.fixture
def model_dir(models_dir: Path) -> Path:
    """Pre-creates the 'tiny' model directory so load_model passes the local-dir check."""
    d = models_dir / "tiny"
    d.mkdir()
    return d


def _mock_faster_whisper_segment(text: str, start: float, end: float) -> MagicMock:
    seg = MagicMock()
    seg.text = text
    seg.start = start
    seg.end = end
    seg.avg_logprob = -0.15
    return seg


def test_whisper_engine_satisfies_protocol(models_dir: Path) -> None:
    engine = WhisperEngine(models_dir=models_dir)
    assert isinstance(engine, TranscriptionEngine)


def test_whisper_not_loaded_initially(models_dir: Path) -> None:
    engine = WhisperEngine(models_dir=models_dir)
    assert engine.is_model_loaded() is False
    assert engine.current_model() is None


def test_whisper_load_sets_state(models_dir: Path, model_dir: Path) -> None:
    mock_model = MagicMock()
    with (
        patch("bahlily_transcription.whisper_engine._is_apple_silicon", return_value=False),
        patch("bahlily_transcription.whisper_engine.WhisperModel", return_value=mock_model),
    ):
        engine = WhisperEngine(models_dir=models_dir)
        engine.load_model("tiny")
    assert engine.is_model_loaded() is True
    assert engine.current_model() == "tiny"


def test_whisper_transcribe_returns_joined_text(models_dir: Path, model_dir: Path) -> None:
    seg1 = _mock_faster_whisper_segment("hello", 0.0, 1.0)
    seg2 = _mock_faster_whisper_segment(" world", 1.0, 2.0)
    mock_info = MagicMock()
    mock_info.language = "en"
    mock_model = MagicMock()
    mock_model.transcribe.return_value = ([seg1, seg2], mock_info)

    with (
        patch("bahlily_transcription.whisper_engine._is_apple_silicon", return_value=False),
        patch("bahlily_transcription.whisper_engine.WhisperModel", return_value=mock_model),
    ):
        engine = WhisperEngine(models_dir=models_dir)
        engine.load_model("tiny")
        audio = np.zeros(32000, dtype=np.float32)
        result = engine.transcribe(audio, language=None)

    assert result.text == "hello world"
    assert result.audio_start_time == 0.0
    assert result.audio_end_time == 2.0
    assert result.language == "en"


def test_whisper_unload_clears_state(models_dir: Path, model_dir: Path) -> None:
    mock_model = MagicMock()
    with (
        patch("bahlily_transcription.whisper_engine._is_apple_silicon", return_value=False),
        patch("bahlily_transcription.whisper_engine.WhisperModel", return_value=mock_model),
    ):
        engine = WhisperEngine(models_dir=models_dir)
        engine.load_model("tiny")
        engine.unload_model()
    assert engine.is_model_loaded() is False
    assert engine.current_model() is None
