from __future__ import annotations

import sqlite3

from langchain_core.embeddings import Embeddings

from bahlily_chat import index
from bahlily_chat.errors import classify_provider_exception
from bahlily_chat.models import IngestRequest, IngestResponse


def ingest(
    conn: sqlite3.Connection,
    embedder: Embeddings,
    meeting_id: str,
    request: IngestRequest,
) -> IngestResponse:
    texts = [s.text for s in request.segments]
    try:
        vectors = embedder.embed_documents(texts)
        rows = [
            (s.segment_id, s.text, s.speaker, s.start_time, s.end_time, vec)
            for s, vec in zip(request.segments, vectors, strict=True)
        ]
        index.upsert_meeting(conn, meeting_id, rows)
    except Exception as exc:
        raise classify_provider_exception(exc) from exc

    return IngestResponse(meeting_id=meeting_id, segments_indexed=len(rows))
