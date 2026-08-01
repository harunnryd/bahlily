from __future__ import annotations

import io
from typing import cast

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import (
    Flowable,
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

from bahlily_export.models import ExportRequest


def render_pdf(req: ExportRequest) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    story: list[Flowable] = []

    story.append(Paragraph(req.title, styles["Title"]))
    story.append(Paragraph(f"Generated on {req.created_at.strftime('%Y-%m-%d')}", styles["Normal"]))
    story.append(Spacer(1, 12))

    story.append(Paragraph("Overview", styles["Heading2"]))
    story.append(Paragraph(req.overview, styles["Normal"]))
    story.append(Spacer(1, 12))

    if req.key_points:
        story.append(Paragraph("Key Points", styles["Heading2"]))
        key_point_items = cast(
            list[Flowable],
            [ListItem(Paragraph(point, styles["Normal"])) for point in req.key_points],
        )
        story.append(ListFlowable(key_point_items, bulletType="bullet"))
        story.append(Spacer(1, 12))

    if req.action_items:
        story.append(Paragraph("Action Items", styles["Heading2"]))
        action_items = []
        for item in req.action_items:
            text = item.description
            if item.owner:
                text += f" (Owner: {item.owner})"
            if item.due_date:
                text += f" (Due: {item.due_date})"
            action_items.append(ListItem(Paragraph(text, styles["Normal"])))
        action_items_cast = cast(list[Flowable], action_items)
        story.append(ListFlowable(action_items_cast, bulletType="bullet"))
        story.append(Spacer(1, 12))

    if req.quotes:
        story.append(Paragraph("Quotes", styles["Heading2"]))
        for quote in req.quotes:
            speaker = quote.speaker or "Unknown"
            story.append(Paragraph(f'"{quote.text}" — {speaker}', styles["Normal"]))
        story.append(Spacer(1, 12))

    doc.build(story)
    return buffer.getvalue()
