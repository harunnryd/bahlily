from __future__ import annotations

import datetime

from bahlily_export.markdown_renderer import render_markdown
from bahlily_export.models import ActionItem, ExportRequest, Quote


def _minimal_request() -> ExportRequest:
    return ExportRequest(
        title="Team Standup",
        overview="Discussed sprint progress.",
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
    )


def test_render_markdown_includes_title_and_overview() -> None:
    output = render_markdown(_minimal_request()).decode("utf-8")
    assert "# Team Standup" in output
    assert "Discussed sprint progress." in output


def test_render_markdown_includes_generated_date() -> None:
    output = render_markdown(_minimal_request()).decode("utf-8")
    assert "2026-01-01" in output


def test_render_markdown_omits_empty_sections() -> None:
    output = render_markdown(_minimal_request()).decode("utf-8")
    assert "## Key Points" not in output
    assert "## Action Items" not in output
    assert "## Quotes" not in output


def test_render_markdown_key_points_as_bullets() -> None:
    req = ExportRequest(
        title="T",
        overview="O",
        key_points=["First point", "Second point"],
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
    )
    output = render_markdown(req).decode("utf-8")
    assert "## Key Points" in output
    assert "- First point" in output
    assert "- Second point" in output


def test_render_markdown_action_item_with_owner_and_due_date() -> None:
    req = ExportRequest(
        title="T",
        overview="O",
        action_items=[ActionItem(description="Ship it", owner="Alex", due_date="2026-02-01")],
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
    )
    output = render_markdown(req).decode("utf-8")
    assert "## Action Items" in output
    assert "Ship it" in output
    assert "Alex" in output
    assert "2026-02-01" in output


def test_render_markdown_quote_attributed_to_speaker() -> None:
    req = ExportRequest(
        title="T",
        overview="O",
        quotes=[Quote(speaker="Alex", text="Let's ship it.", segment_id=3)],
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
    )
    output = render_markdown(req).decode("utf-8")
    assert "## Quotes" in output
    assert "Let's ship it." in output
    assert "Alex" in output


def test_render_markdown_quote_unknown_speaker() -> None:
    req = ExportRequest(
        title="T",
        overview="O",
        quotes=[Quote(text="Anonymous point.", segment_id=1)],
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
    )
    output = render_markdown(req).decode("utf-8")
    assert "Unknown" in output
