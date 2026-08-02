from __future__ import annotations

import dataclasses
import os
import threading

from bahlily_transcription.errors import TranscriptionDiarizationUnavailableError

_MODEL_NAME = "pyannote/speaker-diarization-community-1"

try:
    import torch
    from pyannote.audio import Pipeline
except ImportError:
    torch = None  # type: ignore[assignment]
    Pipeline = None  # type: ignore[misc, assignment]


def _select_device() -> torch.device:
    if torch is None:
        raise TranscriptionDiarizationUnavailableError()
    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


@dataclasses.dataclass(frozen=True)
class DiarizationTurn:
    start: float
    end: float
    speaker_label: str


@dataclasses.dataclass(frozen=True)
class DiarizationResult:
    turns: list[DiarizationTurn]
    speakers: dict[str, list[float]]


class DiarizeEngine:
    def __init__(self) -> None:
        self._pipeline: object | None = None
        self._load_lock = threading.Lock()

    def is_loaded(self) -> bool:
        return self._pipeline is not None

    def load(self) -> None:
        if Pipeline is None:
            raise TranscriptionDiarizationUnavailableError()
        token = os.environ.get("BAHLILY_TRANSCRIPTION_HF_TOKEN")
        if not token:
            raise TranscriptionDiarizationUnavailableError()
        pipeline = Pipeline.from_pretrained(_MODEL_NAME, token=token)
        if pipeline is None:
            raise TranscriptionDiarizationUnavailableError()
        pipeline.to(_select_device())
        self._pipeline = pipeline

    def run(self, recording_path: str) -> DiarizationResult:
        # `run` executes inside a ThreadPoolExecutor worker thread, so two
        # concurrent /diarize calls can both observe `_pipeline is None` and
        # both call the expensive `Pipeline.from_pretrained` -- double-loading
        # the model and risking a CUDA OOM on a GPU machine. Double-checked
        # locking avoids taking the lock on the common (already-loaded) path
        # while still serializing the load itself.
        if self._pipeline is None:
            with self._load_lock:
                if self._pipeline is None:
                    self.load()
        output = self._pipeline(recording_path)  # type: ignore[operator, misc]
        turns = [
            DiarizationTurn(start=segment.start, end=segment.end, speaker_label=label)
            for segment, _, label in output.speaker_diarization.itertracks(yield_label=True)
        ]
        speakers: dict[str, list[float]] = {}
        if output.speaker_embeddings is not None:
            labels = output.speaker_diarization.labels()
            for label, embedding in zip(labels, output.speaker_embeddings, strict=True):
                speakers[label] = [float(x) for x in embedding]
        return DiarizationResult(turns=turns, speakers=speakers)
