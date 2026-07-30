from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from bahlily_transcription.errors import (
    TranscriptionEngineFailedError,
    TranscriptionUnsupportedLanguageError,
)
from bahlily_transcription.models import TranscriptResult

# Kept at module scope so tests can patch it directly.
# Any avoids fighting conditional import types across install states.
ASRPipeline: Any = None
try:
    from onnx_asr import load_model as ASRPipeline  # type: ignore[no-redef]
except ImportError:
    pass


class ParakeetEngine:
    """Parakeet transcription backend via onnx-asr. English-only.
    Does not produce confidence scores."""

    _name = "parakeet"

    def __init__(self, models_dir: Path) -> None:
        self._models_dir = models_dir
        self._pipeline: Any = None
        self._loaded: str | None = None

    @property
    def name(self) -> str:
        return self._name

    def is_model_loaded(self) -> bool:
        return self._pipeline is not None

    def current_model(self) -> str | None:
        return self._loaded

    def load_model(self, name: str) -> None:
        model_path = str(self._models_dir / name)
        self._pipeline = ASRPipeline(model_path)
        self._loaded = name

    def unload_model(self) -> None:
        self._pipeline = None
        self._loaded = None

    def transcribe(self, audio: np.ndarray, language: str | None) -> TranscriptResult:
        if self._pipeline is None:
            raise TranscriptionEngineFailedError("parakeet", "model not loaded")
        if language is not None and language != "en":
            raise TranscriptionUnsupportedLanguageError(language, "parakeet")

        duration = float(len(audio)) / 16000.0
        try:
            result = self._pipeline.transcribe(audio)
            text = result["text"].strip() if isinstance(result, dict) else str(result).strip()
        except Exception as exc:
            raise TranscriptionEngineFailedError("parakeet", str(exc)) from exc

        return TranscriptResult(
            text=text,
            confidence=None,
            language=None,
            audio_start_time=0.0,
            audio_end_time=duration,
        )

    def transcribe_batch(
        self, audios: list[np.ndarray], language: str | None
    ) -> list[TranscriptResult]:
        return [self.transcribe(audio, language) for audio in audios]
