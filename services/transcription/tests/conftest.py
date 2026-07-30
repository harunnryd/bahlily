from __future__ import annotations

import socket

import numpy as np
import pytest

from bahlily_transcription.engine import TranscriptionEngine
from bahlily_transcription.models import TranscriptResult


class FakeEngine:
    """Implements TranscriptionEngine for use in tests. No real models loaded."""

    _name = "fake"
    _loaded: str | None = None

    @property
    def name(self) -> str:
        return self._name

    def is_model_loaded(self) -> bool:
        return self._loaded is not None

    def current_model(self) -> str | None:
        return self._loaded

    def load_model(self, name: str) -> None:
        self._loaded = name

    def unload_model(self) -> None:
        self._loaded = None

    def transcribe(self, audio: np.ndarray, language: str | None) -> TranscriptResult:
        duration = len(audio) / 16000.0
        return TranscriptResult(
            text="fake transcription",
            confidence=0.95,
            language=language or "en",
            audio_start_time=0.0,
            audio_end_time=duration,
        )

    def transcribe_batch(
        self, audios: list[np.ndarray], language: str | None
    ) -> list[TranscriptResult]:
        return [self.transcribe(audio, language) for audio in audios]


@pytest.fixture
def fake_engine() -> TranscriptionEngine:
    return FakeEngine()


@pytest.fixture
def unused_tcp_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return int(s.getsockname()[1])
