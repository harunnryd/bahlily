from __future__ import annotations

import io
import xml.sax.saxutils
from typing import cast

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    Flowable,
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

from bahlily_export.models import ExportRequest

# Adobe's predefined CJK CID font, referenced (not embedded) per PDF's
# standard font-substitution mechanism, so it carries no bundled asset or
# separate font license. It also covers Latin ASCII, so it's used for every
# style rather than switching fonts per script.
_UNICODE_FONT = "STSong-Light"
pdfmetrics.registerFont(UnicodeCIDFont(_UNICODE_FONT))


def _esc(text: str) -> str:
    return xml.sax.saxutils.escape(text)


def render_pdf(req: ExportRequest) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    for style in styles.byName.values():
        style.fontName = _UNICODE_FONT
    story: list[Flowable] = []

    story.append(Paragraph(_esc(req.title), styles["Title"]))
    story.append(Paragraph(f"Generated on {req.created_at.strftime('%Y-%m-%d')}", styles["Normal"]))
    story.append(Spacer(1, 12))

    story.append(Paragraph("Overview", styles["Heading2"]))
    story.append(Paragraph(_esc(req.overview), styles["Normal"]))
    story.append(Spacer(1, 12))

    if req.key_points:
        story.append(Paragraph("Key Points", styles["Heading2"]))
        key_point_items = cast(
            list[Flowable],
            [ListItem(Paragraph(_esc(point), styles["Normal"])) for point in req.key_points],
        )
        story.append(ListFlowable(key_point_items, bulletType="bullet"))
        story.append(Spacer(1, 12))

    if req.action_items:
        story.append(Paragraph("Action Items", styles["Heading2"]))
        action_items = []
        for item in req.action_items:
            text = _esc(item.description)
            if item.owner:
                text += f" (Owner: {_esc(item.owner)})"
            if item.due_date:
                text += f" (Due: {_esc(item.due_date)})"
            action_items.append(ListItem(Paragraph(text, styles["Normal"])))
        action_items_cast = cast(list[Flowable], action_items)
        story.append(ListFlowable(action_items_cast, bulletType="bullet"))
        story.append(Spacer(1, 12))

    if req.quotes:
        story.append(Paragraph("Quotes", styles["Heading2"]))
        for quote in req.quotes:
            speaker = _esc(quote.speaker or "Unknown")
            story.append(Paragraph(f'"{_esc(quote.text)}" — {speaker}', styles["Normal"]))
        story.append(Spacer(1, 12))

    doc.build(story)
    return buffer.getvalue()
