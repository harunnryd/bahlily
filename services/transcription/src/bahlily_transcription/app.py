from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncGenerator
from concurrent.futures import ThreadPoolExecutor
from importlib import resources
from pathlib import Path

import structlog
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from starlette.requests import Request

from bahlily_transcription.errors import (
    TranscriptionAlreadyDownloadingError,
    TranscriptionInsufficientDiskError,
    TranscriptionModelNotFoundError,
    TranscriptionModelNotLoadedError,
    TranscriptionUnsupportedLanguageError,
)
from bahlily_transcription.grpc_server import BroadcastChannel
from bahlily_transcription.parakeet_engine import ParakeetEngine
from bahlily_transcription.registry import ModelRegistry
from bahlily_transcription.whisper_engine import WhisperEngine
from bahlily_transcription.worker import SessionWorker

_log = structlog.get_logger()

_MODELS_DIR = Path(os.environ.get("BAHLILY_MODELS_DIR", str(Path.home() / ".bahlily" / "models")))
_MANIFESTS_DIR = Path(str(resources.files("bahlily_transcription") / "manifests"))

_whisper_engine = WhisperEngine(models_dir=_MODELS_DIR / "whisper")
_parakeet_engine = ParakeetEngine(models_dir=_MODELS_DIR / "parakeet")
_whisper_registry = ModelRegistry("whisper", _MODELS_DIR, _MANIFESTS_DIR)
_parakeet_registry = ModelRegistry("parakeet", _MODELS_DIR, _MANIFESTS_DIR)
_broadcast = BroadcastChannel()
_executor = ThreadPoolExecutor(max_workers=4)
_sessions: dict[str, dict[str, object]] = {}

app = FastAPI(title="bahlily-transcription")

_ENGINES: dict[str, tuple[WhisperEngine | ParakeetEngine, ModelRegistry]] = {
    "whisper": (_whisper_engine, _whisper_registry),
    "parakeet": (_parakeet_engine, _parakeet_registry),
}

_ERROR_STATUS: dict[type[Exception], int] = {
    TranscriptionModelNotLoadedError: 409,
    TranscriptionModelNotFoundError: 404,
    TranscriptionAlreadyDownloadingError: 409,
    TranscriptionInsufficientDiskError: 422,
    TranscriptionUnsupportedLanguageError: 422,
}


@app.exception_handler(TranscriptionModelNotLoadedError)
@app.exception_handler(TranscriptionModelNotFoundError)
@app.exception_handler(TranscriptionAlreadyDownloadingError)
@app.exception_handler(TranscriptionInsufficientDiskError)
@app.exception_handler(TranscriptionUnsupportedLanguageError)
async def _error_handler(request: Request, exc: Exception) -> JSONResponse:
    status = _ERROR_STATUS[type(exc)]
    return JSONResponse(status_code=status, content={"code": exc.code, "message": str(exc)})  # type: ignore[attr-defined]


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "engines": {
            "whisper": {
                "loaded": _whisper_engine.is_model_loaded(),
                "model": _whisper_engine.current_model(),
            },
            "parakeet": {
                "loaded": _parakeet_engine.is_model_loaded(),
                "model": _parakeet_engine.current_model(),
            },
        },
    }


@app.get("/models/{engine}")
def list_models(engine: str) -> list[dict[str, object]]:
    if engine not in _ENGINES:
        raise HTTPException(status_code=404, detail=f"unknown engine '{engine}'")
    _, registry = _ENGINES[engine]
    models = registry.list_models()
    return [
        {
            "name": m.name,
            "engine": m.engine,
            "tier": m.tier,
            "size_bytes": m.size_bytes,
            "status": registry.get_status(m.name).value,
        }
        for m in models
    ]


@app.get("/models/{engine}/current")
def current_model(engine: str) -> dict[str, str | None]:
    if engine not in _ENGINES:
        raise HTTPException(status_code=404, detail=f"unknown engine '{engine}'")
    eng, _ = _ENGINES[engine]
    return {"model": eng.current_model()}


class LoadModelRequest(BaseModel):
    name: str


@app.post("/models/{engine}/load")
def load_model(engine: str, req: LoadModelRequest) -> dict[str, str]:
    if engine not in _ENGINES:
        raise HTTPException(status_code=404, detail=f"unknown engine '{engine}'")
    eng, _ = _ENGINES[engine]
    eng.load_model(req.name)
    return {"engine": engine, "model": req.name, "status": "loaded"}


@app.post("/models/{engine}/download/{name}")
async def download_model(engine: str, name: str) -> EventSourceResponse:
    if engine not in _ENGINES:
        raise HTTPException(status_code=404, detail=f"unknown engine '{engine}'")
    _, registry = _ENGINES[engine]

    async def _event_generator() -> AsyncGenerator[dict[str, str], None]:
        async for progress in registry.download(name):
            yield {
                "data": (
                    f'{{"model_name":"{progress.model_name}",'
                    f'"bytes_downloaded":{progress.bytes_downloaded},'
                    f'"total_bytes":{progress.total_bytes},'
                    f'"status":"{progress.status.value}"}}'
                ),
            }

    return EventSourceResponse(_event_generator(), ping=15)


@app.post("/models/{engine}/download/{name}/cancel")
def cancel_download(engine: str, name: str) -> dict[str, str]:
    if engine not in _ENGINES:
        raise HTTPException(status_code=404, detail=f"unknown engine '{engine}'")
    _, registry = _ENGINES[engine]
    registry.cancel_download(name)
    return {"status": "cancelled"}


@app.delete("/models/{engine}/{name}")
def remove_model(engine: str, name: str) -> dict[str, str]:
    if engine not in _ENGINES:
        raise HTTPException(status_code=404, detail=f"unknown engine '{engine}'")
    eng, registry = _ENGINES[engine]
    loaded = eng.current_model()
    if loaded == name:
        eng.unload_model()
    registry.remove(name)
    return {"status": "removed"}


class StartSessionRequest(BaseModel):
    engine: str | None = None
    model: str | None = None
    language: str | None = None


def _select_engine(req: StartSessionRequest) -> tuple[WhisperEngine | ParakeetEngine, str]:
    if req.engine == "whisper" or (req.language and req.language != "en"):
        eng: WhisperEngine | ParakeetEngine = _whisper_engine
        name = "whisper"
    else:
        eng = _parakeet_engine
        name = "parakeet"
    if not eng.is_model_loaded():
        raise TranscriptionModelNotLoadedError(name)
    return eng, name


def _start_worker_task(
    recording_id: str,
    engine: WhisperEngine | ParakeetEngine,
    language: str | None,
) -> None:
    from bahlily_transcription.grpc_client import AudioCoreClient

    client = AudioCoreClient(addr=os.environ.get("AUDIO_CORE_GRPC_ADDR", "localhost:50051"))
    # TODO: creates one AudioCoreClient per session; spec intends one shared client
    # with per-session workers subscribing to the same broadcast. Refactor when a
    # shared client is added.
    worker = SessionWorker(
        recording_id=recording_id,
        engine=engine,
        broadcast=_broadcast,
        executor=_executor,
        language=language,
    )
    _sessions[recording_id] = {"status": "started", "worker": worker}

    async def _run() -> None:
        await worker.run(client.stream_segments())

    asyncio.create_task(_run())


@app.post("/sessions")
async def start_session(req: StartSessionRequest) -> dict[str, str]:
    engine, _ = _select_engine(req)
    recording_id = str(uuid.uuid4())
    _start_worker_task(recording_id, engine, req.language)
    return {"recording_id": recording_id, "status": "started"}


@app.post("/sessions/{recording_id}/stop")
async def stop_session(recording_id: str) -> dict[str, object]:
    if recording_id not in _sessions:
        raise HTTPException(status_code=404, detail="session not found")
    session = _sessions[recording_id]
    worker: SessionWorker = session["worker"]  # type: ignore[assignment]
    session["status"] = "stopping"
    transcribed = await worker.stop()
    session["status"] = "stopped"
    return {
        "recording_id": recording_id,
        "status": "stopped",
        "segments_transcribed": transcribed,
    }


@app.get("/sessions/{recording_id}")
def get_session(recording_id: str) -> dict[str, object]:
    if recording_id not in _sessions:
        raise HTTPException(status_code=404, detail="session not found")
    session = _sessions[recording_id]
    return {"recording_id": recording_id, "status": session["status"]}
