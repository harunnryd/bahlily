from __future__ import annotations

import asyncio
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import grpc
import grpc.aio
import pytest
from fastapi.testclient import TestClient

from bahlily_transcription.app import _diarize_jobs, _select_whisper_manifest_name, _sessions
from bahlily_transcription.diarize_engine import DiarizationResult, DiarizationTurn
from bahlily_transcription.grpc_client import AudioCoreClient
from bahlily_transcription.jobs import DiarizeJobState, SessionState
from bahlily_transcription.models import DiarizeJobStatus
from bahlily_transcription.pb.audio_core.v1 import audio_pb2, audio_pb2_grpc


@pytest.fixture
def client() -> TestClient:
    from bahlily_transcription.app import app

    return TestClient(app)


def test_select_whisper_manifest_name_uses_mlx_on_apple_silicon() -> None:
    with patch("bahlily_transcription.app._is_apple_silicon", return_value=True):
        assert _select_whisper_manifest_name() == "whisper_mlx"


def test_select_whisper_manifest_name_uses_default_off_apple_silicon() -> None:
    with patch("bahlily_transcription.app._is_apple_silicon", return_value=False):
        assert _select_whisper_manifest_name() == "whisper"


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_list_models_whisper_returns_entries(client: TestClient) -> None:
    response = client.get("/models/whisper")
    assert response.status_code == 200
    names = {m["name"] for m in response.json()}
    assert "tiny" in names


def test_list_models_invalid_engine_returns_404(client: TestClient) -> None:
    response = client.get("/models/nonexistent")
    assert response.status_code == 404


def test_load_model_calls_engine(client: TestClient) -> None:
    mock_engine = MagicMock()
    with patch("bahlily_transcription.app._whisper_engine", mock_engine):
        response = client.post("/models/whisper/load", json={"name": "tiny"})
    assert response.status_code == 200
    mock_engine.load_model.assert_called_once_with("tiny")


def test_post_session_returns_recording_id(client: TestClient) -> None:
    with (
        patch("bahlily_transcription.app._whisper_engine") as mock_engine,
        patch("bahlily_transcription.app._start_worker_task"),
    ):
        mock_engine.is_model_loaded.return_value = True
        mock_engine.current_model.return_value = "tiny"
        response = client.post("/sessions", json={"engine": "whisper", "language": "fr"})
    assert response.status_code == 200
    assert "recording_id" in response.json()


def test_post_session_auto_selects_parakeet_for_english(client: TestClient) -> None:
    with (
        patch("bahlily_transcription.app._parakeet_engine") as mock_engine,
        patch("bahlily_transcription.app._start_worker_task"),
    ):
        mock_engine.is_model_loaded.return_value = True
        mock_engine.current_model.return_value = "nemo-parakeet-tdt-0.6b-v3"
        response = client.post("/sessions", json={"language": "en"})
    assert response.status_code == 200


def test_post_session_no_model_returns_409(client: TestClient) -> None:
    with patch("bahlily_transcription.app._whisper_engine") as mock_engine:
        mock_engine.is_model_loaded.return_value = False
        response = client.post("/sessions", json={"engine": "whisper"})
    assert response.status_code == 409
    assert response.json()["code"] == "TRANSCRIPTION_MODEL_NOT_LOADED"


def test_get_session_not_found_returns_404(client: TestClient) -> None:
    response = client.get("/sessions/nonexistent-id")
    assert response.status_code == 404


def test_delete_model_removes_from_registry(tmp_path: pytest.TempPathFactory) -> None:
    from importlib import resources
    from pathlib import Path

    from bahlily_transcription.app import app
    from bahlily_transcription.models import ModelStatus
    from bahlily_transcription.registry import ModelRegistry
    from bahlily_transcription.whisper_engine import WhisperEngine

    models_dir = Path(str(tmp_path)) / "models"
    manifests_dir = Path(str(resources.files("bahlily_transcription") / "manifests"))
    real_registry = ModelRegistry("whisper", models_dir, manifests_dir)
    real_engine = WhisperEngine(models_dir=models_dir / "whisper")

    # Create the model directory and a model.bin so the registry sees it as AVAILABLE.
    model_dir = models_dir / "whisper" / "tiny"
    model_dir.mkdir(parents=True)
    (model_dir / "model.bin").write_bytes(b"fake")
    real_registry._status["tiny"] = ModelStatus.AVAILABLE

    with (
        patch("bahlily_transcription.app._whisper_engine", real_engine),
        patch("bahlily_transcription.app._whisper_registry", real_registry),
    ):
        client = TestClient(app)
        response = client.delete("/models/whisper/tiny")

    assert response.status_code == 200
    assert real_registry.get_status("tiny") == ModelStatus.MISSING
    assert not model_dir.exists()


def test_stop_session_returns_segment_count(client: TestClient) -> None:
    from bahlily_transcription.jobs import JobStore, SessionState

    mock_worker = MagicMock()
    mock_worker.stop = AsyncMock(return_value=5)
    real_store: JobStore[SessionState] = JobStore(
        ttl_seconds=3600.0,
        sweep_interval_seconds=60.0,
        is_terminal=lambda s: s.status in {"failed", "completed"},
    )
    real_store.put("test-id", SessionState(status="started", worker=mock_worker))
    with patch("bahlily_transcription.app._sessions", real_store):
        response = client.post("/sessions/test-id/stop")
    assert response.status_code == 200
    assert response.json()["segments_transcribed"] == 5
    with pytest.raises(KeyError):
        real_store.get("test-id")


def _diarize_request_body() -> dict[str, object]:
    return {
        "recording_path": "/data/recordings/m1.flac",
        "segments": [
            {
                "text": "hello",
                "segment_id": 0,
                "is_partial": False,
                "engine": "whisper",
                "model_name": "tiny",
                "audio_start_time": 0.0,
                "audio_end_time": 1.0,
                "recording_id": "m1",
                "trace_id": "t1",
            }
        ],
    }


def test_start_diarize_without_hf_token_returns_422(client: TestClient) -> None:
    with patch.dict("os.environ", {}, clear=True):
        resp = client.post("/diarize", json=_diarize_request_body())
    assert resp.status_code == 422
    assert resp.json()["code"] == "TRANSCRIPTION_DIARIZATION_UNAVAILABLE"


def test_get_diarize_job_not_found(client: TestClient) -> None:
    resp = client.get("/diarize/missing-job-id")
    assert resp.status_code == 404
    assert resp.json()["code"] == "TRANSCRIPTION_JOB_NOT_FOUND"


def test_diarize_job_completes_and_is_polled_successfully(client: TestClient) -> None:
    fake_result = DiarizationResult(
        turns=[DiarizationTurn(start=0.0, end=1.0, speaker_label="Speaker 1")],
        speakers={"Speaker 1": [0.1, 0.2]},
    )

    with (
        patch.dict("os.environ", {"BAHLILY_TRANSCRIPTION_HF_TOKEN": "test-token"}),
        patch(
            "bahlily_transcription.app._diarize_engine.run",
            return_value=fake_result,
        ),
    ):
        resp = client.post("/diarize", json=_diarize_request_body())
        assert resp.status_code == 202
        job_id = resp.json()["job_id"]

        for _ in range(200):
            poll = client.get(f"/diarize/{job_id}")
            if poll.json()["status"] == "completed":
                break
            time.sleep(0.05)
        else:
            raise AssertionError("diarize job never completed")

    assert poll.json()["segments"][0]["speaker_cluster_label"] == "Speaker 1"
    assert poll.json()["speakers"][0]["cluster_label"] == "Speaker 1"
    assert poll.json()["speakers"][0]["voice_embedding"] == [0.1, 0.2]


def test_diarize_job_failure_is_polled_as_failed_with_a_populated_error(
    client: TestClient,
) -> None:
    with (
        patch.dict("os.environ", {"BAHLILY_TRANSCRIPTION_HF_TOKEN": "test-token"}),
        patch(
            "bahlily_transcription.app._diarize_engine.run",
            side_effect=RuntimeError("boom"),
        ),
    ):
        resp = client.post("/diarize", json=_diarize_request_body())
        assert resp.status_code == 202
        job_id = resp.json()["job_id"]

        for _ in range(200):
            poll = client.get(f"/diarize/{job_id}")
            if poll.json()["status"] in ("completed", "failed"):
                break
            time.sleep(0.05)
        else:
            raise AssertionError("diarize job never reached a terminal status")

    assert poll.json()["status"] == "failed"
    error = poll.json()["error"]
    assert isinstance(error, str) and error
    assert "TRANSCRIPTION_DIARIZATION_FAILED" in error
    assert "boom" not in error


def test_get_diarize_job_completed_then_evicted(client: TestClient) -> None:
    job_id = "test-job-completed"
    _diarize_jobs.put(
        job_id,
        DiarizeJobState(
            status=DiarizeJobStatus.COMPLETED,
            result=([], []),
            error=None,
        ),
    )
    response = client.get(f"/diarize/{job_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    response = client.get(f"/diarize/{job_id}")
    assert response.status_code == 404
    assert response.json()["code"] == "TRANSCRIPTION_JOB_NOT_FOUND"


def test_get_diarize_job_failed_then_evicted(client: TestClient) -> None:
    job_id = "test-job-failed"
    _diarize_jobs.put(
        job_id,
        DiarizeJobState(
            status=DiarizeJobStatus.FAILED,
            result=None,
            error="boom",
        ),
    )
    response = client.get(f"/diarize/{job_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    response = client.get(f"/diarize/{job_id}")
    assert response.status_code == 404
    assert response.json()["code"] == "TRANSCRIPTION_JOB_NOT_FOUND"


def test_get_diarize_job_pending_does_not_evict(client: TestClient) -> None:
    job_id = "test-job-pending"
    _diarize_jobs.put(job_id, DiarizeJobState(status=DiarizeJobStatus.PENDING))
    response = client.get(f"/diarize/{job_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "pending"
    response = client.get(f"/diarize/{job_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "pending"


def test_get_session_failed_then_evicted(client: TestClient) -> None:
    recording_id = "test-session-failed"
    fake_worker = MagicMock()
    _sessions.put(recording_id, SessionState(status="failed", worker=fake_worker))
    response = client.get(f"/sessions/{recording_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    response = client.get(f"/sessions/{recording_id}")
    assert response.status_code == 404
    assert response.json() == {"detail": "session not found"}


def test_get_session_completed_then_evicted(client: TestClient) -> None:
    recording_id = "test-session-completed"
    fake_worker = MagicMock()
    _sessions.put(recording_id, SessionState(status="completed", worker=fake_worker))
    response = client.get(f"/sessions/{recording_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    response = client.get(f"/sessions/{recording_id}")
    assert response.status_code == 404
    assert response.json() == {"detail": "session not found"}


def test_get_session_started_does_not_evict(client: TestClient) -> None:
    recording_id = "test-session-started"
    fake_worker = MagicMock()
    _sessions.put(recording_id, SessionState(status="started", worker=fake_worker))
    response = client.get(f"/sessions/{recording_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "started"
    response = client.get(f"/sessions/{recording_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "started"


def test_lifespan_starts_and_stops_sweepers() -> None:
    from bahlily_transcription.app import app

    with TestClient(app) as client:
        client.get("/health")
    with TestClient(app) as client:
        client.get("/health")


@asynccontextmanager
async def _fake_audio_core_server() -> AsyncIterator[int]:
    server = grpc.aio.server()

    class _NoOpAudio(audio_pb2_grpc.AudioServiceServicer):
        async def StreamAudio(
            self,
            request: audio_pb2.StreamAudioRequest,
            context: grpc.aio.ServicerContext,
        ) -> AsyncIterator[audio_pb2.StreamAudioResponse]:
            await asyncio.Event().wait()
            yield audio_pb2.StreamAudioResponse()

    audio_pb2_grpc.add_AudioServiceServicer_to_server(  # type: ignore[no-untyped-call]
        _NoOpAudio(), server
    )
    port = server.add_insecure_port("[::]:0")
    await server.start()
    try:
        yield port
    finally:
        await server.stop(grace=None)


def test_lifespan_creates_shared_audiocore_client() -> None:
    from bahlily_transcription import app as app_module
    from bahlily_transcription.app import app

    async def _run() -> None:
        async with _fake_audio_core_server() as port:
            with patch.dict(os.environ, {"AUDIO_CORE_GRPC_ADDR": f"localhost:{port}"}):
                assert app_module._audio_core_client is None
                async with app.router.lifespan_context(app):
                    assert app_module._audio_core_client is not None
                    assert isinstance(app_module._audio_core_client, AudioCoreClient)
                assert app_module._audio_core_client is None
                async with app.router.lifespan_context(app):
                    assert app_module._audio_core_client is not None
                    assert isinstance(app_module._audio_core_client, AudioCoreClient)
                assert app_module._audio_core_client is None

    asyncio.run(_run())


def test_lifespan_clears_partial_state_when_audiocore_construction_fails() -> None:
    from bahlily_transcription import app as app_module
    from bahlily_transcription.app import app

    def _boom(addr: str = "localhost:50051") -> AudioCoreClient:
        raise RuntimeError("simulated startup failure")

    async def _run() -> None:
        with patch("bahlily_transcription.app.AudioCoreClient", side_effect=_boom):
            with pytest.raises(RuntimeError):
                async with app.router.lifespan_context(app):
                    pass

    asyncio.run(_run())
    assert app_module._audio_core_client is None
