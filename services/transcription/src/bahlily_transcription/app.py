from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import AsyncGenerator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from importlib import resources
from pathlib import Path
from typing import cast

import structlog
from bahlily_capability import require_capability as bahlily_capability_require
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from starlette.requests import Request

from bahlily_transcription.diarize_engine import DiarizationResult, DiarizeEngine
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
from bahlily_transcription.grpc_client import AudioCoreClient
from bahlily_transcription.grpc_server import BroadcastChannel
from bahlily_transcription.jobs import (
    DiarizeJobState,
    JobStore,
    SessionState,
)
from bahlily_transcription.merge import assign_speakers
from bahlily_transcription.models import (
    DiarizeJobResponse,
    DiarizeJobStatus,
    DiarizeRequest,
    DiarizeSpeaker,
)
from bahlily_transcription.parakeet_engine import ParakeetEngine
from bahlily_transcription.registry import ModelRegistry
from bahlily_transcription.speaker_match_client import SpeakerMatchClient
from bahlily_transcription.whisper_engine import WhisperEngine, _is_apple_silicon
from bahlily_transcription.worker import SessionWorker

_log = structlog.get_logger()

_MODELS_DIR = Path(os.environ.get("BAHLILY_MODELS_DIR", str(Path.home() / ".bahlily" / "models")))
_MANIFESTS_DIR = Path(str(resources.files("bahlily_transcription") / "manifests"))

_whisper_engine = WhisperEngine(models_dir=_MODELS_DIR / "whisper")
# mlx_whisper needs mlx-community's weights.npz/safetensors layout, which is
# incompatible with the ctranslate2 layout faster-whisper's repos ship - so
# Apple Silicon reads model names against a separate manifest pointing at the
# mlx-community repos instead.
_whisper_manifest_name = "whisper_mlx" if _is_apple_silicon() else "whisper"
_whisper_registry = ModelRegistry(
    "whisper", _MODELS_DIR, _MANIFESTS_DIR, manifest_name=_whisper_manifest_name
)
_parakeet_registry = ModelRegistry("parakeet", _MODELS_DIR, _MANIFESTS_DIR)
_parakeet_engine = ParakeetEngine(
    models_dir=_MODELS_DIR / "parakeet",
    registry=_parakeet_registry,
)
_broadcast = BroadcastChannel()
_audio_core_client: AudioCoreClient | None = None
_executor = ThreadPoolExecutor(max_workers=4)
# Diarization gets its own executor so a long-running /diarize pass (roughly
# doubles inference time versus transcription alone) can't starve real-time
# transcription of the shared pool's worker threads. A single worker is
# intentional: diarize_engine.run() serializes model loading via its own
# lock, so there's no benefit to more workers competing for it, and jobs
# should run one at a time anyway.
_diarize_executor = ThreadPoolExecutor(max_workers=1)
_sessions = JobStore[SessionState](
    ttl_seconds=float(os.environ.get("BAHLILY_TRANSCRIPTION_SESSIONS_TTL_SECONDS", "3600")),
    sweep_interval_seconds=60.0,
    is_terminal=lambda s: s.status in {"failed", "completed"},
)
_diarize_engine = DiarizeEngine()
_match_client = SpeakerMatchClient(storage_url=os.environ.get("BAHLILY_STORAGE_URL"))
_diarize_jobs = JobStore[DiarizeJobState](
    ttl_seconds=float(os.environ.get("BAHLILY_TRANSCRIPTION_DIARIZE_TTL_SECONDS", "3600")),
    sweep_interval_seconds=60.0,
    is_terminal=lambda s: s.status in {DiarizeJobStatus.COMPLETED, DiarizeJobStatus.FAILED},
)


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    global _audio_core_client
    _audio_core_client = AudioCoreClient(
        addr=os.environ.get("AUDIO_CORE_GRPC_ADDR", "localhost:50051"),
    )
    try:
        _sessions.start_sweeper()
        _diarize_jobs.start_sweeper()
        yield
    finally:
        _audio_core_client = None
        try:
            await _sessions.stop_sweeper()
        finally:
            await _diarize_jobs.stop_sweeper()


app = FastAPI(
    title="bahlily-transcription",
    lifespan=_lifespan,
    dependencies=[Depends(bahlily_capability_require)],
)


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
    client = _audio_core_client
    if client is None:
        raise TranscriptionDiarizationFailedError("audio core client not initialized")
    worker = SessionWorker(
        recording_id=recording_id,
        engine=engine,
        broadcast=_broadcast,
        executor=_executor,
        language=language,
    )
    state = SessionState(status="started", worker=worker)
    _sessions.put(recording_id, state)

    async def _run() -> None:
        try:
            await worker.run(client.stream_segments())
            state.status = "completed"
        except Exception:
            _log.exception(
                "session_worker_failed",
                recording_id=recording_id,
            )
            state.status = "failed"

    asyncio.create_task(_run())


@app.post("/sessions")
async def start_session(req: StartSessionRequest) -> dict[str, str]:
    engine, _ = _select_engine(req)
    recording_id = str(uuid.uuid4())
    _start_worker_task(recording_id, engine, req.language)
    return {"recording_id": recording_id, "status": "started"}


@app.post("/sessions/{recording_id}/stop")
async def stop_session(recording_id: str) -> dict[str, object]:
    try:
        job = _sessions.get(recording_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="session not found") from None
    worker = job.state.worker
    job.state.status = "stopping"
    transcribed = await worker.stop()
    _sessions.discard(recording_id)
    return {
        "recording_id": recording_id,
        "status": "stopped",
        "segments_transcribed": transcribed,
    }


@app.get("/sessions/{recording_id}")
def get_session(recording_id: str) -> dict[str, object]:
    try:
        job = _sessions.get(recording_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="session not found") from None
    status = job.state.status
    if status in {"failed", "completed"}:
        _sessions.discard(recording_id)
    return {"recording_id": recording_id, "status": status}


async def _augment_diarization(
    diarization: DiarizationResult,
    match_client: SpeakerMatchClient,
    job_id: str,
) -> list[DiarizeSpeaker]:
    items = list(diarization.speakers.items())
    if not items:
        return []
    try:
        hits = cast(
            dict[str, dict[str, str]],
            await match_client.match_bulk(items),
        )
    except Exception as exc:
        _log.warning(
            "diarize_speaker_match_failed",
            error=str(exc),
            item_count=len(items),
            job_id=job_id,
        )
        hits = {}
    return [
        DiarizeSpeaker(
            cluster_label=label,
            voice_embedding=embedding,
            matched_profile_id=hits.get(label, {}).get("profile_id"),
            matched_profile_name=hits.get(label, {}).get("profile_name"),
        )
        for label, embedding in items
    ]


@app.post("/diarize", status_code=202)
async def start_diarize(req: DiarizeRequest) -> dict[str, str]:
    if not os.environ.get("BAHLILY_TRANSCRIPTION_HF_TOKEN"):
        raise TranscriptionDiarizationUnavailableError()

    job_id = str(uuid.uuid4())
    state = DiarizeJobState(status=DiarizeJobStatus.PENDING)
    _diarize_jobs.put(job_id, state)

    async def _run() -> None:
        state.status = DiarizeJobStatus.RUNNING
        try:
            loop = asyncio.get_running_loop()
            diarization = await loop.run_in_executor(
                _diarize_executor, _diarize_engine.run, req.recording_path
            )
            labeled_segments = assign_speakers(req.segments, diarization.turns)
            speakers = await _augment_diarization(diarization, _match_client, job_id)
            state.status = DiarizeJobStatus.COMPLETED
            state.result = (labeled_segments, speakers)
            state.error = None
        except Exception as exc:
            _log.exception("diarize_job_failed", job_id=job_id)
            wrapped = TranscriptionDiarizationFailedError(str(exc))
            state.status = DiarizeJobStatus.FAILED
            state.result = None
            state.error = f"{wrapped.code}: diarization failed, see server logs for details"

    asyncio.create_task(_run())
    return {"job_id": job_id}


@app.get("/diarize/{job_id}")
async def get_diarize_job(job_id: str) -> DiarizeJobResponse:
    try:
        job = _diarize_jobs.get(job_id)
    except KeyError:
        raise TranscriptionJobNotFoundError(job_id) from None
    state = job.state
    if state.status == DiarizeJobStatus.COMPLETED:
        assert state.result is not None
        segments, speakers = state.result
        response = DiarizeJobResponse(status=state.status, segments=segments, speakers=speakers)
    elif state.status == DiarizeJobStatus.FAILED:
        response = DiarizeJobResponse(status=state.status, error=state.error or "")
    else:
        response = DiarizeJobResponse(status=state.status)
    if state.status in {DiarizeJobStatus.COMPLETED, DiarizeJobStatus.FAILED}:
        _diarize_jobs.discard(job_id)
    return response
