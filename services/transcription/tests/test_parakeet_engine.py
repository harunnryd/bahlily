from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from bahlily_transcription.errors import (
    TranscriptionEngineFailedError,
    TranscriptionModelNotFoundError,
)
from bahlily_transcription.models import ModelInfo
from bahlily_transcription.parakeet_engine import ParakeetEngine

_MODEL_NAME = "nemo-parakeet-ctc-0.6b"


def _fake_registry(names: list[str]) -> MagicMock:
    registry = MagicMock()
    registry.list_models.return_value = [
        ModelInfo(
            name=n,
            engine="parakeet",
            size_bytes=1,
            checksum_sha256="x" * 64,
            download_url="http://example",
            tier="small",
        )
        for n in names
    ]
    return registry


def _engine() -> ParakeetEngine:
    return ParakeetEngine(Path("/tmp/models"), registry=_fake_registry([_MODEL_NAME]))


def test_parakeet_name() -> None:
    assert _engine().name == "parakeet"


def test_parakeet_not_loaded_by_default() -> None:
    eng = _engine()
    assert not eng.is_model_loaded()
    assert eng.current_model() is None


def test_parakeet_load_model_calls_onnx_asr_and_enables_timestamps() -> None:
    eng = _engine()
    base_model = MagicMock()
    timestamped_model = MagicMock()
    base_model.with_timestamps.return_value = timestamped_model
    with patch("onnx_asr.load_model", return_value=base_model) as mock_load:
        eng.load_model(_MODEL_NAME)
    mock_load.assert_called_once_with(_MODEL_NAME, path=Path("/tmp/models"))
    base_model.with_timestamps.assert_called_once_with()
    assert eng.is_model_loaded()
    assert eng.current_model() == _MODEL_NAME
    assert eng._model is timestamped_model


def test_parakeet_load_unknown_model_raises() -> None:
    registry = _fake_registry([_MODEL_NAME])
    eng = ParakeetEngine(Path("/tmp/models"), registry=registry)
    with pytest.raises(TranscriptionModelNotFoundError):
        eng.load_model("not-in-manifest")
    registry.list_models.assert_called_once()


def test_parakeet_load_failure_raises_engine_error() -> None:
    eng = _engine()
    with patch("onnx_asr.load_model", side_effect=RuntimeError("boom")):
        with pytest.raises(TranscriptionEngineFailedError):
            eng.load_model(_MODEL_NAME)
    assert not eng.is_model_loaded()


def test_parakeet_unload_clears_state() -> None:
    eng = _engine()
    fake_model = MagicMock()
    with patch("onnx_asr.load_model", return_value=fake_model):
        eng.load_model(_MODEL_NAME)
    assert eng.is_model_loaded()
    eng.unload_model()
    assert not eng.is_model_loaded()
    assert eng.current_model() is None


def test_parakeet_transcribe_after_unload_raises() -> None:
    eng = _engine()
    fake_model = MagicMock()
    with patch("onnx_asr.load_model", return_value=fake_model):
        eng.load_model(_MODEL_NAME)
    eng.unload_model()
    audio = np.zeros(16000, dtype=np.float32)
    with pytest.raises(TranscriptionEngineFailedError):
        eng.transcribe(audio, "en")


def test_parakeet_transcribe_without_model_raises() -> None:
    eng = _engine()
    audio = np.zeros(16000, dtype=np.float32)
    with pytest.raises(TranscriptionEngineFailedError):
        eng.transcribe(audio, "en")


def test_parakeet_transcribe_returns_text_and_confidence() -> None:
    eng = _engine()
    fake_result = MagicMock()
    fake_result.text = "  hello world  "
    fake_result.timestamps = [0.0, 1.0]
    fake_result.logprobs = [-0.1, -0.2]
    fake_model = MagicMock()
    fake_model.recognize.return_value = [fake_result]
    eng._model = fake_model
    eng._loaded = _MODEL_NAME

    audio = np.zeros(16000, dtype=np.float32)
    result = eng.transcribe(audio, "en")

    assert result.text == "hello world"
    assert result.audio_start_time == 0.0
    assert result.audio_end_time == 1.0
    assert result.confidence is not None
    assert result.confidence < 0


def test_parakeet_transcribe_handles_missing_timestamps_and_logprobs() -> None:
    eng = _engine()
    fake_result = MagicMock()
    fake_result.text = "no timestamps"
    fake_result.timestamps = None
    fake_result.logprobs = None
    fake_model = MagicMock()
    fake_model.recognize.return_value = [fake_result]
    eng._model = fake_model
    eng._loaded = _MODEL_NAME

    audio = np.zeros(24000, dtype=np.float32)
    result = eng.transcribe(audio, "en")

    assert result.text == "no timestamps"
    assert result.audio_start_time == 0.0
    assert result.audio_end_time == pytest.approx(1.5)
    assert result.confidence is None


def test_parakeet_end_time_never_shrinks_below_audio_duration() -> None:
    eng = _engine()
    fake_result = MagicMock()
    fake_result.text = "one"
    fake_result.timestamps = [0.5]
    fake_result.logprobs = [-0.1]
    fake_model = MagicMock()
    fake_model.recognize.return_value = [fake_result]
    eng._model = fake_model
    eng._loaded = _MODEL_NAME

    audio = np.zeros(32000, dtype=np.float32)
    result = eng.transcribe(audio, "en")

    assert result.audio_start_time == 0.5
    assert result.audio_end_time == pytest.approx(2.0)
