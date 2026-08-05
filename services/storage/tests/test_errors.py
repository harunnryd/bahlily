from __future__ import annotations

from bahlily_storage.errors import (
    StorageEmbeddingDimInvalidError,
    StorageEmbeddingDimNotConfiguredError,
    StorageMeetingAlreadyExistsError,
    StorageMeetingNotFoundError,
    StorageSpeakerClusterNotFoundError,
    StorageSpeakerProfileNameConflictError,
    StorageSpeakerProfileNotFoundError,
    StorageSummaryAlreadyExistsError,
    StorageSummaryNotFoundError,
    StorageTemplateNotFoundError,
)


def test_meeting_not_found_code() -> None:
    assert StorageMeetingNotFoundError("abc").code == "STORAGE_MEETING_NOT_FOUND"


def test_meeting_already_exists_code() -> None:
    assert StorageMeetingAlreadyExistsError("abc").code == "STORAGE_MEETING_ALREADY_EXISTS"


def test_summary_already_exists_code() -> None:
    assert StorageSummaryAlreadyExistsError("abc").code == "STORAGE_SUMMARY_ALREADY_EXISTS"


def test_summary_not_found_code() -> None:
    assert StorageSummaryNotFoundError("abc").code == "STORAGE_SUMMARY_NOT_FOUND"


def test_template_not_found_code() -> None:
    assert StorageTemplateNotFoundError("abc").code == "STORAGE_TEMPLATE_NOT_FOUND"


def test_speaker_profile_not_found_code() -> None:
    assert StorageSpeakerProfileNotFoundError("abc").code == "STORAGE_SPEAKER_PROFILE_NOT_FOUND"


def test_speaker_profile_name_conflict_code() -> None:
    assert (
        StorageSpeakerProfileNameConflictError("abc").code
        == "STORAGE_SPEAKER_PROFILE_NAME_CONFLICT"
    )


def test_speaker_cluster_not_found_code() -> None:
    assert (
        StorageSpeakerClusterNotFoundError("m1", "SPEAKER_01").code
        == "STORAGE_SPEAKER_CLUSTER_NOT_FOUND"
    )


def test_embedding_dim_not_configured_code() -> None:
    assert StorageEmbeddingDimNotConfiguredError().code == "STORAGE_EMBEDDING_DIM_NOT_CONFIGURED"


def test_embedding_dim_invalid_code() -> None:
    assert StorageEmbeddingDimInvalidError("abc").code == "STORAGE_EMBEDDING_DIM_INVALID"


def test_storage_codes_are_in_error_catalog() -> None:
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
        StorageTemplateNotFoundError,
        StorageSpeakerProfileNotFoundError,
        StorageSpeakerProfileNameConflictError,
        StorageEmbeddingDimInvalidError,
    ):
        assert exc("x").code in registered
    assert StorageEmbeddingDimNotConfiguredError().code in registered
    assert StorageSpeakerClusterNotFoundError("m1", "SPEAKER_01").code in registered
