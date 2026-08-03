from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from bahlily_transcription.errors import TranscriptionEngineFailedError
from bahlily_transcription.parakeet_engine import ParakeetEngine


def test_parakeet_name() -> None:
    eng = ParakeetEngine(Path("/tmp/models"))
    assert eng.name == "parakeet"


def test_parakeet_not_loaded_by_default() -> None:
    eng = ParakeetEngine(Path("/tmp/models"))
    assert not eng.is_model_loaded()
    assert eng.current_model() is None


def test_parakeet_load_model_calls_onnx_asr() -> None:
    eng = ParakeetEngine(Path("/tmp/models"))
    fake_model = MagicMock()
    with patch("onnx_asr.load_model", return_value=fake_model) as mock_load:
        eng.load_model("nemo-parakeet-ctc-0.6b")
    mock_load.assert_called_once_with("nemo-parakeet-ctc-0.6b", path=Path("/tmp/models"))
    assert eng.is_model_loaded()
    assert eng.current_model() == "nemo-parakeet-ctc-0.6b"
    assert eng._model is fake_model


def test_parakeet_load_failure_raises_engine_error() -> None:
    eng = ParakeetEngine(Path("/tmp/models"))
    with patch("onnx_asr.load_model", side_effect=RuntimeError("boom")):
        with pytest.raises(TranscriptionEngineFailedError):
            eng.load_model("nemo-parakeet-ctc-0.6b")
    assert not eng.is_model_loaded()


def test_parakeet_transcribe_without_model_raises() -> None:
    eng = ParakeetEngine(Path("/tmp/models"))
    audio = np.zeros(16000, dtype=np.float32)
    with pytest.raises(TranscriptionEngineFailedError):
        eng.transcribe(audio, "en")


def test_parakeet_transcribe_returns_text_and_confidence() -> None:
    eng = ParakeetEngine(Path("/tmp/models"))
    fake_result = MagicMock()
    fake_result.text = "  hello world  "
    fake_result.timestamps = [0.0, 1.0]
    fake_result.logprobs = [-0.1, -0.2]
    fake_model = MagicMock()
    fake_model.recognize_batch.return_value = iter([fake_result])
    eng._model = fake_model
    eng._loaded = "nemo-parakeet-ctc-0.6b"

    audio = np.zeros(16000, dtype=np.float32)
    result = eng.transcribe(audio, "en")

    assert result.text == "hello world"
    assert result.audio_start_time == 0.0
    assert result.audio_end_time == 1.0
    assert result.confidence is not None
    assert result.confidence < 0


def test_parakeet_transcribe_handles_missing_timestamps_and_logprobs() -> None:
    eng = ParakeetEngine(Path("/tmp/models"))
    fake_result = MagicMock()
    fake_result.text = "no timestamps"
    fake_result.timestamps = None
    fake_result.logprobs = None
    fake_model = MagicMock()
    fake_model.recognize_batch.return_value = iter([fake_result])
    eng._model = fake_model
    eng._loaded = "nemo-parakeet-ctc-0.6b"

    audio = np.zeros(16000, dtype=np.float32)
    result = eng.transcribe(audio, "en")

    assert result.text == "no timestamps"
    assert result.audio_start_time == 0.0
    assert result.audio_end_time == 1.0
    assert result.confidence is None
