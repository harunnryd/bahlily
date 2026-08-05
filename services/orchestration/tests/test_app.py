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


def test_cors_simple_request_allows_webview_origin() -> None:
    response = client.get("/health", headers={"Origin": "tauri://localhost"})
    assert response.headers["access-control-allow-origin"] == "tauri://localhost"


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
        side_effect=ValueError("unsupported provider"),
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


def test_summarize_returns_422_for_missing_segments() -> None:
    response = client.post(
        "/summarize",
        json={
            "template": {"name": "general", "version": "1.0.0", "system_prompt": "Summarize."},
            "provider": "anthropic",
            "model": "claude-sonnet-4-6",
        },
    )
    assert response.status_code == 422


def test_summarize_returns_422_for_empty_segments() -> None:
    response = client.post(
        "/summarize",
        json={
            "segments": [],
            "template": {"name": "general", "version": "1.0.0", "system_prompt": "Summarize."},
            "provider": "anthropic",
            "model": "claude-sonnet-4-6",
        },
    )
    assert response.status_code == 422


def test_summarize_returns_401_for_provider_auth_failure() -> None:
    class FakeAuthFailModel:
        _llm_type: str = "anthropic-chat"

        def bind_tools(self, *args: object, **kwargs: object) -> "FakeAuthFailModel":
            return self

        def invoke(self, *args: object, **kwargs: object) -> object:
            class AuthError(Exception):
                status_code = 401

            raise AuthError("api key invalid")

    with patch(
        "bahlily_orchestration.summarize.init_chat_model",
        return_value=FakeAuthFailModel(),
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
                "provider": "anthropic",
                "model": "claude-sonnet-4-6",
            },
        )
    assert response.status_code == 401
    assert response.json()["code"] == "ORCHESTRATION_PROVIDER_AUTH_FAILED"

    class FakeUnavailableModel:
        _llm_type: str = "anthropic-chat"

        def bind_tools(self, *args: object, **kwargs: object) -> "FakeUnavailableModel":
            return self

        def invoke(self, *args: object, **kwargs: object) -> object:
            class ServiceUnavailable(Exception):
                status_code = 503

            raise ServiceUnavailable("upstream timeout")

    with patch(
        "bahlily_orchestration.summarize.init_chat_model",
        return_value=FakeUnavailableModel(),
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
                "provider": "anthropic",
                "model": "claude-sonnet-4-6",
            },
        )
    assert response.status_code == 502
    assert response.json()["code"] == "ORCHESTRATION_PROVIDER_UNAVAILABLE"
