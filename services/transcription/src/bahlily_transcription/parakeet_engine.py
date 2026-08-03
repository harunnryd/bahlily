from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from bahlily_transcription.errors import (
    TranscriptionEngineFailedError,
    TranscriptionModelNotFoundError,
)
from bahlily_transcription.models import TranscriptResult
from bahlily_transcription.registry import ModelRegistry

_SAMPLE_RATE = 16000


def _to_float_list(result: object, attr: str) -> list[float]:
    raw = getattr(result, attr, None)
    if raw is None:
        return []
    try:
        seq = list(raw)
    except TypeError as exc:
        raise TranscriptionEngineFailedError(
            "parakeet", f"model returned non-sequence for {attr}"
        ) from exc
    out: list[float] = []
    for v in seq:
        try:
            f = float(v)
        except (TypeError, ValueError) as exc:
            raise TranscriptionEngineFailedError(
                "parakeet", f"model returned non-numeric value in {attr}"
            ) from exc
        if not math.isfinite(f):
            raise TranscriptionEngineFailedError(
                "parakeet", f"model returned non-finite value in {attr}"
            )
        out.append(f)
    return out


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
        try:
            raw_results = self._model.recognize(audios, sample_rate=_SAMPLE_RATE)  # type: ignore[union-attr, attr-defined]
            results = list(raw_results)
        except TranscriptionEngineFailedError:
            raise
        except Exception as exc:
            raise TranscriptionEngineFailedError("parakeet", str(exc)) from exc
        if len(results) != len(audios):
            raise TranscriptionEngineFailedError(
                "parakeet",
                f"model returned {len(results)} results for {len(audios)} audios",
            )
        return [
            _to_transcript_result(audio, result)
            for audio, result in zip(audios, results, strict=True)
        ]


def _to_transcript_result(audio: np.ndarray, result: object) -> TranscriptResult:
    raw_text = getattr(result, "text", None)
    if raw_text is None or not isinstance(raw_text, str):
        raise TranscriptionEngineFailedError("parakeet", "model returned non-string text")
    text = raw_text.strip()
    timestamps = _to_float_list(result, "timestamps")
    logprobs = _to_float_list(result, "logprobs")
    audio_duration = float(audio.shape[0]) / float(_SAMPLE_RATE)
    start = float(timestamps[0]) if timestamps else 0.0
    end = float(timestamps[-1]) if timestamps else audio_duration
    start = max(0.0, min(start, audio_duration))
    end = max(0.0, min(end, audio_duration))
    if end < start:
        end = start
    confidence = float(sum(logprobs) / len(logprobs)) if logprobs else None
    return TranscriptResult(
        text=text,
        confidence=confidence,
        language=None,
        audio_start_time=start,
        audio_end_time=end,
    )
