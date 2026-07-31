from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from bahlily_transcription.engine import TranscriptionEngine
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


def test_parakeet_load_model_raises_not_implemented(models_dir: Path) -> None:
    engine = ParakeetEngine(models_dir=models_dir)
    with pytest.raises(NotImplementedError):
        engine.load_model("parakeet-tdt-1.1b")


def test_parakeet_transcribe_raises_not_implemented(models_dir: Path) -> None:
    engine = ParakeetEngine(models_dir=models_dir)
    with pytest.raises(NotImplementedError):
        engine.transcribe(np.zeros(16000, dtype=np.float32), language=None)
