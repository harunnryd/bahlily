from __future__ import annotations

from pathlib import Path

import numpy as np

from bahlily_transcription.errors import TranscriptionEngineFailedError
from bahlily_transcription.models import TranscriptResult


class ParakeetEngine:
    _name = "parakeet"

    def __init__(self, models_dir: Path) -> None:
        self._models_dir = models_dir
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
        from onnx_asr import load_model as onnx_asr_load_model

        try:
            self._model = onnx_asr_load_model(name, path=self._models_dir)
        except Exception as exc:
            raise TranscriptionEngineFailedError("parakeet", str(exc)) from exc
        self._loaded = name

    def unload_model(self) -> None:
        self._loaded = None
        self._model = None

    def transcribe(self, audio: np.ndarray, language: str | None) -> TranscriptResult:
        if self._model is None:
            raise TranscriptionEngineFailedError("parakeet", "model not loaded")
        results = list(self._transcribe_inner([audio]))
        return results[0]

    def transcribe_batch(
        self, audios: list[np.ndarray], language: str | None
    ) -> list[TranscriptResult]:
        if self._model is None:
            raise TranscriptionEngineFailedError("parakeet", "model not loaded")
        return list(self._transcribe_inner(audios))

    def _transcribe_inner(self, audios: list[np.ndarray]) -> list[TranscriptResult]:
        if not audios:
            return []
        waveforms = np.stack(audios).astype(np.float32)
        waveforms_len = np.fromiter(
            (audio.shape[0] for audio in audios),
            dtype=np.int64,
            count=len(audios),
        )
        out: list[TranscriptResult] = []
        for idx, result in enumerate(self._model.recognize_batch(waveforms, waveforms_len)):  # type: ignore[union-attr]
            text = result.text.strip()
            timestamps = result.timestamps or []
            logprobs = result.logprobs or []
            audio_len_samples = int(waveforms_len[idx])
            sample_rate = 16000
            start = float(timestamps[0]) if timestamps else 0.0
            end = (
                float(timestamps[-1])
                if timestamps
                else float(audio_len_samples) / float(sample_rate)
            )
            confidence = float(sum(logprobs) / len(logprobs)) if logprobs else None
            out.append(
                TranscriptResult(
                    text=text,
                    confidence=confidence,
                    language=None,
                    audio_start_time=start,
                    audio_end_time=end,
                )
            )
        return out
