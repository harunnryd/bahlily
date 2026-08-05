from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, field_validator


@dataclass(frozen=True)
class TranscriptResult:
    text: str
    confidence: float | None
    language: str | None
    audio_start_time: float
    audio_end_time: float


@dataclass(frozen=True)
class ModelFile:
    path: str
    sha256: str


@dataclass(frozen=True)
class ModelInfo:
    name: str
    engine: str
    size_bytes: int
    repo_id: str
    files: tuple[ModelFile, ...]
    tier: str
    revision: str | None = None


class ModelStatus(Enum):
    AVAILABLE = "available"
    MISSING = "missing"
    DOWNLOADING = "downloading"
    ERROR = "error"
    CORRUPTED = "corrupted"


@dataclass(frozen=True)
class DownloadProgress:
    model_name: str
    engine: str
    bytes_downloaded: int
    total_bytes: int
    status: ModelStatus


class TranscriptSegmentSchema(BaseModel):
    text: str
    segment_id: int
    confidence: float | None = None
    is_partial: bool
    engine: str
    model_name: str
    audio_start_time: float
    audio_end_time: float
    language: str | None = None
    recording_id: str
    trace_id: str
    speaker_cluster_label: str | None = None


class DiarizeRequest(BaseModel):
    recording_path: str
    segments: list[TranscriptSegmentSchema]

    @field_validator("recording_path")
    @classmethod
    def _reject_path_traversal(cls, value: str) -> str:
        # This service has no established "recordings root" to confine
        # against -- `recording_path` is handed to it by the UI coordinator
        # from wherever shell/audio-core actually wrote the file (a Tauri
        # app_data_dir-based path this service can't independently know).
        # These checks defend against traversal-style manipulation without
        # assuming any specific root directory. Symlink-based attacks are
        # deliberately out of scope: that defense requires the file to
        # already exist at validation time and assumes a materially
        # stronger attacker foothold (local filesystem write access) than
        # one who can only craft an HTTP request body.
        if not Path(value).is_absolute():
            raise ValueError("recording_path must be an absolute path")
        if ".." in Path(value).parts:
            raise ValueError("recording_path must not contain '..' path segments")
        return value


class DiarizeSpeaker(BaseModel):
    cluster_label: str
    voice_embedding: list[float]


class DiarizeJobStatus(str, Enum):  # noqa: UP042
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class DiarizeJobResponse(BaseModel):
    status: DiarizeJobStatus
    segments: list[TranscriptSegmentSchema] | None = None
    speakers: list[DiarizeSpeaker] | None = None
    error: str | None = None
