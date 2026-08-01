from __future__ import annotations

import datetime
import io

from pypdf import PdfReader

from bahlily_export.models import ActionItem, ExportRequest, Quote
from bahlily_export.pdf_renderer import render_pdf


def _extracted_text(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() for page in reader.pages)


def test_render_pdf_has_at_least_one_page() -> None:
    req = ExportRequest(
        title="T",
        overview="O",
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
    )
    reader = PdfReader(io.BytesIO(render_pdf(req)))
    assert len(reader.pages) >= 1


def test_render_pdf_includes_title_and_overview() -> None:
    req = ExportRequest(
        title="Team Standup",
        overview="Discussed sprint progress.",
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
    )
    text = _extracted_text(render_pdf(req))
    assert "Team Standup" in text
    assert "Discussed sprint progress." in text


def test_render_pdf_key_points_present() -> None:
    req = ExportRequest(
        title="T",
        overview="O",
        key_points=["First point", "Second point"],
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
    )
    text = _extracted_text(render_pdf(req))
    assert "First point" in text
    assert "Second point" in text


def test_render_pdf_action_item_with_owner_and_due_date() -> None:
    req = ExportRequest(
        title="T",
        overview="O",
        action_items=[ActionItem(description="Ship it", owner="Alex", due_date="2026-02-01")],
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
    )
    text = _extracted_text(render_pdf(req))
    assert "Ship it" in text
    assert "Alex" in text
    assert "2026-02-01" in text


def test_render_pdf_quote_attributed_to_speaker() -> None:
    req = ExportRequest(
        title="T",
        overview="O",
        quotes=[Quote(speaker="Alex", text="Let's ship it.", segment_id=3)],
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
    )
    text = _extracted_text(render_pdf(req))
    assert "ship it" in text.lower()
    assert "Alex" in text
