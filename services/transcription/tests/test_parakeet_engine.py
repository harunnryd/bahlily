from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from bahlily_transcription.engine import TranscriptionEngine
from bahlily_transcription.errors import TranscriptionUnsupportedLanguageError
from bahlily_transcription.parakeet_engine import ParakeetEngine


@pytest.fixture
def models_dir(tmp_path: Path) -> Path:
    d = tmp_path / "models" / "parakeet"
    d.mkdir(parents=True)
    return d


def test_parakeet_satisfies_protocol(models_dir: Path) -> None:
    engine = ParakeetEngine(models_dir=models_dir)
    assert isinstance(engine, TranscriptionEngine)


def test_parakeet_not_loaded_initially(models_dir: Path) -> None:
    engine = ParakeetEngine(models_dir=models_dir)
    assert engine.is_model_loaded() is False


def test_parakeet_transcribe_returns_no_confidence_no_language(models_dir: Path) -> None:
    mock_pipeline = MagicMock()
    mock_pipeline.transcribe.return_value = {"text": "hello world"}

    with patch("bahlily_transcription.parakeet_engine.ASRPipeline", return_value=mock_pipeline):
        engine = ParakeetEngine(models_dir=models_dir)
        engine.load_model("parakeet-tdt-1.1b")
        audio = np.zeros(16000, dtype=np.float32)
        result = engine.transcribe(audio, language=None)

    assert result.text == "hello world"
    assert result.confidence is None
    assert result.language is None


def test_parakeet_rejects_non_english(models_dir: Path) -> None:
    mock_pipeline = MagicMock()
    with patch("bahlily_transcription.parakeet_engine.ASRPipeline", return_value=mock_pipeline):
        engine = ParakeetEngine(models_dir=models_dir)
        engine.load_model("parakeet-tdt-1.1b")
        with pytest.raises(TranscriptionUnsupportedLanguageError):
            engine.transcribe(np.zeros(16000, dtype=np.float32), language="fr")
