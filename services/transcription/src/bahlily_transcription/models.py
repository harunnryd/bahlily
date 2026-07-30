from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


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
