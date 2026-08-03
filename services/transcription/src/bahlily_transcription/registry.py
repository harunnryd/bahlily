from __future__ import annotations

import asyncio
import hashlib
import shutil
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import httpx
import yaml

from bahlily_transcription.errors import (
    TranscriptionAlreadyDownloadingError,
    TranscriptionChecksumFailedError,
    TranscriptionInsufficientDiskError,
    TranscriptionModelNotFoundError,
)
from bahlily_transcription.models import DownloadProgress, ModelFile, ModelInfo, ModelStatus

_CHUNK_SIZE = 8 * 1024
# Generous read timeout for large model downloads; connect/write timeouts stay at defaults.
_DOWNLOAD_TIMEOUT = httpx.Timeout(timeout=None, connect=10.0)


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

        bytes_downloaded = 0
        try:
            for file in info.files:
                file_bytes = await self._download_one_file(file, model_dir, name)
                bytes_downloaded += file_bytes
                if name in self._cancelled:
                    return
                yield DownloadProgress(
                    model_name=name,
                    engine=self._engine,
                    bytes_downloaded=bytes_downloaded,
                    total_bytes=info.size_bytes,
                    status=ModelStatus.DOWNLOADING,
                )
                if name in self._cancelled:
                    return
            self._status[name] = ModelStatus.AVAILABLE
            yield DownloadProgress(
                model_name=name,
                engine=self._engine,
                bytes_downloaded=bytes_downloaded,
                total_bytes=info.size_bytes,
                status=ModelStatus.AVAILABLE,
            )
        except TranscriptionChecksumFailedError:
            raise
        except Exception:
            self._status[name] = ModelStatus.ERROR
            raise
        finally:
            self._in_flight.discard(name)
            self._cancelled.discard(name)

    async def _download_one_file(self, file: ModelFile, model_dir: Path, name: str) -> int:
        target = model_dir / file.path
        target.parent.mkdir(parents=True, exist_ok=True)
        path_hash = hashlib.sha256(file.path.encode()).hexdigest()[:8]
        tmp_path = model_dir / f".{file.path.replace('/', '__')}.{path_hash}.download.tmp"
        sha256 = hashlib.sha256()
        bytes_downloaded = 0
        try:
            loop = asyncio.get_running_loop()
            async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT) as client:
                async with client.stream("GET", file.url) as response:
                    response.raise_for_status()
                    f = await loop.run_in_executor(None, open, str(tmp_path), "wb")
                    try:
                        async for chunk in response.aiter_bytes(_CHUNK_SIZE):
                            if name in self._cancelled:
                                break
                            await loop.run_in_executor(None, f.write, chunk)
                            sha256.update(chunk)
                            bytes_downloaded += len(chunk)
                    finally:
                        await loop.run_in_executor(None, f.close)

            if name in self._cancelled:
                tmp_path.unlink(missing_ok=True)
                self._status[name] = ModelStatus.MISSING
                return bytes_downloaded

            if sha256.hexdigest() != file.sha256:
                tmp_path.unlink(missing_ok=True)
                self._status[name] = ModelStatus.CORRUPTED
                raise TranscriptionChecksumFailedError(name)

            tmp_path.rename(target)
            return bytes_downloaded
        except TranscriptionChecksumFailedError:
            raise
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

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
        required_top = {"name", "files", "size_bytes", "tier"}
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
            raw_files = m["files"]
            if not isinstance(raw_files, list) or not raw_files:
                raise ValueError(
                    f"malformed manifest at {manifest_path}: entry {i} files must be non-empty list"
                )
            files: list[ModelFile] = []
            for j, raw_file in enumerate(raw_files):
                if not isinstance(raw_file, dict):
                    raise ValueError(
                        f"malformed manifest at {manifest_path}: entry {i} file {j} not a mapping"
                    )
                required_file = {"path", "url", "sha256"}
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
                file_url = raw_file["url"]
                if not isinstance(file_url, str) or not file_url.startswith("https://"):
                    raise ValueError(
                        f"malformed manifest at {manifest_path}: entry {i} file {j} url "
                        f"must be https://"
                    )
                file_sha = raw_file["sha256"]
                if not isinstance(file_sha, str) or (
                    file_sha != "REPLACE_WITH_ACTUAL_SHA256_AFTER_DOWNLOAD"
                    and (len(file_sha) != 64 or any(c not in "0123456789abcdef" for c in file_sha))
                ):
                    raise ValueError(
                        f"malformed manifest at {manifest_path}: entry {i} file {j} sha256 "
                        f"must be 64-char hex or the placeholder string"
                    )
                files.append(ModelFile(path=file_path, url=file_url, sha256=file_sha))
            manifest[entry_name] = ModelInfo(
                name=entry_name,
                engine=self._engine,
                size_bytes=m["size_bytes"],
                files=tuple(files),
                tier=m["tier"],
            )
        self._manifest = manifest

    def _scan_existing(self) -> None:
        for name, info in self._manifest.items():
            model_path = self._models_dir / name
            for tmp in model_path.glob("*.download.tmp"):
                tmp.unlink(missing_ok=True)
            all_present = all((model_path / file.path).exists() for file in info.files)
            all_verified = all_present and all(
                self._verify_checksum(model_path / file.path, file.sha256) for file in info.files
            )
            if all_verified:
                self._status[name] = ModelStatus.AVAILABLE
            elif all_present:
                self._status[name] = ModelStatus.CORRUPTED
            else:
                self._status[name] = ModelStatus.MISSING

    def _verify_checksum(self, path: Path, expected: str) -> bool:
        sha256 = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(_CHUNK_SIZE), b""):
                sha256.update(chunk)
        return sha256.hexdigest() == expected

    def _get_model_info(self, name: str) -> ModelInfo:
        return self._manifest[name]
