from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated

from bahlily_logging.errors import BahlilyError
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from langchain_core.embeddings import Embeddings
from starlette.requests import Request

from bahlily_chat import chat, db, embeddings, index
from bahlily_chat.errors import (
    ChatMeetingNotIngestedError,
    ChatProviderAuthError,
    ChatProviderUnavailableError,
    ChatUnsupportedEmbeddingProviderError,
    ChatUnsupportedProviderError,
)
from bahlily_chat.models import ChatRequest, ChatResponse, IngestRequest, IngestResponse

app = FastAPI(title="bahlily-chat")

_DEFAULT_DB = str(Path.home() / ".bahlily" / "chat.db")

_ERROR_STATUS: dict[type[Exception], int] = {
    ChatMeetingNotIngestedError: 404,
    ChatUnsupportedEmbeddingProviderError: 500,
    ChatUnsupportedProviderError: 400,
    ChatProviderAuthError: 401,
    ChatProviderUnavailableError: 502,
}


@app.exception_handler(ChatMeetingNotIngestedError)
@app.exception_handler(ChatUnsupportedEmbeddingProviderError)
@app.exception_handler(ChatUnsupportedProviderError)
@app.exception_handler(ChatProviderAuthError)
@app.exception_handler(ChatProviderUnavailableError)
async def _error_handler(request: Request, exc: BahlilyError) -> JSONResponse:
    status_code = _ERROR_STATUS[type(exc)]
    return JSONResponse(status_code=status_code, content={"code": exc.code, "message": str(exc)})


def get_connection() -> Iterator[sqlite3.Connection]:
    db_path = os.environ.get("BAHLILY_CHAT_DB", _DEFAULT_DB)
    dimension = int(os.environ["BAHLILY_CHAT_EMBEDDING_DIMENSION"])
    conn = db.connect(db_path, dimension)
    try:
        yield conn
    finally:
        conn.close()


def get_embedder() -> Embeddings:
    provider = os.environ["BAHLILY_CHAT_EMBEDDING_PROVIDER"]
    model = os.environ["BAHLILY_CHAT_EMBEDDING_MODEL"]
    return embeddings.get_embedder(provider, model)


ConnectionDep = Annotated[sqlite3.Connection, Depends(get_connection)]
EmbedderDep = Annotated[Embeddings, Depends(get_embedder)]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/meetings/{meeting_id}/ingest", status_code=201)
def ingest_meeting(
    meeting_id: str,
    request: IngestRequest,
    conn: ConnectionDep,
    embedder: EmbedderDep,
) -> IngestResponse:
    texts = [s.text for s in request.segments]
    vectors = embedder.embed_documents(texts)
    rows = [
        (s.segment_id, s.text, s.speaker, s.start_time, s.end_time, vec)
        for s, vec in zip(request.segments, vectors, strict=True)
    ]
    index.upsert_meeting(conn, meeting_id, rows)
    return IngestResponse(meeting_id=meeting_id, segments_indexed=len(rows))


@app.delete("/meetings/{meeting_id}", status_code=204)
def delete_meeting(meeting_id: str, conn: ConnectionDep) -> None:
    index.delete_meeting(conn, meeting_id)


@app.post("/chat")
def post_chat(request: ChatRequest, conn: ConnectionDep, embedder: EmbedderDep) -> ChatResponse:
    if request.meeting_id is not None and not index.meeting_exists(conn, request.meeting_id):
        raise ChatMeetingNotIngestedError(request.meeting_id)
    return chat.answer(conn, embedder, request)
