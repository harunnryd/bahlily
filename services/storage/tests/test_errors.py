from __future__ import annotations

from bahlily_storage.errors import (
    StorageMeetingAlreadyExistsError,
    StorageMeetingNotFoundError,
    StorageSummaryAlreadyExistsError,
    StorageSummaryNotFoundError,
)


def test_meeting_not_found_code() -> None:
    assert StorageMeetingNotFoundError("abc").code == "STORAGE_MEETING_NOT_FOUND"


def test_meeting_already_exists_code() -> None:
    assert StorageMeetingAlreadyExistsError("abc").code == "STORAGE_MEETING_ALREADY_EXISTS"


def test_summary_already_exists_code() -> None:
    assert StorageSummaryAlreadyExistsError("abc").code == "STORAGE_SUMMARY_ALREADY_EXISTS"


def test_summary_not_found_code() -> None:
    assert StorageSummaryNotFoundError("abc").code == "STORAGE_SUMMARY_NOT_FOUND"


def test_storage_codes_are_in_error_catalog() -> None:
    """Every storage error code must be registered in the root error catalog."""
    import re
    from pathlib import Path

    catalog = None
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "error-catalog.yaml"
        if candidate.is_file():
            catalog = candidate
            break
    assert catalog is not None
    registered = set(re.findall(r"^- code: (\S+)", catalog.read_text(), flags=re.MULTILINE))

    for exc in (
        StorageMeetingNotFoundError,
        StorageMeetingAlreadyExistsError,
        StorageSummaryAlreadyExistsError,
        StorageSummaryNotFoundError,
    ):
        assert exc("x").code in registered
