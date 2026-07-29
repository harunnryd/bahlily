from unittest.mock import patch

from fastapi.testclient import TestClient

from bahlily_orchestration.app import app
from bahlily_orchestration.errors import UnsupportedProviderError
from bahlily_orchestration.models import StructuredSummary, SummarizeResponse

client = TestClient(app)


def test_health_returns_ok() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_templates_lists_built_in_templates() -> None:
    response = client.get("/templates")
    assert response.status_code == 200
    names = {t["name"] for t in response.json()}
    assert names == {"general", "one-on-one", "sales-call"}


def test_summarize_returns_200_with_structured_response() -> None:
    fake_response = SummarizeResponse(
        summary=StructuredSummary(
            title="Standup",
            overview="Quick sync.",
            key_points=[],
            action_items=[],
        ),
        attempts=1,
        provider="anthropic",
        model="claude-sonnet-4-6",
    )
    with patch("bahlily_orchestration.app.summarize", return_value=fake_response):
        response = client.post(
            "/summarize",
            json={
                "segments": [{"text": "Hi", "segment_id": 0}],
                "template": {
                    "name": "general",
                    "version": "1.0.0",
                    "system_prompt": "Summarize.",
                },
                "provider": "anthropic",
                "model": "claude-sonnet-4-6",
            },
        )
    assert response.status_code == 200
    assert response.json()["summary"]["title"] == "Standup"


def test_summarize_returns_400_for_unsupported_provider() -> None:
    with patch(
        "bahlily_orchestration.app.summarize",
        side_effect=UnsupportedProviderError("bad provider"),
    ):
        response = client.post(
            "/summarize",
            json={
                "segments": [{"text": "Hi", "segment_id": 0}],
                "template": {
                    "name": "general",
                    "version": "1.0.0",
                    "system_prompt": "Summarize.",
                },
                "provider": "not-real",
                "model": "x",
            },
        )
    assert response.status_code == 400
    assert response.json()["code"] == "ORCHESTRATION_UNSUPPORTED_PROVIDER"
