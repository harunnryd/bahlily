from __future__ import annotations

from pathlib import Path

import numpy as np

from bahlily_transcription.errors import (
    TranscriptionEngineFailedError,
    TranscriptionModelNotFoundError,
)
from bahlily_transcription.models import TranscriptResult
from bahlily_transcription.registry import ModelRegistry

_SAMPLE_RATE = 16000


class ParakeetEngine:
    _name = "parakeet"

    def __init__(self, models_dir: Path, registry: ModelRegistry) -> None:
        self._models_dir = models_dir
        self._registry = registry
        self._loaded: str | None = None
        self._model: object | None = None

    @property
    def name(self) -> str:
        return self._name

    def is_model_loaded(self) -> bool:
        return self._loaded is not None

    def current_model(self) -> str | None:
        return self._loaded

    def load_model(self, name: str) -> None:
        known_names = {info.name for info in self._registry.list_models()}
        if name not in known_names:
            raise TranscriptionModelNotFoundError(name)

        from onnx_asr import load_model as onnx_asr_load_model

        try:
            self._model = onnx_asr_load_model(name, path=self._models_dir).with_timestamps()
        except Exception as exc:
            raise TranscriptionEngineFailedError("parakeet", str(exc)) from exc
        self._loaded = name

    def unload_model(self) -> None:
        self._loaded = None
        self._model = None

    def transcribe(self, audio: np.ndarray, language: str | None) -> TranscriptResult:
        results = self.transcribe_batch([audio], language)
        return results[0]

    def transcribe_batch(
        self, audios: list[np.ndarray], language: str | None
    ) -> list[TranscriptResult]:
        if self._model is None:
            raise TranscriptionEngineFailedError("parakeet", "model not loaded")
        results = self._model.recognize(audios, sample_rate=_SAMPLE_RATE)  # type: ignore[union-attr, attr-defined]
        return [
            _to_transcript_result(audio, result)
            for audio, result in zip(audios, results, strict=True)
        ]


def _to_transcript_result(audio: np.ndarray, result: object) -> TranscriptResult:
    timestamps = getattr(result, "timestamps", None) or []
    logprobs = getattr(result, "logprobs", None) or []
    text = getattr(result, "text", "").strip()
    audio_duration = float(audio.shape[0]) / float(_SAMPLE_RATE)
    start = float(timestamps[0]) if timestamps else 0.0
    end = max(audio_duration, float(timestamps[-1]) if timestamps else audio_duration)
    confidence = float(sum(logprobs) / len(logprobs)) if logprobs else None
    return TranscriptResult(
        text=text,
        confidence=confidence,
        language=None,
        audio_start_time=start,
        audio_end_time=end,
    )
