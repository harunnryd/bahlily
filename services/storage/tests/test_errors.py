from __future__ import annotations

from bahlily_storage.errors import (
    StorageMeetingAlreadyExistsError,
    StorageMeetingNotFoundError,
    StorageSummaryAlreadyExistsError,
)


def test_meeting_not_found_code() -> None:
    assert StorageMeetingNotFoundError("abc").code == "STORAGE_MEETING_NOT_FOUND"


def test_meeting_already_exists_code() -> None:
    assert StorageMeetingAlreadyExistsError("abc").code == "STORAGE_MEETING_ALREADY_EXISTS"


def test_summary_already_exists_code() -> None:
    assert StorageSummaryAlreadyExistsError("abc").code == "STORAGE_SUMMARY_ALREADY_EXISTS"
