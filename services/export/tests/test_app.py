from __future__ import annotations

import datetime
import io

import pytest
from docx import Document
from fastapi.testclient import TestClient
from pypdf import PdfReader

from bahlily_export.app import app

client = TestClient(app)


def _body() -> dict[str, object]:
    return {
        "title": "Team Standup",
        "overview": "Discussed sprint progress.",
        "key_points": ["Shipped feature X"],
        "action_items": [{"description": "Ship it", "owner": "Alex"}],
        "quotes": [{"speaker": "Alex", "text": "Let's ship it.", "segment_id": 1}],
        "created_at": datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC).isoformat(),
    }


def test_health_returns_ok() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_export_markdown() -> None:
    response = client.post("/export?format=markdown", json=_body())
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert 'attachment; filename="team-standup.md"' in response.headers["content-disposition"]
    assert "Team Standup" in response.content.decode("utf-8")


def test_export_docx() -> None:
    response = client.post("/export?format=docx", json=_body())
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert 'filename="team-standup.docx"' in response.headers["content-disposition"]
    doc = Document(io.BytesIO(response.content))
    assert any("Team Standup" == p.text for p in doc.paragraphs)


def test_export_pdf() -> None:
    response = client.post("/export?format=pdf", json=_body())
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    assert 'filename="team-standup.pdf"' in response.headers["content-disposition"]
    reader = PdfReader(io.BytesIO(response.content))
    assert len(reader.pages) >= 1


def test_export_rejects_unsupported_format() -> None:
    response = client.post("/export?format=xml", json=_body())
    assert response.status_code == 422


def test_export_rejects_missing_format() -> None:
    response = client.post("/export", json=_body())
    assert response.status_code == 422


def test_export_rejects_empty_title() -> None:
    body = _body()
    body["title"] = ""
    response = client.post("/export?format=markdown", json=body)
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("title", "expected_slug"),
    [
        ("Team Standup", "team-standup"),
        ("  Weird!!  Title??  ", "weird-title"),
        ("!!!", "summary"),
    ],
)
def test_export_slugifies_title_for_filename(title: str, expected_slug: str) -> None:
    body = _body()
    body["title"] = title
    response = client.post("/export?format=markdown", json=body)
    assert f'filename="{expected_slug}.md"' in response.headers["content-disposition"]
