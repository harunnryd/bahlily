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
from bahlily_transcription.models import ModelFile, ModelInfo, ModelStatus
from bahlily_transcription.registry import ModelRegistry


@pytest.fixture
def models_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "models"
    directory.mkdir()
    return directory


@pytest.fixture
def manifests_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "manifests"
    directory.mkdir()
    (directory / "whisper.yaml").write_text(
        "engine: whisper\n"
        "models:\n"
        "  - name: large-v3-turbo\n"
        "    files:\n"
        "      - path: model.bin\n"
        "        url: https://example.com/large/model.bin\n"
        "        sha256: REPLACE_WITH_ACTUAL_SHA256_AFTER_DOWNLOAD\n"
        "    size_bytes: 1628614656\n"
        "    tier: high_accuracy\n"
        "  - name: tiny\n"
        "    files:\n"
        "      - path: model.bin\n"
        "        url: https://example.com/tiny/model.bin\n"
        "        sha256: REPLACE_WITH_ACTUAL_SHA256_AFTER_DOWNLOAD\n"
        "    size_bytes: 75968000\n"
        "    tier: fast\n"
    )
    return directory


@pytest.fixture
def registry(models_dir: Path, manifests_dir: Path) -> ModelRegistry:
    return ModelRegistry(engine="whisper", models_dir=models_dir, manifests_dir=manifests_dir)


def _seed_manifest_entry(
    registry: ModelRegistry,
    name: str,
    content: bytes,
    url: str = "https://fake.host/model.bin",
) -> str:
    checksum = hashlib.sha256(content).hexdigest()
    registry._manifest[name] = ModelInfo(
        name=name,
        engine=registry._engine,
        size_bytes=len(content),
        files=(ModelFile(path="model.bin", url=url, sha256=checksum),),
        tier="fast",
    )
    return checksum


def test_list_models_returns_all_manifest_entries(registry: ModelRegistry) -> None:
    models = registry.list_models()
    names = {model.name for model in models}
    assert "large-v3-turbo" in names
    assert "tiny" in names
    assert all(model.files for model in models)


def test_status_missing_when_not_downloaded(registry: ModelRegistry) -> None:
    assert registry.get_status("tiny") == ModelStatus.MISSING


def test_status_available_after_model_dir_created(
    registry: ModelRegistry, models_dir: Path
) -> None:
    model_dir = models_dir / "whisper" / "tiny"
    model_dir.mkdir(parents=True)
    for file in registry._manifest["tiny"].files:
        model_file = model_dir / file.path
        model_file.parent.mkdir(parents=True, exist_ok=True)
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
    config = b'{"model": "tiny"}'
    weights = b"fake model content " * 100
    registry._manifest["tiny"] = ModelInfo(
        name="tiny",
        engine=registry._engine,
        size_bytes=len(config) + len(weights),
        files=(
            ModelFile(
                path="config.json",
                url="https://fake.host/config.json",
                sha256=hashlib.sha256(config).hexdigest(),
            ),
            ModelFile(
                path="model.bin",
                url="https://fake.host/model.bin",
                sha256=hashlib.sha256(weights).hexdigest(),
            ),
        ),
        tier="fast",
    )

    with respx.mock:
        respx.get("https://fake.host/config.json").mock(
            return_value=httpx.Response(200, content=config)
        )
        respx.get("https://fake.host/model.bin").mock(
            return_value=httpx.Response(200, content=weights)
        )
        events = [progress async for progress in registry.download("tiny")]

    assert len(events) == 3
    assert [event.status for event in events] == [
        ModelStatus.DOWNLOADING,
        ModelStatus.DOWNLOADING,
        ModelStatus.AVAILABLE,
    ]
    assert events[0].bytes_downloaded == len(config)
    assert events[1].bytes_downloaded == len(config) + len(weights)
    assert (models_dir / "whisper" / "tiny" / "config.json").read_bytes() == config
    assert (models_dir / "whisper" / "tiny" / "model.bin").read_bytes() == weights
    assert registry.get_status("tiny") == ModelStatus.AVAILABLE


@pytest.mark.asyncio
async def test_download_sets_corrupted_on_checksum_mismatch(
    registry: ModelRegistry, models_dir: Path
) -> None:
    config = b"valid config"
    weights = b"corrupted content"
    registry._manifest["tiny"] = ModelInfo(
        name="tiny",
        engine=registry._engine,
        size_bytes=len(config) + len(weights),
        files=(
            ModelFile(
                path="config.json",
                url="https://fake.host/config.json",
                sha256=hashlib.sha256(config).hexdigest(),
            ),
            ModelFile(
                path="model.bin",
                url="https://fake.host/model.bin",
                sha256="0" * 64,
            ),
        ),
        tier="fast",
    )

    with respx.mock:
        respx.get("https://fake.host/config.json").mock(
            return_value=httpx.Response(200, content=config)
        )
        respx.get("https://fake.host/model.bin").mock(
            return_value=httpx.Response(200, content=weights)
        )
        with pytest.raises(TranscriptionChecksumFailedError):
            async for _ in registry.download("tiny"):
                pass

    model_dir = models_dir / "whisper" / "tiny"
    assert (model_dir / "config.json").read_bytes() == config
    assert not (model_dir / "model.bin").exists()
    assert not list(model_dir.glob("*.download.tmp"))
    assert registry.get_status("tiny") == ModelStatus.CORRUPTED


@pytest.mark.asyncio
async def test_concurrent_download_rejected(registry: ModelRegistry) -> None:
    content = b"x" * 1000
    _seed_manifest_entry(registry, "tiny", content)

    registry._in_flight.add("tiny")
    with pytest.raises(TranscriptionAlreadyDownloadingError):
        async for _ in registry.download("tiny"):
            pass
    registry._in_flight.discard("tiny")


def test_cancel_sets_status_missing(registry: ModelRegistry) -> None:
    registry._status["tiny"] = ModelStatus.DOWNLOADING
    registry._in_flight.add("tiny")
    registry.cancel_download("tiny")
    assert registry.get_status("tiny") == ModelStatus.MISSING
    assert "tiny" in registry._cancelled
    registry._in_flight.discard("tiny")
    registry._cancelled.discard("tiny")


def test_remove_rejects_in_flight_download(registry: ModelRegistry, models_dir: Path) -> None:
    model_dir = models_dir / "whisper" / "tiny"
    model_dir.mkdir(parents=True)
    (model_dir / "model.bin").write_bytes(b"fake")
    registry._status["tiny"] = ModelStatus.DOWNLOADING
    registry._in_flight.add("tiny")

    with pytest.raises(TranscriptionAlreadyDownloadingError):
        registry.remove("tiny")

    assert model_dir.exists()
    registry._in_flight.discard("tiny")


@pytest.mark.asyncio
async def test_download_raises_on_insufficient_disk(registry: ModelRegistry) -> None:
    registry._manifest["tiny"] = ModelInfo(
        name="tiny",
        engine=registry._engine,
        size_bytes=10**18,
        files=(
            ModelFile(
                path="model.bin",
                url="https://fake.host/model.bin",
                sha256="0" * 64,
            ),
        ),
        tier="fast",
    )
    with pytest.raises(TranscriptionInsufficientDiskError):
        async for _ in registry.download("tiny"):
            pass


def test_scan_existing_removes_stale_download_tmp_files(
    models_dir: Path, manifests_dir: Path
) -> None:
    model_dir = models_dir / "whisper" / "tiny"
    model_dir.mkdir(parents=True)
    stale_tmp = model_dir / ".model.bin.download.tmp"
    stale_tmp.write_bytes(b"partial download")

    registry = ModelRegistry(engine="whisper", models_dir=models_dir, manifests_dir=manifests_dir)

    assert not stale_tmp.exists()
    assert registry.get_status("tiny") == ModelStatus.MISSING


@pytest.mark.asyncio
async def test_cancel_during_download_stops_progress(registry: ModelRegistry) -> None:
    content = b"x" * 1000
    _seed_manifest_entry(registry, "tiny", content)

    with respx.mock:
        respx.get("https://fake.host/model.bin").mock(
            return_value=httpx.Response(200, content=content)
        )
        events = []
        async for progress in registry.download("tiny"):
            events.append(progress)
            registry.cancel_download("tiny")

    assert len(events) == 1
    assert events[0].status == ModelStatus.DOWNLOADING
    assert registry.get_status("tiny") == ModelStatus.MISSING


def test_load_manifest_rejects_duplicate_model_names(models_dir: Path, manifests_dir: Path) -> None:
    (manifests_dir / "whisper.yaml").write_text(
        "engine: whisper\n"
        "models:\n"
        "  - name: tiny\n"
        "    files:\n"
        "      - path: model.bin\n"
        "        url: https://example.com/tiny\n"
        "        sha256: " + "a" * 64 + "\n"
        "    size_bytes: 1000\n"
        "    tier: fast\n"
        "  - name: tiny\n"
        "    files:\n"
        "      - path: model.bin\n"
        "        url: https://example.com/tiny2\n"
        "        sha256: " + "b" * 64 + "\n"
        "    size_bytes: 2000\n"
        "    tier: balanced\n"
    )
    with pytest.raises(ValueError, match="duplicate model name"):
        ModelRegistry(engine="whisper", models_dir=models_dir, manifests_dir=manifests_dir)


def test_manifest_loader_rejects_legacy_single_url_field(
    models_dir: Path, manifests_dir: Path
) -> None:
    (manifests_dir / "whisper.yaml").write_text(
        "engine: whisper\n"
        "models:\n"
        "  - name: legacy\n"
        "    download_url: https://example.com/model.bin\n"
        "    size_bytes: 100\n"
        "    tier: test\n"
    )
    with pytest.raises(ValueError, match="missing fields"):
        ModelRegistry("whisper", models_dir, manifests_dir)


def test_manifest_loader_parses_files_list(models_dir: Path, manifests_dir: Path) -> None:
    (manifests_dir / "whisper.yaml").write_text(
        "engine: whisper\n"
        "models:\n"
        "  - name: multi\n"
        "    files:\n"
        "      - path: config.json\n"
        "        url: https://example.com/config.json\n"
        "        sha256: REPLACE_WITH_ACTUAL_SHA256_AFTER_DOWNLOAD\n"
        "      - path: model.bin\n"
        "        url: https://example.com/model.bin\n"
        "        sha256: REPLACE_WITH_ACTUAL_SHA256_AFTER_DOWNLOAD\n"
        "    size_bytes: 200\n"
        "    tier: test\n"
    )
    reg = ModelRegistry("whisper", models_dir, manifests_dir)
    info = reg.list_models()[0]
    assert len(info.files) == 2
    assert info.files[0].path == "config.json"
    assert info.files[1].url == "https://example.com/model.bin"


def test_manifest_loader_rejects_absolute_file_path(models_dir: Path, manifests_dir: Path) -> None:
    (manifests_dir / "whisper.yaml").write_text(
        "engine: whisper\n"
        "models:\n"
        "  - name: bad\n"
        "    files:\n"
        "      - path: /etc/passwd\n"
        "        url: https://example.com/x\n"
        "        sha256: REPLACE_WITH_ACTUAL_SHA256_AFTER_DOWNLOAD\n"
        "    size_bytes: 100\n"
        "    tier: test\n"
    )
    with pytest.raises(ValueError, match="must be relative"):
        ModelRegistry("whisper", models_dir, manifests_dir)


def test_manifest_loader_rejects_non_https_url(models_dir: Path, manifests_dir: Path) -> None:
    (manifests_dir / "whisper.yaml").write_text(
        "engine: whisper\n"
        "models:\n"
        "  - name: bad\n"
        "    files:\n"
        "      - path: model.bin\n"
        "        url: http://insecure.example.com/x\n"
        "        sha256: REPLACE_WITH_ACTUAL_SHA256_AFTER_DOWNLOAD\n"
        "    size_bytes: 100\n"
        "    tier: test\n"
    )
    with pytest.raises(ValueError, match="https://"):
        ModelRegistry("whisper", models_dir, manifests_dir)


def test_manifest_loader_rejects_invalid_sha256(models_dir: Path, manifests_dir: Path) -> None:
    (manifests_dir / "whisper.yaml").write_text(
        "engine: whisper\n"
        "models:\n"
        "  - name: bad\n"
        "    files:\n"
        "      - path: model.bin\n"
        "        url: https://example.com/x\n"
        "        sha256: not-a-real-sha\n"
        "    size_bytes: 100\n"
        "    tier: test\n"
    )
    with pytest.raises(ValueError, match="sha256"):
        ModelRegistry("whisper", models_dir, manifests_dir)
