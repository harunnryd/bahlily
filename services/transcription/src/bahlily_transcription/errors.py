from __future__ import annotations

from bahlily_logging.errors import BahlilyError


class TranscriptionModelNotLoadedError(BahlilyError):
    def __init__(self, engine: str) -> None:
        super().__init__(f"{engine} has no model loaded", code="TRANSCRIPTION_MODEL_NOT_LOADED")


class TranscriptionAudioTooShortError(BahlilyError):
    def __init__(self, duration_s: float) -> None:
        super().__init__(
            f"audio segment too short ({duration_s:.2f}s < 0.5s)",
            code="TRANSCRIPTION_AUDIO_TOO_SHORT",
        )


class TranscriptionEngineFailedError(BahlilyError):
    def __init__(self, engine: str, reason: str) -> None:
        super().__init__(f"{engine} inference failed: {reason}", code="TRANSCRIPTION_ENGINE_FAILED")


class TranscriptionUnsupportedLanguageError(BahlilyError):
    def __init__(self, language: str, engine: str) -> None:
        super().__init__(
            f"{engine} does not support language '{language}'",
            code="TRANSCRIPTION_UNSUPPORTED_LANGUAGE",
        )


class TranscriptionModelNotFoundError(BahlilyError):
    def __init__(self, name: str) -> None:
        super().__init__(
            f"model '{name}' not found in manifest", code="TRANSCRIPTION_MODEL_NOT_FOUND"
        )


class TranscriptionAlreadyDownloadingError(BahlilyError):
    def __init__(self, name: str) -> None:
        super().__init__(
            f"model '{name}' is already downloading",
            code="TRANSCRIPTION_ALREADY_DOWNLOADING",
        )


class TranscriptionInsufficientDiskError(BahlilyError):
    def __init__(self, needed: int, free: int) -> None:
        super().__init__(
            f"need {needed} bytes but only {free} free",
            code="TRANSCRIPTION_INSUFFICIENT_DISK",
        )


class TranscriptionChecksumFailedError(BahlilyError):
    def __init__(self, name: str) -> None:
        super().__init__(
            f"checksum verification failed for '{name}'",
            code="TRANSCRIPTION_CHECKSUM_FAILED",
        )


class TranscriptionDiarizationUnavailableError(BahlilyError):
    def __init__(self) -> None:
        super().__init__(
            "diarization requires BAHLILY_TRANSCRIPTION_HF_TOKEN to be set",
            code="TRANSCRIPTION_DIARIZATION_UNAVAILABLE",
        )


class TranscriptionDiarizationFailedError(BahlilyError):
    def __init__(self, reason: str) -> None:
        super().__init__(f"diarization failed: {reason}", code="TRANSCRIPTION_DIARIZATION_FAILED")


class TranscriptionJobNotFoundError(BahlilyError):
    def __init__(self, job_id: str) -> None:
        super().__init__(
            f"diarization job '{job_id}' not found", code="TRANSCRIPTION_JOB_NOT_FOUND"
        )
