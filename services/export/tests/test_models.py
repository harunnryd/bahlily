from __future__ import annotations

import datetime

import pytest
from pydantic import ValidationError

from bahlily_export.models import ActionItem, ExportRequest, Quote


def test_export_request_minimal() -> None:
    req = ExportRequest(
        title="Standup",
        overview="Quick sync.",
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
    )
    assert req.title == "Standup"
    assert req.key_points == []
    assert req.action_items == []
    assert req.quotes == []


def test_export_request_rejects_empty_title() -> None:
    with pytest.raises(ValidationError):
        ExportRequest(
            title="",
            overview="Quick sync.",
            created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        )


def test_export_request_rejects_empty_overview() -> None:
    with pytest.raises(ValidationError):
        ExportRequest(
            title="Standup",
            overview="",
            created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        )


def test_export_request_with_full_content() -> None:
    req = ExportRequest(
        title="Standup",
        overview="Quick sync.",
        key_points=["Point A", "Point B"],
        action_items=[ActionItem(description="Ship it", owner="Alex", due_date="2026-02-01")],
        quotes=[Quote(speaker="Alex", text="Let's ship it.", segment_id=3)],
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
    )
    assert req.key_points == ["Point A", "Point B"]
    assert req.action_items[0].owner == "Alex"
    assert req.quotes[0].segment_id == 3


def test_action_item_defaults() -> None:
    item = ActionItem(description="Ship it")
    assert item.owner is None
    assert item.due_date is None
