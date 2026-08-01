from __future__ import annotations

from bahlily_export.models import ExportRequest


def render_markdown(req: ExportRequest) -> bytes:
    lines: list[str] = [f"# {req.title}", ""]
    lines.append(f"_Generated on {req.created_at.strftime('%Y-%m-%d')}_")
    lines.append("")
    lines.append("## Overview")
    lines.append("")
    lines.append(req.overview)
    lines.append("")

    if req.key_points:
        lines.append("## Key Points")
        lines.append("")
        for point in req.key_points:
            lines.append(f"- {point}")
        lines.append("")

    if req.action_items:
        lines.append("## Action Items")
        lines.append("")
        for item in req.action_items:
            parts = [item.description]
            if item.owner:
                parts.append(f"(Owner: {item.owner})")
            if item.due_date:
                parts.append(f"(Due: {item.due_date})")
            lines.append(f"- {' '.join(parts)}")
        lines.append("")

    if req.quotes:
        lines.append("## Quotes")
        lines.append("")
        for quote in req.quotes:
            speaker = quote.speaker or "Unknown"
            lines.append(f"> {quote.text}")
            lines.append(f"> — {speaker}")
            lines.append("")

    return "\n".join(lines).encode("utf-8")
