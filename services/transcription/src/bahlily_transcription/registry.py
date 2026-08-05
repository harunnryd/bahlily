from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import re
import shutil
import threading
from collections.abc import AsyncGenerator
from pathlib import Path, PurePosixPath
from typing import Any

import structlog
import yaml
from huggingface_hub import hf_hub_download

from bahlily_transcription.errors import (
    TranscriptionAlreadyDownloadingError,
    TranscriptionChecksumFailedError,
    TranscriptionInsufficientDiskError,
    TranscriptionModelNotFoundError,
)
from bahlily_transcription.models import DownloadProgress, ModelFile, ModelInfo, ModelStatus

_CHUNK_SIZE = 8 * 1024
_GLOB_CHARS_PATTERN = re.compile(r"[*?\[\]]")

# How often to log a warning while waiting for the worker thread during cleanup.
_CLEANUP_WAIT_POLL_SECONDS = 30

_log = structlog.get_logger()


def _verify_file_sha(path: Path, expected_sha: str) -> bool:
    sha256 = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(_CHUNK_SIZE), b""):
            sha256.update(chunk)
    return sha256.hexdigest() == expected_sha


def _verify_files(model_path: Path, files: tuple[ModelFile, ...]) -> bool:
    """Verify every file exists and matches its SHA-256 checksum. Always re-hashes."""
    for file in files:
        target = model_path / file.path
        if not target.is_file() or not _verify_file_sha(target, file.sha256):
            return False
    return True


class ModelRegistry:
    def __init__(self, engine: str, models_dir: Path, manifests_dir: Path) -> None:
        self._engine = engine
        self._models_dir = models_dir / engine
        self._models_dir.mkdir(parents=True, exist_ok=True)
        self._manifests_dir = manifests_dir
        self._manifest: dict[str, ModelInfo] = {}
        self._status: dict[str, ModelStatus] = {}
        self._in_flight: set[str] = set()
        self._cancelled: set[str] = set()
        self._lock = threading.Lock()
        self._load_manifest()
        self._scan_existing()

    def list_models(self) -> list[ModelInfo]:
        return list(self._manifest.values())

    def get_status(self, name: str) -> ModelStatus:
        if name not in self._manifest:
            raise TranscriptionModelNotFoundError(name)
        return self._status.get(name, ModelStatus.MISSING)

    async def download(self, name: str) -> AsyncGenerator[DownloadProgress, None]:
        if name not in self._manifest:
            raise TranscriptionModelNotFoundError(name)

        info = self._get_model_info(name)
        model_dir = self._models_dir / name
        free = shutil.disk_usage(self._models_dir).free
        if free < info.size_bytes:
            raise TranscriptionInsufficientDiskError(info.size_bytes, free)

        with self._lock:
            if name in self._in_flight:
                raise TranscriptionAlreadyDownloadingError(name)
            self._in_flight.add(name)
            self._cancelled.discard(name)
            self._status[name] = ModelStatus.DOWNLOADING

        def _download_and_verify() -> None:
            for file in info.files:
                if name in self._cancelled:
                    return
                target = model_dir / file.path
                hf_hub_download(
                    repo_id=info.repo_id,
                    repo_type="model",
                    filename=file.path,
                    revision=info.revision,
                    local_dir=model_dir,
                )
                if target.is_file() and _verify_file_sha(target, file.sha256):
                    continue
                if name in self._cancelled:
                    return
                # Mismatch: retry once, bypassing any corrupt local cache.
                hf_hub_download(
                    repo_id=info.repo_id,
                    repo_type="model",
                    filename=file.path,
                    revision=info.revision,
                    local_dir=model_dir,
                    force_download=True,
                )
                if not target.is_file() or not _verify_file_sha(target, file.sha256):
                    raise TranscriptionChecksumFailedError(name)
            if name in self._cancelled:
                return

        try:
            model_dir.mkdir(parents=True, exist_ok=True)
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            concurrent_future: concurrent.futures.Future[None] = executor.submit(
                _download_and_verify
            )
        except Exception:
            with self._lock:
                self._in_flight.discard(name)
                self._cancelled.discard(name)
                self._status[name] = ModelStatus.MISSING
            raise

        asyncio_future = asyncio.wrap_future(concurrent_future)
        try:
            try:
                await asyncio_future
                with self._lock:
                    if name in self._cancelled:
                        self._status[name] = ModelStatus.MISSING
                        return
                    self._status[name] = ModelStatus.AVAILABLE
                yield DownloadProgress(
                    model_name=name,
                    engine=self._engine,
                    bytes_downloaded=info.size_bytes,
                    total_bytes=info.size_bytes,
                    status=ModelStatus.AVAILABLE,
                )
            except asyncio.CancelledError:
                with self._lock:
                    self._cancelled.add(name)
                    self._status[name] = ModelStatus.MISSING
                raise
            except Exception:
                with self._lock:
                    self._status[name] = ModelStatus.MISSING
                raise
        finally:
            while True:
                try:
                    await asyncio.wait_for(
                        asyncio.shield(asyncio.wrap_future(concurrent_future)),
                        timeout=_CLEANUP_WAIT_POLL_SECONDS,
                    )
                except TimeoutError:
                    _log.warning(
                        "model_download_cleanup_still_waiting",
                        model_name=name,
                        engine=self._engine,
                    )
                    continue
                except asyncio.CancelledError:
                    if concurrent_future.done():
                        break
                    continue
                except Exception as exc:
                    _log.warning(
                        "model_download_worker_failed_during_cleanup",
                        model_name=name,
                        engine=self._engine,
                        error=str(exc),
                    )
                    break
                break
            with self._lock:
                self._in_flight.discard(name)
                self._cancelled.discard(name)
            executor.shutdown(wait=False)

    def cancel_download(self, name: str) -> None:
        if name not in self._manifest:
            raise TranscriptionModelNotFoundError(name)
        with self._lock:
            if self._status.get(name) != ModelStatus.DOWNLOADING:
                return
            self._cancelled.add(name)
            self._status[name] = ModelStatus.MISSING

    def remove(self, name: str) -> None:
        if name not in self._manifest:
            raise TranscriptionModelNotFoundError(name)
        with self._lock:
            if name in self._in_flight:
                raise TranscriptionAlreadyDownloadingError(name)
            model_dir = self._models_dir / name
            if model_dir.exists():
                shutil.rmtree(model_dir)
            self._status[name] = ModelStatus.MISSING

    def _load_manifest(self) -> None:
        manifest_path = self._manifests_dir / f"{self._engine}.yaml"
        with manifest_path.open() as f:
            raw = yaml.safe_load(f)
        if not isinstance(raw, dict) or "models" not in raw or not isinstance(raw["models"], list):
            raise ValueError(
                f"malformed manifest at {manifest_path}: expected {{models: [...]}} at root"
            )
        models: list[Any] = raw["models"]
        required_top = {"name", "repo_id", "files", "size_bytes", "tier"}
        manifest: dict[str, ModelInfo] = {}
        for i, m in enumerate(models):
            if not isinstance(m, dict):
                raise ValueError(
                    f"malformed manifest at {manifest_path}: entry {i} is not a mapping"
                )
            missing_top = required_top - m.keys()
            if missing_top:
                raise ValueError(
                    f"malformed manifest at {manifest_path}: entry {i} missing fields: "
                    + ", ".join(sorted(missing_top))
                )
            entry_name = m["name"]
            if (
                not isinstance(entry_name, str)
                or not entry_name
                or "/" in entry_name
                or "\\" in entry_name
                or entry_name in (".", "..")
                or entry_name.startswith("/")
            ):
                raise ValueError(
                    f"malformed manifest at {manifest_path}: entry {i} has unsafe name "
                    f"{entry_name!r}"
                )
            if entry_name in manifest:
                raise ValueError(
                    f"malformed manifest at {manifest_path}: duplicate model name "
                    f"{entry_name!r} at entry {i}"
                )
            repo_id = m["repo_id"]
            if (
                not isinstance(repo_id, str)
                or len(repo_id.split("/")) != 2
                or not all(repo_id.split("/"))
            ):
                raise ValueError(
                    f"malformed manifest at {manifest_path}: entry {i} repo_id "
                    f"must be 'owner/name' format with non-empty owner and name, got {repo_id!r}"
                )
            size_bytes = m["size_bytes"]
            if not isinstance(size_bytes, int) or isinstance(size_bytes, bool) or size_bytes < 0:
                raise ValueError(
                    f"malformed manifest at {manifest_path}: entry {i} size_bytes must be "
                    f"non-negative int, got {size_bytes!r}"
                )
            tier = m["tier"]
            if not isinstance(tier, str) or not tier:
                raise ValueError(
                    f"malformed manifest at {manifest_path}: entry {i} tier must be "
                    f"non-empty string, got {tier!r}"
                )
            revision = m.get("revision")
            if revision is not None and (not isinstance(revision, str) or not revision):
                raise ValueError(
                    f"malformed manifest at {manifest_path}: entry {i} revision must be "
                    f"a non-empty string when provided, got {revision!r}"
                )
            raw_files = m["files"]
            if not isinstance(raw_files, list) or not raw_files:
                raise ValueError(
                    f"malformed manifest at {manifest_path}: entry {i} files must be non-empty list"
                )
            files: list[ModelFile] = []
            seen_paths: set[str] = set()
            for j, raw_file in enumerate(raw_files):
                if not isinstance(raw_file, dict):
                    raise ValueError(
                        f"malformed manifest at {manifest_path}: entry {i} file {j} not a mapping"
                    )
                required_file = {"path", "sha256"}
                missing_file = required_file - raw_file.keys()
                if missing_file:
                    raise ValueError(
                        f"malformed manifest at {manifest_path}: entry {i} file {j} "
                        "missing fields: " + ", ".join(sorted(missing_file))
                    )
                file_path = raw_file["path"]
                if (
                    not isinstance(file_path, str)
                    or not file_path
                    or file_path.startswith("/")
                    or ".." in file_path.split("/")
                    or "\\" in file_path
                ):
                    raise ValueError(
                        f"malformed manifest at {manifest_path}: entry {i} file {j} path "
                        f"{file_path!r} must be relative without .. components"
                    )
                normalized = PurePosixPath(file_path)
                if not normalized.parts or str(normalized) != file_path:
                    raise ValueError(
                        f"malformed manifest at {manifest_path}: entry {i} file {j} path "
                        f"{file_path!r} is not a canonical relative POSIX path"
                    )
                if _GLOB_CHARS_PATTERN.search(file_path):
                    raise ValueError(
                        f"malformed manifest at {manifest_path}: entry {i} file {j} path "
                        f"{file_path!r} must not contain glob metacharacters (*, ?, [, ])"
                    )
                if file_path in seen_paths:
                    raise ValueError(
                        f"malformed manifest at {manifest_path}: entry {i} file {j} "
                        f"duplicate path {file_path!r}"
                    )
                seen_paths.add(file_path)
                file_sha = raw_file["sha256"]
                if (
                    not isinstance(file_sha, str)
                    or len(file_sha) != 64
                    or any(c not in "0123456789abcdef" for c in file_sha)
                ):
                    raise ValueError(
                        f"malformed manifest at {manifest_path}: entry {i} file {j} sha256 "
                        f"must be exactly 64 lowercase hex characters"
                    )
                files.append(ModelFile(path=file_path, sha256=file_sha))
            manifest[entry_name] = ModelInfo(
                name=entry_name,
                engine=self._engine,
                size_bytes=m["size_bytes"],
                repo_id=repo_id,
                files=tuple(files),
                tier=m["tier"],
                revision=revision,
            )
        self._manifest = manifest

    def _scan_existing(self) -> None:
        for name, info in self._manifest.items():
            model_path = self._models_dir / name
            if _verify_files(model_path, info.files):
                self._status[name] = ModelStatus.AVAILABLE
            else:
                self._status[name] = ModelStatus.MISSING

    def _get_model_info(self, name: str) -> ModelInfo:
        return self._manifest[name]
