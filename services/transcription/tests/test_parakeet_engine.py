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
    assert result.confidence == pytest.approx(-0.15)
    fake_model.recognize.assert_called_once_with([audio], sample_rate=16000)


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


def _engine_registry() -> MagicMock:
    registry = MagicMock()
    info = MagicMock()
    info.name = _MODEL_NAME
    registry.list_models.return_value = [info]
    return registry


def test_parakeet_transcribe_batch_handles_multiple_inputs() -> None:
    eng = ParakeetEngine(Path("/tmp/models"), registry=_engine_registry())
    fake_result_1 = MagicMock()
    fake_result_1.text = "hello"
    fake_result_1.timestamps = None
    fake_result_1.logprobs = None
    fake_result_2 = MagicMock()
    fake_result_2.text = "world"
    fake_result_2.timestamps = None
    fake_result_2.logprobs = None
    fake_model = MagicMock()
    fake_model.recognize.return_value = iter([fake_result_1, fake_result_2])
    eng._model = fake_model
    eng._loaded = _MODEL_NAME

    audio_1 = np.zeros(16000, dtype=np.float32)
    audio_2 = np.zeros(32000, dtype=np.float32)
    results = eng.transcribe_batch([audio_1, audio_2], "en")

    assert len(results) == 2
    assert results[0].text == "hello"
    assert results[1].text == "world"
    fake_model.recognize.assert_called_once_with([audio_1, audio_2], sample_rate=16000)


def test_parakeet_transcribe_batch_wraps_recognition_error() -> None:
    eng = ParakeetEngine(Path("/tmp/models"), registry=_engine_registry())
    fake_model = MagicMock()
    fake_model.recognize.side_effect = RuntimeError("model crashed")
    eng._model = fake_model
    eng._loaded = _MODEL_NAME
    with pytest.raises(TranscriptionEngineFailedError):
        eng.transcribe_batch([np.zeros(16000, dtype=np.float32)], "en")


def test_parakeet_transcribe_batch_invalid_result_count() -> None:
    eng = ParakeetEngine(Path("/tmp/models"), registry=_engine_registry())
    fake_model = MagicMock()
    fake_model.recognize.return_value = iter([MagicMock(text="only one")])
    eng._model = fake_model
    eng._loaded = _MODEL_NAME
    with pytest.raises(TranscriptionEngineFailedError):
        eng.transcribe_batch(
            [np.zeros(16000, dtype=np.float32), np.zeros(16000, dtype=np.float32)],
            "en",
        )


def test_parakeet_audio_end_time_from_last_token_with_trailing_silence() -> None:
    eng = ParakeetEngine(Path("/tmp/models"), registry=_engine_registry())
    fake_result = MagicMock()
    fake_result.text = "short"
    fake_result.timestamps = [0.5, 1.0]
    fake_result.logprobs = [-0.1, -0.1]
    fake_model = MagicMock()
    fake_model.recognize.return_value = iter([fake_result])
    eng._model = fake_model
    eng._loaded = _MODEL_NAME

    audio = np.zeros(32000, dtype=np.float32)
    result = eng.transcribe(audio, "en")

    assert result.audio_start_time == pytest.approx(0.5)
    assert result.audio_end_time == pytest.approx(1.0)


def test_parakeet_non_string_text_raises() -> None:
    eng = ParakeetEngine(Path("/tmp/models"), registry=_engine_registry())
    fake_result = MagicMock()
    fake_result.text = None
    fake_result.timestamps = None
    fake_result.logprobs = None
    fake_model = MagicMock()
    fake_model.recognize.return_value = iter([fake_result])
    eng._model = fake_model
    eng._loaded = _MODEL_NAME
    with pytest.raises(TranscriptionEngineFailedError):
        eng.transcribe(np.zeros(16000, dtype=np.float32), "en")


def test_parakeet_end_time_clamped_to_audio_duration() -> None:
    eng = ParakeetEngine(Path("/tmp/models"), registry=_engine_registry())
    fake_result = MagicMock()
    fake_result.text = "single"
    fake_result.timestamps = [1.5]
    fake_result.logprobs = [-0.1]
    fake_model = MagicMock()
    fake_model.recognize.return_value = iter([fake_result])
    eng._model = fake_model
    eng._loaded = _MODEL_NAME

    audio = np.zeros(16000, dtype=np.float32)
    result = eng.transcribe(audio, "en")

    assert result.audio_start_time == pytest.approx(1.0)
    assert result.audio_end_time == pytest.approx(1.0)
