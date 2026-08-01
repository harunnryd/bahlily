from __future__ import annotations

import dataclasses
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
    classify_provider_exception,
)
from bahlily_chat.models import ChatRequest, ChatResponse, IngestRequest, IngestResponse

app = FastAPI(title="bahlily-chat")

DEFAULT_DB = str(Path.home() / ".bahlily" / "chat.db")


@dataclasses.dataclass(frozen=True)
class ChatConfig:
    db_path: str
    dimension: int


_config: ChatConfig | None = None
_embedder: Embeddings | None = None


def configure(
    *, db_path: str, dimension: int, embedding_provider: str, embedding_model: str
) -> None:
    """Set the process-wide config/embedder once, at startup.

    Doing the (potentially failing) env var reads and embedder construction
    here rather than lazily inside the request-scoped dependencies below
    means a misconfigured deployment fails loudly at boot instead of 500ing
    with a raw KeyError/ValueError on the first real request.
    """
    global _config, _embedder
    _config = ChatConfig(db_path=db_path, dimension=dimension)
    _embedder = embeddings.get_embedder(embedding_provider, embedding_model)


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
    if _config is None:
        raise RuntimeError("bahlily_chat.app.configure() must be called before serving requests")
    conn = db.connect(_config.db_path, _config.dimension)
    try:
        yield conn
    finally:
        conn.close()


def get_embedder() -> Embeddings:
    if _embedder is None:
        raise RuntimeError("bahlily_chat.app.configure() must be called before serving requests")
    return _embedder


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
    try:
        vectors = embedder.embed_documents(texts)
    except Exception as exc:
        raise classify_provider_exception(exc) from exc
    try:
        rows = [
            (s.segment_id, s.text, s.speaker, s.start_time, s.end_time, vec)
            for s, vec in zip(request.segments, vectors, strict=True)
        ]
    except ValueError as exc:
        raise classify_provider_exception(exc) from exc
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
