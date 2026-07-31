# TODO: onnx-asr 0.12.0 uses .recognize() not .transcribe(); load_model() API changed --
# wire properly before enabling Parakeet in production
from __future__ import annotations

from pathlib import Path

import numpy as np

from bahlily_transcription.models import TranscriptResult


class ParakeetEngine:
    _name = "parakeet"

    def __init__(self, models_dir: Path) -> None:
        self._models_dir = models_dir
        self._loaded: str | None = None

    @property
    def name(self) -> str:
        return self._name

    def is_model_loaded(self) -> bool:
        return self._loaded is not None

    def current_model(self) -> str | None:
        return self._loaded

    def load_model(self, name: str) -> None:
        raise NotImplementedError(
            "Parakeet wiring incomplete: onnx-asr 0.12.0 API changed; see TODO"
        )

    def unload_model(self) -> None:
        self._loaded = None

    def transcribe(self, audio: np.ndarray, language: str | None) -> TranscriptResult:
        raise NotImplementedError("Parakeet not yet wired to onnx-asr")

    def transcribe_batch(
        self, audios: list[np.ndarray], language: str | None
    ) -> list[TranscriptResult]:
        return [self.transcribe(audio, language) for audio in audios]
