from __future__ import annotations

import asyncio
import hashlib
import re
import shutil
from collections.abc import AsyncGenerator
from pathlib import Path, PurePosixPath
from typing import Any

import structlog
import yaml
from huggingface_hub import snapshot_download

from bahlily_transcription.errors import (
    TranscriptionAlreadyDownloadingError,
    TranscriptionChecksumFailedError,
    TranscriptionInsufficientDiskError,
    TranscriptionModelNotFoundError,
)
from bahlily_transcription.models import DownloadProgress, ModelFile, ModelInfo, ModelStatus

_CHUNK_SIZE = 8 * 1024
_PLACEHOLDER_SHA = "REPLACE_WITH_ACTUAL_SHA256_AFTER_DOWNLOAD"
_GLOB_CHARS_PATTERN = re.compile(r"[*?\[\]]")

_log = structlog.get_logger()


def _verify_file_sha(path: Path, expected_sha: str) -> bool:
    sha256 = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(_CHUNK_SIZE), b""):
            sha256.update(chunk)
    return sha256.hexdigest() == expected_sha


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
        if name in self._in_flight:
            raise TranscriptionAlreadyDownloadingError(name)

        info = self._get_model_info(name)
        free = shutil.disk_usage(self._models_dir).free
        if free < info.size_bytes:
            raise TranscriptionInsufficientDiskError(info.size_bytes, free)

        self._in_flight.add(name)
        self._cancelled.discard(name)
        self._status[name] = ModelStatus.DOWNLOADING
        model_dir = self._models_dir / name
        model_dir.mkdir(parents=True, exist_ok=True)

        try:
            if name in self._cancelled:
                self._status[name] = ModelStatus.MISSING
                return
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                lambda: snapshot_download(
                    repo_id=info.repo_id,
                    repo_type="model",
                    local_dir=str(model_dir),
                    allow_patterns=[file.path for file in info.files],
                ),
            )
            for file in info.files:
                target = model_dir / file.path
                if not target.exists():
                    self._status[name] = ModelStatus.ERROR
                    raise TranscriptionChecksumFailedError(name)
                if file.sha256 == _PLACEHOLDER_SHA:
                    _log.warning(
                        "model_placeholder_sha_skipped",
                        model_name=name,
                        engine=self._engine,
                        file=file.path,
                    )
                    continue
                if not _verify_file_sha(target, file.sha256):
                    self._status[name] = ModelStatus.ERROR
                    raise TranscriptionChecksumFailedError(name)
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
        except Exception:
            if name in self._cancelled:
                self._status[name] = ModelStatus.MISSING
            else:
                self._status[name] = ModelStatus.ERROR
            raise
        finally:
            self._in_flight.discard(name)
            self._cancelled.discard(name)

    def cancel_download(self, name: str) -> None:
        if name not in self._manifest:
            raise TranscriptionModelNotFoundError(name)
        self._cancelled.add(name)
        self._status[name] = ModelStatus.MISSING

    def remove(self, name: str) -> None:
        if name not in self._manifest:
            raise TranscriptionModelNotFoundError(name)
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
                    or ".." in file_path.split("\\")
                ):
                    raise ValueError(
                        f"malformed manifest at {manifest_path}: entry {i} file {j} path "
                        f"{file_path!r} must be relative without .. components"
                    )
                normalized = PurePosixPath(file_path)
                if not normalized.parts or str(normalized) != file_path or normalized.is_absolute():
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
                if not isinstance(file_sha, str) or (
                    file_sha != _PLACEHOLDER_SHA
                    and (len(file_sha) != 64 or any(c not in "0123456789abcdef" for c in file_sha))
                ):
                    raise ValueError(
                        f"malformed manifest at {manifest_path}: entry {i} file {j} sha256 "
                        f"must be 64-char hex or the placeholder string"
                    )
                files.append(ModelFile(path=file_path, sha256=file_sha))
            manifest[entry_name] = ModelInfo(
                name=entry_name,
                engine=self._engine,
                size_bytes=m["size_bytes"],
                repo_id=repo_id,
                files=tuple(files),
                tier=m["tier"],
            )
        self._manifest = manifest

    def _scan_existing(self) -> None:
        for name, info in self._manifest.items():
            model_path = self._models_dir / name
            all_present = all((model_path / file.path).exists() for file in info.files)
            if all_present:
                self._status[name] = ModelStatus.AVAILABLE
            else:
                self._status[name] = ModelStatus.MISSING

    def _get_model_info(self, name: str) -> ModelInfo:
        return self._manifest[name]
