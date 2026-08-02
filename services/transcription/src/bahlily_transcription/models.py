from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel


@dataclass(frozen=True)
class TranscriptResult:
    text: str
    confidence: float | None
    language: str | None
    audio_start_time: float
    audio_end_time: float


@dataclass(frozen=True)
class ModelInfo:
    name: str
    engine: str
    size_bytes: int
    checksum_sha256: str
    download_url: str
    tier: str


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
