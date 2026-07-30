from __future__ import annotations

import hashlib
import shutil
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import httpx
import yaml

from bahlily_transcription.engine import TranscriptionEngine
from bahlily_transcription.errors import (
    TranscriptionAlreadyDownloadingError,
    TranscriptionChecksumFailedError,
    TranscriptionInsufficientDiskError,
    TranscriptionModelNotFoundError,
)
from bahlily_transcription.models import DownloadProgress, ModelInfo, ModelStatus

_CHUNK_SIZE = 8 * 1024


class ModelRegistry:
    def __init__(self, engine: str, models_dir: Path, manifests_dir: Path) -> None:
        self._engine = engine
        self._models_dir = models_dir / engine
        self._models_dir.mkdir(parents=True, exist_ok=True)
        self._manifests_dir = manifests_dir
        self._manifest: dict[str, ModelInfo] = {}
        self._status: dict[str, ModelStatus] = {}
        self._in_flight: set[str] = set()
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
        self._status[name] = ModelStatus.DOWNLOADING
        model_dir = self._models_dir / name
        model_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = model_dir / "model.bin.tmp"
        sha256 = hashlib.sha256()
        bytes_downloaded = 0

        try:
            async with httpx.AsyncClient() as client:
                async with client.stream("GET", info.download_url) as response:
                    response.raise_for_status()
                    with open(tmp_path, "ab") as f:
                        async for chunk in response.aiter_bytes(_CHUNK_SIZE):
                            f.write(chunk)
                            sha256.update(chunk)
                            bytes_downloaded += len(chunk)
                            yield DownloadProgress(
                                model_name=name,
                                engine=self._engine,
                                bytes_downloaded=bytes_downloaded,
                                total_bytes=info.size_bytes,
                                status=ModelStatus.DOWNLOADING,
                            )

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

    def cancel_download(self, name: str) -> None:
        self._in_flight.discard(name)
        tmp = self._models_dir / name / "model.bin.tmp"
        tmp.unlink(missing_ok=True)
        self._status[name] = ModelStatus.MISSING

    def remove(self, name: str, engine_instance: TranscriptionEngine | None = None) -> None:
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
        self._manifest = {
            m["name"]: ModelInfo(
                name=m["name"],
                engine=self._engine,
                size_bytes=m["size_bytes"],
                checksum_sha256=m["checksum_sha256"],
                download_url=m["download_url"],
                tier=m["tier"],
            )
            for m in models
        }

    def _scan_existing(self) -> None:
        for name in self._manifest:
            model_path = self._models_dir / name / "model.bin"
            tmp_path = self._models_dir / name / "model.bin.tmp"
            if tmp_path.exists():
                tmp_path.unlink()
                self._status[name] = ModelStatus.MISSING
            elif model_path.exists():
                self._status[name] = ModelStatus.AVAILABLE
            else:
                self._status[name] = ModelStatus.MISSING

    def _refresh_status(self, name: str) -> None:
        model_path = self._models_dir / name / "model.bin"
        if model_path.exists():
            self._status[name] = ModelStatus.AVAILABLE
        else:
            self._status[name] = ModelStatus.MISSING

    def _get_model_info(self, name: str) -> ModelInfo:
        return self._manifest[name]
