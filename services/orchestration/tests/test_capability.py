from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from bahlily_orchestration.app import app


@pytest.fixture
def gated_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("BAHLILY_CAPABILITY", "secret-test-token")
    return TestClient(app)


def test_capability_required_rejects_request_without_header(
    gated_client: TestClient,
) -> None:
    response = gated_client.get("/templates")
    assert response.status_code == 401


def test_capability_required_rejects_request_with_wrong_header(
    gated_client: TestClient,
) -> None:
    response = gated_client.get(
        "/templates",
        headers={"x-bahlily-capability": "wrong"},
    )
    assert response.status_code == 401


def test_capability_required_accepts_correct_header(gated_client: TestClient) -> None:
    response = gated_client.get(
        "/templates",
        headers={"x-bahlily-capability": "secret-test-token"},
    )
    assert response.status_code == 200


def test_capability_passthrough_when_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BAHLILY_CAPABILITY", raising=False)
    client = TestClient(app)
    response = client.get("/templates")
    assert response.status_code == 200
