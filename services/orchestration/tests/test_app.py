import itertools
from unittest.mock import patch

from fastapi.testclient import TestClient

from bahlily_orchestration.app import app
from tests.utils import FakeToolCallingModel, tool_call_message

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
    fake_model = FakeToolCallingModel(
        messages=itertools.cycle(
            [
                tool_call_message(
                    "StructuredSummary",
                    {
                        "title": "Standup",
                        "overview": "Quick sync.",
                        "key_points": [],
                        "action_items": [],
                    },
                )
            ]
        )
    )
    with patch("bahlily_orchestration.summarize.init_chat_model", return_value=fake_model):
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
    assert response.json()["attempts"] >= 1


def test_summarize_returns_400_for_unsupported_provider() -> None:
    with patch(
        "bahlily_orchestration.summarize.init_chat_model",
        side_effect=Exception("unsupported provider"),
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
