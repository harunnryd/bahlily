from __future__ import annotations

from bahlily_logging.errors import BahlilyError


class StorageMeetingNotFoundError(BahlilyError):
    def __init__(self, meeting_id: str) -> None:
        super().__init__(f"meeting '{meeting_id}' not found", code="STORAGE_MEETING_NOT_FOUND")


class StorageMeetingAlreadyExistsError(BahlilyError):
    def __init__(self, meeting_id: str) -> None:
        super().__init__(
            f"meeting '{meeting_id}' already exists",
            code="STORAGE_MEETING_ALREADY_EXISTS",
        )


class StorageSummaryNotFoundError(BahlilyError):
    def __init__(self, meeting_id: str) -> None:
        super().__init__(
            f"no summary for meeting '{meeting_id}'",
            code="STORAGE_SUMMARY_NOT_FOUND",
        )


class StorageSummaryAlreadyExistsError(BahlilyError):
    def __init__(self, meeting_id: str) -> None:
        super().__init__(
            f"summary for meeting '{meeting_id}' already exists",
            code="STORAGE_SUMMARY_ALREADY_EXISTS",
        )


class StorageTemplateNotFoundError(BahlilyError):
    def __init__(self, template_id: str) -> None:
        super().__init__(
            f"template '{template_id}' not found",
            code="STORAGE_TEMPLATE_NOT_FOUND",
        )


class StorageSpeakerProfileNotFoundError(BahlilyError):
    def __init__(self, speaker_profile_id: str) -> None:
        super().__init__(
            f"speaker profile '{speaker_profile_id}' not found",
            code="STORAGE_SPEAKER_PROFILE_NOT_FOUND",
        )
