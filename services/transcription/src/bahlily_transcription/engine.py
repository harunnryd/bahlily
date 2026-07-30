from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np

from bahlily_transcription.models import TranscriptResult


@runtime_checkable
class TranscriptionEngine(Protocol):
    @property
    def name(self) -> str: ...

    def is_model_loaded(self) -> bool: ...

    def current_model(self) -> str | None: ...

    def load_model(self, name: str) -> None: ...

    def unload_model(self) -> None: ...

    def transcribe(self, audio: np.ndarray, language: str | None) -> TranscriptResult: ...

    def transcribe_batch(
        self, audios: list[np.ndarray], language: str | None
    ) -> list[TranscriptResult]:
        return [self.transcribe(audio, language) for audio in audios]
