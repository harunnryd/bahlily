from __future__ import annotations

import numpy as np

from bahlily_transcription.engine import TranscriptionEngine
from bahlily_transcription.models import TranscriptResult


def test_fake_engine_satisfies_protocol(fake_engine: TranscriptionEngine) -> None:
    assert isinstance(fake_engine, TranscriptionEngine)


def test_fake_engine_not_loaded_initially(fake_engine: TranscriptionEngine) -> None:
    assert fake_engine.is_model_loaded() is False
    assert fake_engine.current_model() is None


def test_fake_engine_load_and_unload(fake_engine: TranscriptionEngine) -> None:
    fake_engine.load_model("test-model")
    assert fake_engine.is_model_loaded() is True
    assert fake_engine.current_model() == "test-model"
    fake_engine.unload_model()
    assert fake_engine.is_model_loaded() is False


def test_fake_engine_transcribe_returns_result(fake_engine: TranscriptionEngine) -> None:
    fake_engine.load_model("test-model")
    audio = np.zeros(16000, dtype=np.float32)
    result = fake_engine.transcribe(audio, language="en")
    assert isinstance(result, TranscriptResult)
    assert result.text == "fake transcription"


def test_fake_engine_transcribe_batch(fake_engine: TranscriptionEngine) -> None:
    fake_engine.load_model("test-model")
    audios = [np.zeros(16000, dtype=np.float32) for _ in range(3)]
    results = fake_engine.transcribe_batch(audios, language="en")
    assert len(results) == 3
    assert all(isinstance(r, TranscriptResult) for r in results)
