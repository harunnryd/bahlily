from __future__ import annotations

import asyncio
import hashlib
import shutil
import uuid
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
from bahlily_transcription.models import DownloadProgress, ModelInfo, ModelStatus

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
        tmp_path = model_dir / f"model_download_{uuid.uuid4().hex}.tmp"
        sha256 = hashlib.sha256()
        bytes_downloaded = 0

        try:
            loop = asyncio.get_running_loop()
            async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT) as client:
                async with client.stream("GET", info.download_url) as response:
                    response.raise_for_status()
                    f = await loop.run_in_executor(None, open, tmp_path, "ab")
                    try:
                        async for chunk in response.aiter_bytes(_CHUNK_SIZE):
                            if name in self._cancelled:
                                break
                            await loop.run_in_executor(None, f.write, chunk)
                            sha256.update(chunk)
                            bytes_downloaded += len(chunk)
                            yield DownloadProgress(
                                model_name=name,
                                engine=self._engine,
                                bytes_downloaded=bytes_downloaded,
                                total_bytes=info.size_bytes,
                                status=ModelStatus.DOWNLOADING,
                            )
                    finally:
                        await loop.run_in_executor(None, f.close)

            if name in self._cancelled:
                tmp_path.unlink(missing_ok=True)
                self._status[name] = ModelStatus.MISSING
                return

            if sha256.hexdigest() != info.checksum_sha256:
                tmp_path.unlink(missing_ok=True)
                self._status[name] = ModelStatus.CORRUPTED
                raise TranscriptionChecksumFailedError(name)

            final_path = model_dir / "model.bin"
            tmp_path.rename(final_path)
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
            tmp_path.unlink(missing_ok=True)
            self._status[name] = ModelStatus.ERROR
            raise
        finally:
            self._in_flight.discard(name)
            self._cancelled.discard(name)
            tmp_path.unlink(missing_ok=True)

    def cancel_download(self, name: str) -> None:
        if name not in self._manifest:
            raise TranscriptionModelNotFoundError(name)
        self._cancelled.add(name)
        self._status[name] = ModelStatus.MISSING

    def remove(self, name: str) -> None:
        if name not in self._manifest:
            raise TranscriptionModelNotFoundError(name)
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
        required_fields = {"name", "size_bytes", "checksum_sha256", "download_url", "tier"}
        manifest: dict[str, ModelInfo] = {}
        for i, m in enumerate(models):
            if not isinstance(m, dict):
                raise ValueError(
                    f"malformed manifest at {manifest_path}: entry {i} is not a mapping"
                )
            missing = required_fields - m.keys()
            if missing:
                raise ValueError(
                    f"malformed manifest at {manifest_path}: entry {i} missing fields: "
                    + ", ".join(sorted(missing))
                )
            manifest[m["name"]] = ModelInfo(
                name=m["name"],
                engine=self._engine,
                size_bytes=m["size_bytes"],
                checksum_sha256=m["checksum_sha256"],
                download_url=m["download_url"],
                tier=m["tier"],
            )
        self._manifest = manifest

    def _scan_existing(self) -> None:
        for name, info in self._manifest.items():
            model_path = self._models_dir / name / "model.bin"
            model_dir = self._models_dir / name
            # Remove any stale temporary files from interrupted downloads.
            for tmp in model_dir.glob("model_download_*.tmp"):
                tmp.unlink(missing_ok=True)
            old_tmp = model_dir / "model.bin.tmp"
            if old_tmp.exists():
                old_tmp.unlink()
            if model_path.exists():
                if self._verify_checksum(model_path, info.checksum_sha256):
                    self._status[name] = ModelStatus.AVAILABLE
                else:
                    self._status[name] = ModelStatus.CORRUPTED
            else:
                self._status[name] = ModelStatus.MISSING

    def _verify_checksum(self, path: Path, expected: str) -> bool:
        sha256 = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(_CHUNK_SIZE), b""):
                sha256.update(chunk)
        return sha256.hexdigest() == expected

    def _refresh_status(self, name: str) -> None:
        model_path = self._models_dir / name / "model.bin"
        if model_path.exists():
            self._status[name] = ModelStatus.AVAILABLE
        else:
            self._status[name] = ModelStatus.MISSING

    def _get_model_info(self, name: str) -> ModelInfo:
        return self._manifest[name]
