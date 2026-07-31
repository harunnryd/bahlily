from __future__ import annotations

import platform
import sys
from pathlib import Path
from typing import Any

import numpy as np

from bahlily_transcription.errors import TranscriptionEngineFailedError
from bahlily_transcription.models import TranscriptResult


def _is_apple_silicon() -> bool:
    return sys.platform == "darwin" and platform.machine() == "arm64"


# Declared Any so the conditional import on non-Apple Silicon and the None default
# on Apple Silicon are both compatible without platform-specific mypy suppression
# churn. Kept at module scope so tests can patch it directly.
WhisperModel: Any = None
if not _is_apple_silicon():
    from faster_whisper import (  # type: ignore[import-not-found, import-untyped, no-redef]
        WhisperModel,
    )


class WhisperEngine:
    """Uses mlx-whisper on Apple Silicon, faster-whisper everywhere else."""

    _name = "whisper"

    def __init__(self, models_dir: Path) -> None:
        self._models_dir = models_dir
        self._model: object | None = None
        self._loaded: str | None = None
        self._mlx_model_path: str | None = None

    @property
    def name(self) -> str:
        return self._name

    def is_model_loaded(self) -> bool:
        return self._model is not None

    def current_model(self) -> str | None:
        return self._loaded

    def load_model(self, name: str) -> None:
        candidate = (self._models_dir / name).resolve()
        models_root = self._models_dir.resolve()
        # Reject traversal components (e.g. "../") that would escape models_dir.
        if not str(candidate).startswith(str(models_root) + "/") and candidate != models_root:
            raise TranscriptionEngineFailedError(
                "whisper",
                f"invalid model name '{name}': path escapes models directory",
            )
        if not candidate.is_dir():
            raise TranscriptionEngineFailedError(
                "whisper",
                f"model directory not found at {candidate}; download the model first",
            )
        model_path = str(candidate)
        if _is_apple_silicon():
            import mlx_whisper  # type: ignore[import-not-found, import-untyped]

            self._model = mlx_whisper
            self._mlx_model_path = model_path
        else:
            self._model = WhisperModel(model_path, device="auto", compute_type="auto")
        self._loaded = name

    def unload_model(self) -> None:
        self._model = None
        self._loaded = None

    def transcribe(self, audio: np.ndarray, language: str | None) -> TranscriptResult:
        if self._model is None:
            raise TranscriptionEngineFailedError("whisper", "model not loaded")

        try:
            if _is_apple_silicon():
                import mlx_whisper  # type: ignore[import-not-found, import-untyped]

                result = mlx_whisper.transcribe(
                    audio,
                    path_or_hf_repo=self._mlx_model_path,  # type: ignore[attr-defined]
                    language=language,
                )
                text = result["text"].strip()
                raw_segments = result.get("segments", [])
                start = raw_segments[0]["start"] if raw_segments else 0.0
                end = raw_segments[-1]["end"] if raw_segments else float(len(audio)) / 16000.0
                detected_language = result.get("language", language)
                confidence = None
            else:
                segments_iter, info = self._model.transcribe(  # type: ignore[attr-defined]
                    audio, language=language
                )
                segments = list(segments_iter)
                text = "".join(s.text for s in segments).strip()
                start = segments[0].start if segments else 0.0
                end = segments[-1].end if segments else float(len(audio)) / 16000.0
                detected_language = info.language
                logprobs = [s.avg_logprob for s in segments if hasattr(s, "avg_logprob")]
                confidence = float(sum(logprobs) / len(logprobs)) if logprobs else None
        except TranscriptionEngineFailedError:
            raise
        except Exception as exc:
            raise TranscriptionEngineFailedError("whisper", str(exc)) from exc

        return TranscriptResult(
            text=text,
            confidence=confidence,
            language=detected_language,
            audio_start_time=start,
            audio_end_time=end,
        )

    def transcribe_batch(
        self, audios: list[np.ndarray], language: str | None
    ) -> list[TranscriptResult]:
        return [self.transcribe(audio, language) for audio in audios]
