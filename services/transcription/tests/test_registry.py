from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import pytest
import respx

from bahlily_transcription.errors import (
    TranscriptionAlreadyDownloadingError,
    TranscriptionChecksumFailedError,
    TranscriptionInsufficientDiskError,
    TranscriptionModelNotFoundError,
)
from bahlily_transcription.models import ModelInfo, ModelStatus
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


def _seed_manifest_entry(
    registry: ModelRegistry,
    name: str,
    content: bytes,
    download_url: str = "https://fake.host/model.bin",
) -> str:
    checksum = hashlib.sha256(content).hexdigest()
    registry._manifest[name] = ModelInfo(
        name=name,
        engine=registry._engine,
        size_bytes=len(content),
        checksum_sha256=checksum,
        download_url=download_url,
        tier="fast",
    )
    return checksum


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
    model_file.write_bytes(b"fake model data")
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
    _seed_manifest_entry(registry, "tiny", content)

    with respx.mock:
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
    _seed_manifest_entry(registry, "tiny", content)
    # Replace checksum with a wrong value to force mismatch
    registry._manifest["tiny"] = ModelInfo(
        name="tiny",
        engine=registry._engine,
        size_bytes=len(content),
        checksum_sha256="0" * 64,
        download_url="https://fake.host/model.bin",
        tier="fast",
    )

    with respx.mock:
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
    _seed_manifest_entry(registry, "tiny", content)

    with respx.mock:
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
    assert "tiny" in registry._cancelled
    # _in_flight is cleared by the download generator's finally block, not by cancel_download.
    registry._in_flight.discard("tiny")
    registry._cancelled.discard("tiny")


@pytest.mark.asyncio
async def test_download_raises_on_insufficient_disk(registry: ModelRegistry) -> None:
    registry._manifest["tiny"] = ModelInfo(
        name="tiny",
        engine=registry._engine,
        size_bytes=10**18,
        checksum_sha256="x" * 64,
        download_url="https://fake.host/model.bin",
        tier="fast",
    )
    with pytest.raises(TranscriptionInsufficientDiskError):
        async for _ in registry.download("tiny"):
            pass


def test_scan_existing_removes_stale_uuid_tmp_files(models_dir: Path, manifests_dir: Path) -> None:
    """Startup recovery must remove model_download_*.tmp files left by crashed downloads."""
    model_dir = models_dir / "whisper" / "tiny"
    model_dir.mkdir(parents=True)
    stale_tmp = model_dir / "model_download_deadbeef1234.tmp"
    stale_tmp.write_bytes(b"partial download")

    # Constructing the registry triggers _scan_existing.
    registry = ModelRegistry(engine="whisper", models_dir=models_dir, manifests_dir=manifests_dir)

    assert not stale_tmp.exists()
    assert registry.get_status("tiny") == ModelStatus.MISSING


@pytest.mark.asyncio
async def test_cancel_during_download_stops_progress(
    registry: ModelRegistry, models_dir: Path
) -> None:
    """Cancelling mid-download must stop yielding progress events immediately."""
    from bahlily_transcription.registry import _CHUNK_SIZE

    # Content large enough to guarantee at least two chunks.
    content = b"x" * (_CHUNK_SIZE + 1)
    _seed_manifest_entry(registry, "tiny", content)

    events = []
    with respx.mock:
        respx.get("https://fake.host/model.bin").mock(
            return_value=httpx.Response(200, content=content)
        )
        async for progress in registry.download("tiny"):
            events.append(progress)
            if len(events) == 1:
                registry.cancel_download("tiny")

    # Only the first DOWNLOADING event must be present; no AVAILABLE event.
    assert len(events) == 1
    assert events[0].status == ModelStatus.DOWNLOADING
    assert registry.get_status("tiny") == ModelStatus.MISSING
