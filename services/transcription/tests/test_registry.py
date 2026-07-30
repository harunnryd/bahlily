from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx

from bahlily_transcription.errors import (
    TranscriptionAlreadyDownloadingError,
    TranscriptionChecksumFailedError,
    TranscriptionInsufficientDiskError,
    TranscriptionModelNotFoundError,
)
from bahlily_transcription.models import ModelStatus
from bahlily_transcription.registry import ModelRegistry


@pytest.fixture
def models_dir(tmp_path: Path) -> Path:
    d = tmp_path / "models"
    d.mkdir()
    return d


@pytest.fixture
def manifests_dir() -> Path:
    from importlib import resources

    return Path(str(resources.files("bahlily_transcription") / "manifests"))


@pytest.fixture
def registry(models_dir: Path, manifests_dir: Path) -> ModelRegistry:
    return ModelRegistry(engine="whisper", models_dir=models_dir, manifests_dir=manifests_dir)


def test_list_models_returns_all_manifest_entries(registry: ModelRegistry) -> None:
    models = registry.list_models()
    names = {m.name for m in models}
    assert "large-v3-turbo" in names
    assert "tiny" in names


def test_status_missing_when_not_downloaded(registry: ModelRegistry) -> None:
    assert registry.get_status("tiny") == ModelStatus.MISSING


def test_status_available_after_model_dir_created(
    registry: ModelRegistry, models_dir: Path
) -> None:
    model_dir = models_dir / "whisper" / "tiny"
    model_dir.mkdir(parents=True)
    model_file = model_dir / "model.bin"
    content = b"fake model data"
    model_file.write_bytes(content)
    checksum = hashlib.sha256(content).hexdigest()
    with patch.object(registry, "_get_model_info") as mock_info:
        mock_info.return_value = MagicMock(checksum_sha256=checksum)
        registry._refresh_status("tiny")
    assert registry.get_status("tiny") == ModelStatus.AVAILABLE


def test_model_not_found_raises(registry: ModelRegistry) -> None:
    with pytest.raises(TranscriptionModelNotFoundError):
        registry.get_status("nonexistent-model")


@pytest.mark.asyncio
async def test_download_yields_progress_and_verifies_checksum(
    registry: ModelRegistry, models_dir: Path
) -> None:
    content = b"fake model content " * 100
    expected_checksum = hashlib.sha256(content).hexdigest()

    tiny_info = MagicMock()
    tiny_info.name = "tiny"
    tiny_info.download_url = "https://fake.host/model.bin"
    tiny_info.size_bytes = len(content)
    tiny_info.checksum_sha256 = expected_checksum
    tiny_info.tier = "fast"

    with patch.object(registry, "_get_model_info", return_value=tiny_info), respx.mock:
        respx.get("https://fake.host/model.bin").mock(
            return_value=httpx.Response(200, content=content)
        )
        events = []
        async for progress in registry.download("tiny"):
            events.append(progress)

    assert events[-1].status == ModelStatus.AVAILABLE
    assert registry.get_status("tiny") == ModelStatus.AVAILABLE


@pytest.mark.asyncio
async def test_download_sets_corrupted_on_checksum_mismatch(
    registry: ModelRegistry, models_dir: Path
) -> None:
    content = b"corrupted content"
    tiny_info = MagicMock()
    tiny_info.name = "tiny"
    tiny_info.download_url = "https://fake.host/model.bin"
    tiny_info.size_bytes = len(content)
    tiny_info.checksum_sha256 = "0000000000000000000000000000000000000000000000000000000000000000"
    tiny_info.tier = "fast"

    with patch.object(registry, "_get_model_info", return_value=tiny_info), respx.mock:
        respx.get("https://fake.host/model.bin").mock(
            return_value=httpx.Response(200, content=content)
        )
        with pytest.raises(TranscriptionChecksumFailedError):
            async for _ in registry.download("tiny"):
                pass

    assert registry.get_status("tiny") == ModelStatus.CORRUPTED


@pytest.mark.asyncio
async def test_concurrent_download_rejected(registry: ModelRegistry) -> None:
    content = b"x" * 1000
    info = MagicMock()
    info.name = "tiny"
    info.download_url = "https://fake.host/model.bin"
    info.size_bytes = len(content)
    info.checksum_sha256 = hashlib.sha256(content).hexdigest()

    with patch.object(registry, "_get_model_info", return_value=info), respx.mock:
        respx.get("https://fake.host/model.bin").mock(
            return_value=httpx.Response(200, content=content)
        )
        registry._in_flight.add("tiny")
        with pytest.raises(TranscriptionAlreadyDownloadingError):
            async for _ in registry.download("tiny"):
                pass
        registry._in_flight.discard("tiny")


def test_cancel_sets_status_missing(registry: ModelRegistry, models_dir: Path) -> None:
    registry._status["tiny"] = ModelStatus.DOWNLOADING
    registry._in_flight.add("tiny")
    registry.cancel_download("tiny")
    assert registry.get_status("tiny") == ModelStatus.MISSING
    assert "tiny" not in registry._in_flight


@pytest.mark.asyncio
async def test_download_raises_on_insufficient_disk(registry: ModelRegistry) -> None:
    info = MagicMock()
    info.name = "tiny"
    info.download_url = "https://fake.host/model.bin"
    info.size_bytes = 10**18
    info.checksum_sha256 = "x" * 64

    with patch.object(registry, "_get_model_info", return_value=info):
        with pytest.raises(TranscriptionInsufficientDiskError):
            async for _ in registry.download("tiny"):
                pass
