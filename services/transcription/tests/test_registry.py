from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest

from bahlily_transcription.errors import (
    TranscriptionAlreadyDownloadingError,
    TranscriptionChecksumFailedError,
    TranscriptionInsufficientDiskError,
    TranscriptionModelNotFoundError,
)
from bahlily_transcription.models import DownloadProgress, ModelFile, ModelInfo, ModelStatus
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
        "    repo_id: owner/large-v3-turbo\n"
        "    files:\n"
        "      - path: model.bin\n"
        "        sha256: REPLACE_WITH_ACTUAL_SHA256_AFTER_DOWNLOAD\n"
        "    size_bytes: 1628614656\n"
        "    tier: high_accuracy\n"
        "  - name: tiny\n"
        "    repo_id: owner/tiny\n"
        "    files:\n"
        "      - path: model.bin\n"
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
    repo_id: str = "owner/seed",
) -> str:
    checksum = hashlib.sha256(content).hexdigest()
    registry._manifest[name] = ModelInfo(
        name=name,
        engine=registry._engine,
        size_bytes=len(content),
        repo_id=repo_id,
        files=(ModelFile(path="model.bin", sha256=checksum),),
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
    file_contents = b"fake model data"
    actual_sha = hashlib.sha256(file_contents).hexdigest()
    new_files = tuple(
        ModelFile(path=file.path, sha256=actual_sha) for file in registry._manifest["tiny"].files
    )
    registry._manifest["tiny"] = ModelInfo(
        name="tiny",
        engine=registry._engine,
        size_bytes=registry._manifest["tiny"].size_bytes,
        repo_id=registry._manifest["tiny"].repo_id,
        files=new_files,
        tier=registry._manifest["tiny"].tier,
    )
    for file in new_files:
        model_file = model_dir / file.path
        model_file.parent.mkdir(parents=True, exist_ok=True)
        model_file.write_bytes(file_contents)
    registry._scan_existing()
    assert registry.get_status("tiny") == ModelStatus.AVAILABLE


def test_model_not_found_raises(registry: ModelRegistry) -> None:
    with pytest.raises(TranscriptionModelNotFoundError):
        registry.get_status("nonexistent-model")


def _fake_snapshot_download(file_contents: dict[str, bytes], models_dir: Path) -> object:
    def fake(repo_id: str, **kwargs: object) -> str:
        local_dir = Path(str(kwargs["local_dir"]))
        local_dir.mkdir(parents=True, exist_ok=True)
        allow_raw = kwargs.get("allow_patterns")
        allow_list: list[str] | None = (
            [str(p) for p in allow_raw] if isinstance(allow_raw, (list, tuple)) else None
        )
        for path, contents in file_contents.items():
            if allow_list is None or path in allow_list:
                target = local_dir / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(contents)
        return str(local_dir)

    return fake


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
        repo_id="owner/tiny",
        files=(
            ModelFile(
                path="config.json",
                sha256=hashlib.sha256(config).hexdigest(),
            ),
            ModelFile(
                path="model.bin",
                sha256=hashlib.sha256(weights).hexdigest(),
            ),
        ),
        tier="fast",
    )

    file_contents = {"config.json": config, "model.bin": weights}
    with patch(
        "bahlily_transcription.registry.snapshot_download",
        side_effect=_fake_snapshot_download(file_contents, models_dir),
    ):
        events = [progress async for progress in registry.download("tiny")]

    assert len(events) == 1
    assert events[0].status == ModelStatus.AVAILABLE
    assert events[0].bytes_downloaded == len(config) + len(weights)
    assert (models_dir / "whisper" / "tiny" / "config.json").read_bytes() == config
    assert (models_dir / "whisper" / "tiny" / "model.bin").read_bytes() == weights
    assert registry.get_status("tiny") == ModelStatus.AVAILABLE


@pytest.mark.asyncio
async def test_download_sets_error_when_checksum_verification_fails(
    registry: ModelRegistry, models_dir: Path
) -> None:
    config = b"valid config"
    weights = b"corrupted content"
    registry._manifest["tiny"] = ModelInfo(
        name="tiny",
        engine=registry._engine,
        size_bytes=len(config) + len(weights),
        repo_id="owner/tiny",
        files=(
            ModelFile(
                path="config.json",
                sha256=hashlib.sha256(config).hexdigest(),
            ),
            ModelFile(
                path="model.bin",
                sha256="0" * 64,
            ),
        ),
        tier="fast",
    )

    file_contents = {"config.json": config, "model.bin": weights}
    with patch(
        "bahlily_transcription.registry.snapshot_download",
        side_effect=_fake_snapshot_download(file_contents, models_dir),
    ):
        with pytest.raises(TranscriptionChecksumFailedError):
            async for _ in registry.download("tiny"):
                pass

    assert registry.get_status("tiny") == ModelStatus.ERROR


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
        repo_id="owner/tiny",
        files=(
            ModelFile(
                path="model.bin",
                sha256="0" * 64,
            ),
        ),
        tier="fast",
    )
    with pytest.raises(TranscriptionInsufficientDiskError):
        async for _ in registry.download("tiny"):
            pass


def test_scan_existing_does_not_clean_hf_cache(models_dir: Path, manifests_dir: Path) -> None:
    model_dir = models_dir / "whisper" / "tiny"
    model_dir.mkdir(parents=True)
    hf_marker = model_dir / ".cache" / "huggingface"
    hf_marker.mkdir(parents=True)
    (hf_marker / "metadata.json").write_text("{}")

    registry = ModelRegistry(engine="whisper", models_dir=models_dir, manifests_dir=manifests_dir)

    assert hf_marker.exists()
    assert (hf_marker / "metadata.json").exists()
    assert registry.get_status("tiny") == ModelStatus.MISSING


@pytest.mark.asyncio
async def test_cancel_during_download_stops_progress(
    registry: ModelRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio
    import threading

    content = b"x" * 1000
    _seed_manifest_entry(registry, "tiny", content)
    started = threading.Event()
    cancel_called = threading.Event()

    def slow_snapshot(repo_id: str, **kwargs: object) -> str:
        started.set()
        if cancel_called.wait(timeout=2.0):
            raise RuntimeError("download cancelled")
        return str(kwargs["local_dir"])

    async def collect_progress() -> list[DownloadProgress]:
        return [progress async for progress in registry.download("tiny")]

    monkeypatch.setattr("bahlily_transcription.registry.snapshot_download", slow_snapshot)
    progress_task = asyncio.create_task(asyncio.to_thread(lambda: asyncio.run(collect_progress())))
    assert await asyncio.to_thread(started.wait, 2.0)
    registry.cancel_download("tiny")
    cancel_called.set()
    with pytest.raises(RuntimeError, match="download cancelled"):
        await progress_task

    assert cancel_called.is_set()
    assert registry.get_status("tiny") in (ModelStatus.ERROR, ModelStatus.MISSING)


def test_load_manifest_rejects_duplicate_model_names(models_dir: Path, manifests_dir: Path) -> None:
    (manifests_dir / "whisper.yaml").write_text(
        "engine: whisper\n"
        "models:\n"
        "  - name: tiny\n"
        "    repo_id: owner/tiny-a\n"
        "    files:\n"
        "      - path: model.bin\n"
        "        sha256: " + "a" * 64 + "\n"
        "    size_bytes: 1000\n"
        "    tier: fast\n"
        "  - name: tiny\n"
        "    repo_id: owner/tiny-b\n"
        "    files:\n"
        "      - path: model.bin\n"
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
        "    repo_id: owner/multi\n"
        "    files:\n"
        "      - path: config.json\n"
        "        sha256: REPLACE_WITH_ACTUAL_SHA256_AFTER_DOWNLOAD\n"
        "      - path: model.bin\n"
        "        sha256: REPLACE_WITH_ACTUAL_SHA256_AFTER_DOWNLOAD\n"
        "    size_bytes: 200\n"
        "    tier: test\n"
    )
    reg = ModelRegistry("whisper", models_dir, manifests_dir)
    info = reg.list_models()[0]
    assert len(info.files) == 2
    assert info.files[0].path == "config.json"
    assert info.files[1].path == "model.bin"
    assert info.repo_id == "owner/multi"


def test_manifest_loader_rejects_absolute_file_path(models_dir: Path, manifests_dir: Path) -> None:
    (manifests_dir / "whisper.yaml").write_text(
        "engine: whisper\n"
        "models:\n"
        "  - name: bad\n"
        "    repo_id: owner/bad\n"
        "    files:\n"
        "      - path: /etc/passwd\n"
        "        sha256: REPLACE_WITH_ACTUAL_SHA256_AFTER_DOWNLOAD\n"
        "    size_bytes: 100\n"
        "    tier: test\n"
    )
    with pytest.raises(ValueError, match="must be relative"):
        ModelRegistry("whisper", models_dir, manifests_dir)


def test_manifest_loader_rejects_invalid_sha256(models_dir: Path, manifests_dir: Path) -> None:
    (manifests_dir / "whisper.yaml").write_text(
        "engine: whisper\n"
        "models:\n"
        "  - name: bad\n"
        "    repo_id: owner/bad\n"
        "    files:\n"
        "      - path: model.bin\n"
        "        sha256: not-a-real-sha\n"
        "    size_bytes: 100\n"
        "    tier: test\n"
    )
    with pytest.raises(ValueError, match="sha256"):
        ModelRegistry("whisper", models_dir, manifests_dir)


def test_manifest_loader_rejects_parent_directory_path(
    models_dir: Path, manifests_dir: Path
) -> None:
    (manifests_dir / "whisper.yaml").write_text(
        "engine: whisper\n"
        "models:\n"
        "  - name: bad\n"
        "    repo_id: owner/bad\n"
        "    files:\n"
        "      - path: ../config.json\n"
        "        sha256: REPLACE_WITH_ACTUAL_SHA256_AFTER_DOWNLOAD\n"
        "    size_bytes: 100\n"
        "    tier: test\n"
    )
    with pytest.raises(ValueError, match="must be relative"):
        ModelRegistry("whisper", models_dir, manifests_dir)


def test_manifest_loader_rejects_backslash_path(models_dir: Path, manifests_dir: Path) -> None:
    (manifests_dir / "whisper.yaml").write_text(
        "engine: whisper\n"
        "models:\n"
        "  - name: bad\n"
        "    repo_id: owner/bad\n"
        "    files:\n"
        "      - path: ..\\evil\\config.json\n"
        "        sha256: REPLACE_WITH_ACTUAL_SHA256_AFTER_DOWNLOAD\n"
        "    size_bytes: 100\n"
        "    tier: test\n"
    )
    with pytest.raises(ValueError, match="must be relative"):
        ModelRegistry("whisper", models_dir, manifests_dir)


def test_manifest_loader_rejects_non_integer_size_bytes(
    models_dir: Path, manifests_dir: Path
) -> None:
    (manifests_dir / "whisper.yaml").write_text(
        "engine: whisper\n"
        "models:\n"
        "  - name: bad\n"
        "    repo_id: owner/bad\n"
        "    files:\n"
        "      - path: model.bin\n"
        "        sha256: REPLACE_WITH_ACTUAL_SHA256_AFTER_DOWNLOAD\n"
        "    size_bytes: '100'\n"
        "    tier: test\n"
    )
    with pytest.raises(ValueError, match="size_bytes"):
        ModelRegistry("whisper", models_dir, manifests_dir)


def test_manifest_loader_rejects_negative_size_bytes(models_dir: Path, manifests_dir: Path) -> None:
    (manifests_dir / "whisper.yaml").write_text(
        "engine: whisper\n"
        "models:\n"
        "  - name: bad\n"
        "    repo_id: owner/bad\n"
        "    files:\n"
        "      - path: model.bin\n"
        "        sha256: REPLACE_WITH_ACTUAL_SHA256_AFTER_DOWNLOAD\n"
        "    size_bytes: -1\n"
        "    tier: test\n"
    )
    with pytest.raises(ValueError, match="size_bytes"):
        ModelRegistry("whisper", models_dir, manifests_dir)


def test_manifest_loader_rejects_boolean_size_bytes(models_dir: Path, manifests_dir: Path) -> None:
    (manifests_dir / "whisper.yaml").write_text(
        "engine: whisper\n"
        "models:\n"
        "  - name: bad\n"
        "    repo_id: owner/bad\n"
        "    files:\n"
        "      - path: model.bin\n"
        "        sha256: REPLACE_WITH_ACTUAL_SHA256_AFTER_DOWNLOAD\n"
        "    size_bytes: true\n"
        "    tier: test\n"
    )
    with pytest.raises(ValueError, match="size_bytes"):
        ModelRegistry("whisper", models_dir, manifests_dir)


def test_manifest_loader_rejects_non_string_tier(models_dir: Path, manifests_dir: Path) -> None:
    (manifests_dir / "whisper.yaml").write_text(
        "engine: whisper\n"
        "models:\n"
        "  - name: bad\n"
        "    repo_id: owner/bad\n"
        "    files:\n"
        "      - path: model.bin\n"
        "        sha256: REPLACE_WITH_ACTUAL_SHA256_AFTER_DOWNLOAD\n"
        "    size_bytes: 100\n"
        "    tier: 123\n"
    )
    with pytest.raises(ValueError, match="tier"):
        ModelRegistry("whisper", models_dir, manifests_dir)


def test_manifest_loader_rejects_empty_tier(models_dir: Path, manifests_dir: Path) -> None:
    (manifests_dir / "whisper.yaml").write_text(
        "engine: whisper\n"
        "models:\n"
        "  - name: bad\n"
        "    repo_id: owner/bad\n"
        "    files:\n"
        "      - path: model.bin\n"
        "        sha256: REPLACE_WITH_ACTUAL_SHA256_AFTER_DOWNLOAD\n"
        "    size_bytes: 100\n"
        "    tier: ''\n"
    )
    with pytest.raises(ValueError, match="tier"):
        ModelRegistry("whisper", models_dir, manifests_dir)


def test_manifest_loader_rejects_duplicate_file_paths(
    models_dir: Path, manifests_dir: Path
) -> None:
    (manifests_dir / "whisper.yaml").write_text(
        "engine: whisper\n"
        "models:\n"
        "  - name: dup\n"
        "    repo_id: owner/dup\n"
        "    files:\n"
        "      - path: model.bin\n"
        "        sha256: REPLACE_WITH_ACTUAL_SHA256_AFTER_DOWNLOAD\n"
        "      - path: model.bin\n"
        "        sha256: REPLACE_WITH_ACTUAL_SHA256_AFTER_DOWNLOAD\n"
        "    size_bytes: 200\n"
        "    tier: test\n"
    )
    with pytest.raises(ValueError, match="duplicate path"):
        ModelRegistry("whisper", models_dir, manifests_dir)


def test_manifest_loader_rejects_missing_repo_id(models_dir: Path, manifests_dir: Path) -> None:
    (manifests_dir / "whisper.yaml").write_text(
        "engine: whisper\n"
        "models:\n"
        "  - name: bad\n"
        "    files:\n"
        "      - path: model.bin\n"
        "        sha256: REPLACE_WITH_ACTUAL_SHA256_AFTER_DOWNLOAD\n"
        "    size_bytes: 100\n"
        "    tier: test\n"
    )
    with pytest.raises(ValueError, match="missing fields"):
        ModelRegistry("whisper", models_dir, manifests_dir)


def test_manifest_loader_rejects_malformed_repo_id(models_dir: Path, manifests_dir: Path) -> None:
    (manifests_dir / "whisper.yaml").write_text(
        "engine: whisper\n"
        "models:\n"
        "  - name: bad\n"
        "    repo_id: just-a-name\n"
        "    files:\n"
        "      - path: model.bin\n"
        "        sha256: REPLACE_WITH_ACTUAL_SHA256_AFTER_DOWNLOAD\n"
        "    size_bytes: 100\n"
        "    tier: test\n"
    )
    with pytest.raises(ValueError, match="owner/name"):
        ModelRegistry("whisper", models_dir, manifests_dir)


def test_manifest_loader_rejects_repo_id_with_single_component(
    models_dir: Path, manifests_dir: Path
) -> None:
    (manifests_dir / "whisper.yaml").write_text(
        "engine: whisper\n"
        "models:\n"
        "  - name: bad\n"
        "    repo_id: just-a-name\n"
        "    files:\n"
        "      - path: model.bin\n"
        "        sha256: REPLACE_WITH_ACTUAL_SHA256_AFTER_DOWNLOAD\n"
        "    size_bytes: 100\n"
        "    tier: test\n"
    )
    with pytest.raises(ValueError, match="owner/name"):
        ModelRegistry("whisper", models_dir, manifests_dir)


def test_manifest_loader_rejects_repo_id_with_empty_components(
    models_dir: Path, manifests_dir: Path
) -> None:
    (manifests_dir / "whisper.yaml").write_text(
        "engine: whisper\n"
        "models:\n"
        "  - name: bad\n"
        '    repo_id: "owner/"\n'
        "    files:\n"
        "      - path: model.bin\n"
        "        sha256: REPLACE_WITH_ACTUAL_SHA256_AFTER_DOWNLOAD\n"
        "    size_bytes: 100\n"
        "    tier: test\n"
    )
    with pytest.raises(ValueError, match="owner/name"):
        ModelRegistry("whisper", models_dir, manifests_dir)


def test_manifest_loader_rejects_dot_file_path(models_dir: Path, manifests_dir: Path) -> None:
    (manifests_dir / "whisper.yaml").write_text(
        "engine: whisper\n"
        "models:\n"
        "  - name: bad\n"
        "    repo_id: owner/name\n"
        "    files:\n"
        '      - path: "."\n'
        "        sha256: REPLACE_WITH_ACTUAL_SHA256_AFTER_DOWNLOAD\n"
        "    size_bytes: 100\n"
        "    tier: test\n"
    )
    with pytest.raises(ValueError, match="canonical"):
        ModelRegistry("whisper", models_dir, manifests_dir)


def test_manifest_loader_rejects_dot_slash_file_path(models_dir: Path, manifests_dir: Path) -> None:
    (manifests_dir / "whisper.yaml").write_text(
        "engine: whisper\n"
        "models:\n"
        "  - name: bad\n"
        "    repo_id: owner/name\n"
        "    files:\n"
        '      - path: "./model.bin"\n'
        "        sha256: REPLACE_WITH_ACTUAL_SHA256_AFTER_DOWNLOAD\n"
        "    size_bytes: 100\n"
        "    tier: test\n"
    )
    with pytest.raises(ValueError, match="canonical"):
        ModelRegistry("whisper", models_dir, manifests_dir)


def test_manifest_loader_rejects_double_slash_file_path(
    models_dir: Path, manifests_dir: Path
) -> None:
    (manifests_dir / "whisper.yaml").write_text(
        "engine: whisper\n"
        "models:\n"
        "  - name: bad\n"
        "    repo_id: owner/name\n"
        "    files:\n"
        '      - path: "dir//model.bin"\n'
        "        sha256: REPLACE_WITH_ACTUAL_SHA256_AFTER_DOWNLOAD\n"
        "    size_bytes: 100\n"
        "    tier: test\n"
    )
    with pytest.raises(ValueError, match="canonical"):
        ModelRegistry("whisper", models_dir, manifests_dir)
