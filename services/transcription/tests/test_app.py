from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from bahlily_transcription.diarize_engine import DiarizationResult, DiarizationTurn


@pytest.fixture
def client() -> TestClient:
    from bahlily_transcription.app import app

    return TestClient(app)


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_list_models_whisper_returns_entries(client: TestClient) -> None:
    response = client.get("/models/whisper")
    assert response.status_code == 200
    names = {m["name"] for m in response.json()}
    assert "large-v3-turbo" in names


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
        mock_engine.current_model.return_value = "parakeet-tdt-1.1b"
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
    mock_worker = MagicMock()
    mock_worker.stop = AsyncMock(return_value=5)

    with patch(
        "bahlily_transcription.app._sessions",
        {"test-id": {"status": "started", "worker": mock_worker}},
    ):
        response = client.post("/sessions/test-id/stop")
    assert response.status_code == 200
    assert response.json()["segments_transcribed"] == 5


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

        for _ in range(50):
            poll = client.get(f"/diarize/{job_id}")
            if poll.json()["status"] == "completed":
                break
            time.sleep(0.05)
        else:
            raise AssertionError("diarize job never completed")

    assert poll.json()["segments"][0]["speaker_cluster_label"] == "Speaker 1"
    assert poll.json()["speakers"][0]["cluster_label"] == "Speaker 1"
    assert poll.json()["speakers"][0]["voice_embedding"] == [0.1, 0.2]
