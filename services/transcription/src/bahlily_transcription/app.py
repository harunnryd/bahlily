from __future__ import annotations

import asyncio
import json
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

from bahlily_transcription.diarize_engine import DiarizeEngine
from bahlily_transcription.errors import (
    TranscriptionAlreadyDownloadingError,
    TranscriptionChecksumFailedError,
    TranscriptionDiarizationFailedError,
    TranscriptionDiarizationUnavailableError,
    TranscriptionInsufficientDiskError,
    TranscriptionJobNotFoundError,
    TranscriptionModelNotFoundError,
    TranscriptionModelNotLoadedError,
    TranscriptionUnsupportedLanguageError,
)
from bahlily_transcription.grpc_server import BroadcastChannel
from bahlily_transcription.merge import assign_speakers
from bahlily_transcription.models import (
    DiarizeJobResponse,
    DiarizeJobStatus,
    DiarizeRequest,
    DiarizeSpeaker,
    TranscriptSegmentSchema,
)
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
# Diarization gets its own executor so a long-running /diarize pass (roughly
# doubles inference time versus transcription alone) can't starve real-time
# transcription of the shared pool's worker threads. A single worker is
# intentional: diarize_engine.run() serializes model loading via its own
# lock, so there's no benefit to more workers competing for it, and jobs
# should run one at a time anyway.
_diarize_executor = ThreadPoolExecutor(max_workers=1)
_sessions: dict[str, dict[str, object]] = {}
_diarize_engine = DiarizeEngine()
_diarize_jobs: dict[str, dict[str, object]] = {}

app = FastAPI(title="bahlily-transcription")


def _engines() -> dict[str, tuple[WhisperEngine | ParakeetEngine, ModelRegistry]]:
    return {
        "whisper": (_whisper_engine, _whisper_registry),
        "parakeet": (_parakeet_engine, _parakeet_registry),
    }


_ERROR_STATUS: dict[type[Exception], int] = {
    TranscriptionModelNotLoadedError: 409,
    TranscriptionModelNotFoundError: 404,
    TranscriptionAlreadyDownloadingError: 409,
    TranscriptionInsufficientDiskError: 422,
    TranscriptionUnsupportedLanguageError: 422,
    TranscriptionDiarizationUnavailableError: 422,
    TranscriptionJobNotFoundError: 404,
}


@app.exception_handler(TranscriptionModelNotLoadedError)
@app.exception_handler(TranscriptionModelNotFoundError)
@app.exception_handler(TranscriptionAlreadyDownloadingError)
@app.exception_handler(TranscriptionInsufficientDiskError)
@app.exception_handler(TranscriptionUnsupportedLanguageError)
@app.exception_handler(TranscriptionDiarizationUnavailableError)
@app.exception_handler(TranscriptionJobNotFoundError)
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
    engines = _engines()
    if engine not in engines:
        raise HTTPException(status_code=404, detail=f"unknown engine '{engine}'")
    _, registry = engines[engine]
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
    engines = _engines()
    if engine not in engines:
        raise HTTPException(status_code=404, detail=f"unknown engine '{engine}'")
    eng, _ = engines[engine]
    return {"model": eng.current_model()}


class LoadModelRequest(BaseModel):
    name: str


@app.post("/models/{engine}/load")
def load_model(engine: str, req: LoadModelRequest) -> dict[str, str]:
    engines = _engines()
    if engine not in engines:
        raise HTTPException(status_code=404, detail=f"unknown engine '{engine}'")
    eng, _ = engines[engine]
    eng.load_model(req.name)
    return {"engine": engine, "model": req.name, "status": "loaded"}


@app.post("/models/{engine}/download/{name}")
async def download_model(engine: str, name: str) -> EventSourceResponse:
    engines = _engines()
    if engine not in engines:
        raise HTTPException(status_code=404, detail=f"unknown engine '{engine}'")
    _, registry = engines[engine]

    async def _event_generator() -> AsyncGenerator[dict[str, str], None]:
        try:
            async for progress in registry.download(name):
                yield {
                    "data": json.dumps(
                        {
                            "model_name": progress.model_name,
                            "bytes_downloaded": progress.bytes_downloaded,
                            "total_bytes": progress.total_bytes,
                            "status": progress.status.value,
                        }
                    ),
                }
        except (
            TranscriptionModelNotFoundError,
            TranscriptionAlreadyDownloadingError,
            TranscriptionInsufficientDiskError,
            TranscriptionChecksumFailedError,
        ) as exc:
            yield {
                "data": json.dumps({"status": "error", "code": exc.code, "message": str(exc)}),
            }
        except Exception as exc:
            yield {
                "data": json.dumps({"status": "error", "message": str(exc)}),
            }

    return EventSourceResponse(_event_generator(), ping=15)


@app.post("/models/{engine}/download/{name}/cancel")
def cancel_download(engine: str, name: str) -> dict[str, str]:
    engines = _engines()
    if engine not in engines:
        raise HTTPException(status_code=404, detail=f"unknown engine '{engine}'")
    _, registry = engines[engine]
    registry.cancel_download(name)
    return {"status": "cancelled"}


@app.delete("/models/{engine}/{name}")
def remove_model(engine: str, name: str) -> dict[str, str]:
    engines = _engines()
    if engine not in engines:
        raise HTTPException(status_code=404, detail=f"unknown engine '{engine}'")
    eng, registry = engines[engine]
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
    if req.engine == "parakeet":
        if req.language and req.language != "en":
            raise TranscriptionUnsupportedLanguageError(req.language, "parakeet")
        eng: WhisperEngine | ParakeetEngine = _parakeet_engine
        name = "parakeet"
    elif req.engine == "whisper" or (req.language and req.language != "en"):
        eng = _whisper_engine
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
        try:
            await worker.run(client.stream_segments())
        except Exception:
            _log.exception(
                "session_worker_failed",
                recording_id=recording_id,
            )
            _sessions[recording_id]["status"] = "failed"

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
    del _sessions[recording_id]
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


@app.post("/diarize", status_code=202)
async def start_diarize(req: DiarizeRequest) -> dict[str, str]:
    if not os.environ.get("BAHLILY_TRANSCRIPTION_HF_TOKEN"):
        raise TranscriptionDiarizationUnavailableError()

    job_id = str(uuid.uuid4())
    _diarize_jobs[job_id] = {"status": DiarizeJobStatus.PENDING, "result": None, "error": None}

    async def _run() -> None:
        _diarize_jobs[job_id]["status"] = DiarizeJobStatus.RUNNING
        try:
            loop = asyncio.get_running_loop()
            diarization = await loop.run_in_executor(
                _diarize_executor, _diarize_engine.run, req.recording_path
            )
            labeled_segments = assign_speakers(req.segments, diarization.turns)
            speakers = [
                DiarizeSpeaker(cluster_label=label, voice_embedding=embedding)
                for label, embedding in diarization.speakers.items()
            ]
            _diarize_jobs[job_id] = {
                "status": DiarizeJobStatus.COMPLETED,
                "result": (labeled_segments, speakers),
                "error": None,
            }
        except Exception as exc:
            _log.exception("diarize_job_failed", job_id=job_id)
            wrapped = TranscriptionDiarizationFailedError(str(exc))
            _diarize_jobs[job_id] = {
                "status": DiarizeJobStatus.FAILED,
                "result": None,
                "error": f"{wrapped.code}: diarization failed, see server logs for details",
            }

    asyncio.create_task(_run())
    return {"job_id": job_id}


@app.get("/diarize/{job_id}")
async def get_diarize_job(job_id: str) -> DiarizeJobResponse:
    if job_id not in _diarize_jobs:
        raise TranscriptionJobNotFoundError(job_id)
    job = _diarize_jobs[job_id]
    status = job["status"]
    if status == DiarizeJobStatus.COMPLETED:
        result: tuple[list[TranscriptSegmentSchema], list[DiarizeSpeaker]] = job["result"]  # type: ignore[assignment]
        segments, speakers = result
        return DiarizeJobResponse(
            status=status,  # type: ignore[arg-type]
            segments=segments,
            speakers=speakers,
        )
    if status == DiarizeJobStatus.FAILED:
        return DiarizeJobResponse(status=status, error=job["error"])  # type: ignore[arg-type]
    return DiarizeJobResponse(status=status)  # type: ignore[arg-type]
