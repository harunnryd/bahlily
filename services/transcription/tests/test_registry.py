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
        "  - name: medium\n"
        "    repo_id: owner/medium\n"
        "    files:\n"
        "      - path: model.bin\n"
        "        sha256: " + "a" * 64 + "\n"
        "    size_bytes: 1628614656\n"
        "    tier: balanced\n"
        "  - name: tiny\n"
        "    repo_id: owner/tiny\n"
        "    files:\n"
        "      - path: model.bin\n"
        "        sha256: " + "b" * 64 + "\n"
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
    assert "medium" in names
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


def _fake_hf_hub_download(file_contents: dict[str, bytes]) -> object:
    def fake(
        repo_id: str,
        repo_type: str,
        filename: str,
        revision: str | None,
        local_dir: object,
        **kwargs: object,
    ) -> str:
        target = Path(str(local_dir)) / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(file_contents[filename])
        return str(target)

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
        "bahlily_transcription.registry.hf_hub_download",
        side_effect=_fake_hf_hub_download(file_contents),
    ):
        events = [progress async for progress in registry.download("tiny")]

    assert len(events) == 1
    assert events[0].status == ModelStatus.AVAILABLE
    assert events[0].bytes_downloaded == len(config) + len(weights)
    assert (models_dir / "whisper" / "tiny" / "config.json").read_bytes() == config
    assert (models_dir / "whisper" / "tiny" / "model.bin").read_bytes() == weights
    assert registry.get_status("tiny") == ModelStatus.AVAILABLE


@pytest.mark.asyncio
async def test_download_sets_missing_when_checksum_verification_fails(
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
        "bahlily_transcription.registry.hf_hub_download",
        side_effect=_fake_hf_hub_download(file_contents),
    ):
        with pytest.raises(TranscriptionChecksumFailedError):
            async for _ in registry.download("tiny"):
                pass

    assert registry.get_status("tiny") == ModelStatus.MISSING


def test_manifest_loader_rejects_placeholder_sha(models_dir: Path, manifests_dir: Path) -> None:
    (manifests_dir / "whisper.yaml").write_text(
        "engine: whisper\n"
        "models:\n"
        "  - name: bad\n"
        "    repo_id: owner/bad\n"
        "    files:\n"
        "      - path: model.bin\n"
        "        sha256: REPLACE_WITH_ACTUAL_SHA256_AFTER_DOWNLOAD\n"
        "    size_bytes: 100\n"
        "    tier: test\n"
    )
    with pytest.raises(ValueError, match="64 lowercase hex"):
        ModelRegistry("whisper", models_dir, manifests_dir)


def test_manifest_loader_rejects_uppercase_sha(models_dir: Path, manifests_dir: Path) -> None:
    (manifests_dir / "whisper.yaml").write_text(
        "engine: whisper\n"
        "models:\n"
        "  - name: bad\n"
        "    repo_id: owner/bad\n"
        "    files:\n"
        "      - path: model.bin\n"
        "        sha256: " + "A" * 64 + "\n"
        "    size_bytes: 100\n"
        "    tier: test\n"
    )
    with pytest.raises(ValueError, match="64 lowercase hex"):
        ModelRegistry("whisper", models_dir, manifests_dir)


def test_manifest_loader_accepts_real_lowercase_sha(models_dir: Path, manifests_dir: Path) -> None:
    real_sha = hashlib.sha256(b"real model bytes").hexdigest()
    (manifests_dir / "whisper.yaml").write_text(
        "engine: whisper\n"
        "models:\n"
        "  - name: good\n"
        "    repo_id: owner/good\n"
        "    files:\n"
        f"      - path: model.bin\n"
        f"        sha256: {real_sha}\n"
        "    size_bytes: 100\n"
        "    tier: test\n"
    )
    registry = ModelRegistry("whisper", models_dir, manifests_dir)
    info = registry.list_models()[0]
    assert info.files[0].sha256 == real_sha


@pytest.mark.asyncio
async def test_download_succeeds_with_real_sha_after_placeholder_removed(
    registry: ModelRegistry,
) -> None:
    info = registry.list_models()[0]
    content = b"real-content"
    name = info.name
    manifest_dir = registry._manifests_dir
    manifest_path = manifest_dir / f"{registry._engine}.yaml"
    manifest_path.write_text(
        f"engine: {registry._engine}\n"
        "models:\n"
        f"  - name: {name}\n"
        "    repo_id: owner/real\n"
        "    files:\n"
        "      - path: model.bin\n"
        f"        sha256: {hashlib.sha256(content).hexdigest()}\n"
        f"    size_bytes: {len(content)}\n"
        "    tier: test\n"
    )
    fresh_registry = ModelRegistry(
        registry._engine,
        registry._models_dir.parent,
        manifest_dir,
    )

    def fake_download(**kwargs: object) -> str:
        local_dir = kwargs["local_dir"]
        target = Path(str(local_dir)) / str(kwargs["filename"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return str(target)

    with patch("bahlily_transcription.registry.hf_hub_download", side_effect=fake_download):
        progresses = [progress async for progress in fresh_registry.download(name)]

    assert fresh_registry.get_status(name) == ModelStatus.AVAILABLE
    assert any(progress.status == ModelStatus.AVAILABLE for progress in progresses)


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

    def slow_download(**kwargs: object) -> str:
        started.set()
        if cancel_called.wait(timeout=2.0):
            raise RuntimeError("download cancelled")
        return str(kwargs["local_dir"])

    async def collect_progress() -> list[DownloadProgress]:
        return [progress async for progress in registry.download("tiny")]

    monkeypatch.setattr("bahlily_transcription.registry.hf_hub_download", slow_download)
    progress_task = asyncio.create_task(asyncio.to_thread(lambda: asyncio.run(collect_progress())))
    assert await asyncio.to_thread(started.wait, 2.0)
    registry.cancel_download("tiny")
    cancel_called.set()
    with pytest.raises(RuntimeError, match="download cancelled"):
        await progress_task

    assert cancel_called.is_set()
    assert registry.get_status("tiny") is ModelStatus.MISSING


@pytest.mark.asyncio
async def test_cancel_during_async_generator_holds_in_flight_until_worker_dones(
    registry: ModelRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio
    import threading

    info = registry.list_models()[0]
    started = threading.Event()
    release = threading.Event()

    def slow_download(*args: object, **kwargs: object) -> str:
        started.set()
        release.wait(timeout=10.0)
        return str(kwargs.get("local_dir"))

    monkeypatch.setattr("bahlily_transcription.registry.hf_hub_download", slow_download)

    download_gen = registry.download(info.name)
    next_task = asyncio.create_task(download_gen.__anext__())
    await asyncio.to_thread(started.wait, 2.0)
    next_task.cancel()
    await asyncio.sleep(0.1)

    assert info.name in registry._in_flight

    second_gen = registry.download(info.name)
    with pytest.raises(TranscriptionAlreadyDownloadingError):
        async for _ in second_gen:
            pass

    release.set()
    with pytest.raises(asyncio.CancelledError):
        await next_task
    try:
        while True:
            await download_gen.__anext__()
    except StopAsyncIteration:
        pass

    assert registry.get_status(info.name) is ModelStatus.MISSING
    assert info.name not in registry._in_flight
    assert info.name not in registry._cancelled


@pytest.mark.asyncio
async def test_download_resets_status_when_hf_hub_download_raises(
    registry: ModelRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = b"x" * 1000
    _seed_manifest_entry(registry, "tiny", content)

    def failing_download(**kwargs: object) -> str:
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("bahlily_transcription.registry.hf_hub_download", failing_download)

    with pytest.raises(RuntimeError, match="provider unavailable"):
        async for _ in registry.download("tiny"):
            pass

    assert registry.get_status("tiny") == ModelStatus.MISSING


@pytest.mark.asyncio
async def test_cancel_download_before_worker_completes_suppresses_available(
    registry: ModelRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio
    import threading

    content = b"x" * 1000
    _seed_manifest_entry(registry, "tiny", content)
    started = threading.Event()
    release = threading.Event()

    def slow_download(**kwargs: object) -> str:
        started.set()
        release.wait(timeout=10.0)
        target = Path(str(kwargs["local_dir"])) / str(kwargs["filename"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return str(target)

    monkeypatch.setattr("bahlily_transcription.registry.hf_hub_download", slow_download)

    events: list[DownloadProgress] = []

    async def collect() -> None:
        async for progress in registry.download("tiny"):
            events.append(progress)

    task = asyncio.create_task(collect())
    await asyncio.to_thread(started.wait, 2.0)
    registry.cancel_download("tiny")
    release.set()
    await task

    assert events == []
    assert registry.get_status("tiny") == ModelStatus.MISSING


def test_registry_configures_bounded_transfer_timeout() -> None:
    import huggingface_hub.constants as hf_constants

    from bahlily_transcription import registry as registry_module

    assert hf_constants.HF_HUB_DOWNLOAD_TIMEOUT == registry_module._TRANSFER_TIMEOUT_SECONDS
    assert hf_constants.HF_HUB_DOWNLOAD_TIMEOUT == 30


@pytest.mark.asyncio
async def test_cancel_during_single_file_transfer_stops_within_bounded_time(
    registry: ModelRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A single-file model has no between-files boundary to check cancellation
    at -- cancelling while its one file is still 'in flight' must still stop
    the download promptly rather than waiting out the whole transfer."""
    import asyncio
    import threading
    import time

    content = b"x" * 1000
    _seed_manifest_entry(registry, "tiny", content)
    started = threading.Event()
    release = threading.Event()

    def slow_download(**kwargs: object) -> str:
        started.set()
        release.wait(timeout=10.0)
        target = Path(str(kwargs["local_dir"])) / str(kwargs["filename"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return str(target)

    monkeypatch.setattr("bahlily_transcription.registry.hf_hub_download", slow_download)

    events: list[DownloadProgress] = []

    async def collect() -> None:
        async for progress in registry.download("tiny"):
            events.append(progress)

    task = asyncio.create_task(collect())
    await asyncio.to_thread(started.wait, 2.0)
    registry.cancel_download("tiny")
    start = time.monotonic()
    release.set()
    await task
    elapsed = time.monotonic() - start

    assert elapsed < 2.0, f"cleanup took {elapsed:.2f}s, expected a bounded stop"
    assert events == []
    assert registry.get_status("tiny") == ModelStatus.MISSING
    assert "tiny" not in registry._in_flight


@pytest.mark.asyncio
async def test_cancel_during_second_file_download_prevents_available(
    registry: ModelRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio
    import threading

    content_a = b"a" * 100
    content_b = b"b" * 100
    registry._manifest["tiny"] = ModelInfo(
        name="tiny",
        engine=registry._engine,
        size_bytes=len(content_a) + len(content_b),
        repo_id="owner/tiny",
        files=(
            ModelFile(path="a.bin", sha256=hashlib.sha256(content_a).hexdigest()),
            ModelFile(path="b.bin", sha256=hashlib.sha256(content_b).hexdigest()),
        ),
        tier="fast",
    )
    file_contents = {"a.bin": content_a, "b.bin": content_b}
    started = threading.Event()
    release = threading.Event()

    def fake_download(**kwargs: object) -> str:
        filename = str(kwargs["filename"])
        target = Path(str(kwargs["local_dir"])) / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        if filename == "b.bin":
            started.set()
            release.wait(timeout=10.0)
        target.write_bytes(file_contents[filename])
        return str(target)

    monkeypatch.setattr("bahlily_transcription.registry.hf_hub_download", fake_download)

    events: list[DownloadProgress] = []

    async def collect() -> None:
        async for progress in registry.download("tiny"):
            events.append(progress)

    task = asyncio.create_task(collect())
    await asyncio.to_thread(started.wait, 2.0)
    registry.cancel_download("tiny")
    release.set()
    await task

    # Both files were genuinely downloaded with content matching their real
    # checksums -- verification would legitimately pass if not for the
    # cancellation flag, proving cancellation wins even over a fully valid
    # transfer that was already in flight.
    assert (registry._models_dir / "tiny" / "a.bin").read_bytes() == content_a
    assert (registry._models_dir / "tiny" / "b.bin").read_bytes() == content_b
    assert events == []
    assert registry.get_status("tiny") == ModelStatus.MISSING


@pytest.mark.asyncio
async def test_cancel_while_verify_files_is_hashing_prevents_available(
    registry: ModelRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both file transfers complete successfully -- cancellation lands while
    _verify_files() is actively hashing, not during the download step."""
    import asyncio
    import threading

    content = b"x" * 1000
    checksum = _seed_manifest_entry(registry, "tiny", content)

    def fake_download(**kwargs: object) -> str:
        target = Path(str(kwargs["local_dir"])) / str(kwargs["filename"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return str(target)

    verify_started = threading.Event()
    release_verify = threading.Event()

    def blocking_verify(path: Path, expected_sha: str) -> bool:
        verify_started.set()
        release_verify.wait(timeout=10.0)
        return expected_sha == checksum

    monkeypatch.setattr("bahlily_transcription.registry.hf_hub_download", fake_download)
    monkeypatch.setattr("bahlily_transcription.registry._verify_file_sha", blocking_verify)

    events: list[DownloadProgress] = []

    async def collect() -> None:
        async for progress in registry.download("tiny"):
            events.append(progress)

    task = asyncio.create_task(collect())
    await asyncio.to_thread(verify_started.wait, 2.0)
    registry.cancel_download("tiny")
    release_verify.set()
    await task

    # The file downloaded successfully and its checksum genuinely matches --
    # verification would legitimately pass and mark AVAILABLE if not for the
    # cancellation flag being re-checked under lock right before that
    # transition, proving cancellation still wins mid-hash.
    assert (registry._models_dir / "tiny" / "model.bin").read_bytes() == content
    assert events == []
    assert registry.get_status("tiny") == ModelStatus.MISSING


@pytest.mark.asyncio
async def test_checksum_verification_does_not_block_event_loop(
    registry: ModelRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio
    import time

    content = b"x" * 1000
    checksum = _seed_manifest_entry(registry, "tiny", content)

    def fake_download(**kwargs: object) -> str:
        target = Path(str(kwargs["local_dir"])) / str(kwargs["filename"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return str(target)

    def slow_verify(path: Path, expected_sha: str) -> bool:
        time.sleep(0.5)
        return expected_sha == checksum

    monkeypatch.setattr("bahlily_transcription.registry.hf_hub_download", fake_download)
    monkeypatch.setattr("bahlily_transcription.registry._verify_file_sha", slow_verify)

    download_done = False
    ticks_while_pending = 0

    async def ticker() -> None:
        nonlocal ticks_while_pending
        while not download_done:
            await asyncio.sleep(0.01)
            if not download_done:
                ticks_while_pending += 1

    async def run_download() -> None:
        nonlocal download_done
        async for _ in registry.download("tiny"):
            pass
        download_done = True

    ticker_task = asyncio.create_task(ticker())
    await run_download()
    ticker_task.cancel()
    try:
        await ticker_task
    except asyncio.CancelledError:
        pass

    # If verification had blocked the event loop, the ticker would never get
    # a chance to run its sleep loop while the download was still pending.
    assert ticks_while_pending > 0


@pytest.mark.asyncio
async def test_cancel_stops_subsequent_file_downloads(
    registry: ModelRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stalled/slow transfer of one file must not let the loop keep
    launching downloads for the remaining files once cancelled -- the
    transfer actually stops within a bounded time instead of running
    unbounded to completion."""
    import asyncio
    import threading

    content_a = b"a" * 100
    content_b = b"b" * 100
    registry._manifest["tiny"] = ModelInfo(
        name="tiny",
        engine=registry._engine,
        size_bytes=len(content_a) + len(content_b),
        repo_id="owner/tiny",
        files=(
            ModelFile(path="a.bin", sha256=hashlib.sha256(content_a).hexdigest()),
            ModelFile(path="b.bin", sha256=hashlib.sha256(content_b).hexdigest()),
        ),
        tier="fast",
    )
    file_contents = {"a.bin": content_a, "b.bin": content_b}
    started = threading.Event()
    release = threading.Event()
    b_requested = threading.Event()

    def fake_download(**kwargs: object) -> str:
        filename = str(kwargs["filename"])
        if filename == "b.bin":
            b_requested.set()
        target = Path(str(kwargs["local_dir"])) / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        if filename == "a.bin":
            started.set()
            release.wait(timeout=10.0)
        target.write_bytes(file_contents[filename])
        return str(target)

    monkeypatch.setattr("bahlily_transcription.registry.hf_hub_download", fake_download)

    async def collect() -> None:
        async for _ in registry.download("tiny"):
            pass

    task = asyncio.create_task(collect())
    await asyncio.to_thread(started.wait, 2.0)
    registry.cancel_download("tiny")
    release.set()
    await task

    assert not b_requested.is_set(), "download of the next file must not start once cancelled"
    assert registry.get_status("tiny") == ModelStatus.MISSING
    assert "tiny" not in registry._in_flight


def test_scan_existing_skips_rehash_when_marker_matches(
    registry: ModelRegistry, models_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    from bahlily_transcription import registry as registry_module

    content = b"x" * 1000
    _seed_manifest_entry(registry, "tiny", content)
    model_dir = models_dir / "whisper" / "tiny"
    model_dir.mkdir(parents=True)
    (model_dir / "model.bin").write_bytes(content)

    calls: list[Path] = []
    real_verify = registry_module._verify_file_sha

    def counting_verify(path: Path, expected_sha: str) -> bool:
        calls.append(path)
        return real_verify(path, expected_sha)

    monkeypatch.setattr("bahlily_transcription.registry._verify_file_sha", counting_verify)

    registry._scan_existing()
    assert registry.get_status("tiny") == ModelStatus.AVAILABLE
    assert len(calls) == 1

    registry._scan_existing()
    assert registry.get_status("tiny") == ModelStatus.AVAILABLE
    assert len(calls) == 1, "unchanged size/mtime should skip re-hashing"

    target = model_dir / "model.bin"
    stat = target.stat()
    os.utime(target, (stat.st_atime, stat.st_mtime + 5))

    registry._scan_existing()
    assert registry.get_status("tiny") == ModelStatus.AVAILABLE
    assert len(calls) == 2, "a stale mtime should force a re-hash"

    # Marker now reflects this file's current (post-bump) size/mtime -- save
    # those values so scenario (b) below can restore the exact recorded mtime.
    recorded_stat = target.stat()

    # (a) Different-length content is always caught: it changes the recorded
    # size (and, incidentally, the mtime too), so the marker can't match.
    target.write_bytes(content + b"extra-tail-bytes")
    registry._scan_existing()
    assert registry.get_status("tiny") == ModelStatus.MISSING, (
        "a size change must be caught even though a rehash was needed"
    )
    assert len(calls) == 3
    # Verification failed, so the marker was left untouched at its prior
    # (still-valid) recorded values from before this corruption.

    # (b) Known limitation of the size+mtime marker: content corrupted to the
    # exact same length, with the exact recorded mtime restored, is
    # indistinguishable from an unchanged file without re-hashing -- which is
    # exactly the cost this optimization exists to avoid. Detecting this would
    # require hashing the content, defeating the whole point of the marker.
    # This is confirmed here as a documented trade-off, not silently fixed.
    same_length_corruption = bytes(b ^ 0xFF for b in content)
    assert len(same_length_corruption) == recorded_stat.st_size
    target.write_bytes(same_length_corruption)
    os.utime(target, (recorded_stat.st_atime, recorded_stat.st_mtime))

    registry._scan_existing()
    assert registry.get_status("tiny") == ModelStatus.AVAILABLE, (
        "documented limitation: same-size corruption with the exact recorded "
        "mtime restored is trusted without re-hashing"
    )
    assert len(calls) == 3, "marker match short-circuited verification -- no new hash call"


def test_cancel_download_noop_when_not_downloading(registry: ModelRegistry) -> None:
    registry._status["tiny"] = ModelStatus.AVAILABLE
    registry.cancel_download("tiny")
    assert registry.get_status("tiny") == ModelStatus.AVAILABLE
    assert "tiny" not in registry._cancelled


def test_manifest_loader_rejects_non_string_revision(models_dir: Path, manifests_dir: Path) -> None:
    (manifests_dir / "whisper.yaml").write_text(
        "engine: whisper\n"
        "models:\n"
        "  - name: bad\n"
        "    repo_id: owner/bad\n"
        "    revision: 123\n"
        "    files:\n"
        "      - path: model.bin\n"
        "        sha256: " + "a" * 64 + "\n"
        "    size_bytes: 100\n"
        "    tier: test\n"
    )
    with pytest.raises(ValueError, match="revision"):
        ModelRegistry("whisper", models_dir, manifests_dir)


def test_manifest_loader_parses_revision(models_dir: Path, manifests_dir: Path) -> None:
    (manifests_dir / "whisper.yaml").write_text(
        "engine: whisper\n"
        "models:\n"
        "  - name: pinned\n"
        "    repo_id: owner/pinned\n"
        "    revision: abc123\n"
        "    files:\n"
        "      - path: model.bin\n"
        "        sha256: " + "a" * 64 + "\n"
        "    size_bytes: 100\n"
        "    tier: test\n"
    )
    registry = ModelRegistry("whisper", models_dir, manifests_dir)
    assert registry.list_models()[0].revision == "abc123"


def test_manifest_loader_defaults_revision_to_none(models_dir: Path, manifests_dir: Path) -> None:
    registry = ModelRegistry("whisper", models_dir, manifests_dir)
    assert registry.list_models()[0].revision is None


@pytest.mark.asyncio
async def test_download_passes_revision_to_hf_hub_download(
    registry: ModelRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = b"x" * 100
    registry._manifest["tiny"] = ModelInfo(
        name="tiny",
        engine=registry._engine,
        size_bytes=len(content),
        repo_id="owner/tiny",
        files=(ModelFile(path="model.bin", sha256=hashlib.sha256(content).hexdigest()),),
        tier="fast",
        revision="deadbeef",
    )
    seen_revisions: list[object] = []

    def fake_download(**kwargs: object) -> str:
        seen_revisions.append(kwargs["revision"])
        target = Path(str(kwargs["local_dir"])) / str(kwargs["filename"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return str(target)

    monkeypatch.setattr("bahlily_transcription.registry.hf_hub_download", fake_download)
    async for _ in registry.download("tiny"):
        pass

    assert seen_revisions == ["deadbeef"]


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
        "        sha256: " + "a" * 64 + "\n"
        "      - path: model.bin\n"
        "        sha256: " + "b" * 64 + "\n"
        "    size_bytes: 200\n"
        "    tier: test\n"
    )
    reg = ModelRegistry("whisper", models_dir, manifests_dir)
    info = reg.list_models()[0]
    assert len(info.files) == 2
    assert info.files[0].path == "config.json"
    assert info.files[1].path == "model.bin"
    assert info.repo_id == "owner/multi"


def test_manifest_loader_rejects_glob_star_path(models_dir: Path, manifests_dir: Path) -> None:
    (manifests_dir / "whisper.yaml").write_text(
        "engine: whisper\n"
        "models:\n"
        "  - name: bad\n"
        "    repo_id: owner/name\n"
        "    files:\n"
        "      - path: 'model*.bin'\n"
        "        sha256: REPLACE_WITH_ACTUAL_SHA256_AFTER_DOWNLOAD\n"
        "    size_bytes: 100\n"
        "    tier: test\n"
    )
    with pytest.raises(ValueError, match="glob"):
        ModelRegistry("whisper", models_dir, manifests_dir)


def test_manifest_loader_rejects_glob_question_path(models_dir: Path, manifests_dir: Path) -> None:
    (manifests_dir / "whisper.yaml").write_text(
        "engine: whisper\n"
        "models:\n"
        "  - name: bad\n"
        "    repo_id: owner/name\n"
        "    files:\n"
        "      - path: 'model?.bin'\n"
        "        sha256: REPLACE_WITH_ACTUAL_SHA256_AFTER_DOWNLOAD\n"
        "    size_bytes: 100\n"
        "    tier: test\n"
    )
    with pytest.raises(ValueError, match="glob"):
        ModelRegistry("whisper", models_dir, manifests_dir)


def test_manifest_loader_rejects_glob_bracket_path(models_dir: Path, manifests_dir: Path) -> None:
    (manifests_dir / "whisper.yaml").write_text(
        "engine: whisper\n"
        "models:\n"
        "  - name: bad\n"
        "    repo_id: owner/name\n"
        "    files:\n"
        "      - path: 'model[a-z].bin'\n"
        "        sha256: REPLACE_WITH_ACTUAL_SHA256_AFTER_DOWNLOAD\n"
        "    size_bytes: 100\n"
        "    tier: test\n"
    )
    with pytest.raises(ValueError, match="glob"):
        ModelRegistry("whisper", models_dir, manifests_dir)


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
        "        sha256: " + "a" * 64 + "\n"
        "      - path: model.bin\n"
        "        sha256: " + "b" * 64 + "\n"
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


def _packaged_manifests_dir() -> Path:
    return Path(__file__).parent.parent / "src" / "bahlily_transcription" / "manifests"


def test_whisper_manifest_loads_with_no_placeholder_hashes(models_dir: Path) -> None:
    manifest_path = _packaged_manifests_dir() / "whisper.yaml"
    registry = ModelRegistry("whisper", models_dir, _packaged_manifests_dir())
    models = registry.list_models()
    assert models
    for model in models:
        for file in model.files:
            assert len(file.sha256) == 64
            assert all(c in "0123456789abcdef" for c in file.sha256)
    assert "REPLACE_WITH_ACTUAL_SHA256_AFTER_DOWNLOAD" not in manifest_path.read_text()


def test_whisper_manifest_includes_faster_whisper_support_files(models_dir: Path) -> None:
    registry = ModelRegistry("whisper", models_dir, _packaged_manifests_dir())
    required = {"model.bin", "config.json", "tokenizer.json", "vocabulary.txt"}
    for model in registry.list_models():
        paths = {file.path for file in model.files}
        assert required <= paths, f"{model.name} is missing {required - paths}"


def test_whisper_manifest_pins_revision(models_dir: Path) -> None:
    registry = ModelRegistry("whisper", models_dir, _packaged_manifests_dir())
    for model in registry.list_models():
        assert model.revision, f"{model.name} has no pinned revision"


def test_parakeet_manifest_loads_with_no_placeholder_hashes(models_dir: Path) -> None:
    manifest_path = _packaged_manifests_dir() / "parakeet.yaml"
    registry = ModelRegistry("parakeet", models_dir, _packaged_manifests_dir())
    models = registry.list_models()
    assert models
    for model in models:
        for file in model.files:
            assert len(file.sha256) == 64
            assert all(c in "0123456789abcdef" for c in file.sha256)
    assert "REPLACE_WITH_ACTUAL_SHA256_AFTER_DOWNLOAD" not in manifest_path.read_text()


def test_parakeet_manifest_pins_revision(models_dir: Path) -> None:
    registry = ModelRegistry("parakeet", models_dir, _packaged_manifests_dir())
    for model in registry.list_models():
        assert model.revision, f"{model.name} has no pinned revision"
