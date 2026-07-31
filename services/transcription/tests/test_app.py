from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


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
