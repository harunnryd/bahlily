from __future__ import annotations

import dataclasses
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated

from bahlily_capability import require_capability
from bahlily_logging.errors import BahlilyError
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from langchain_core.embeddings import Embeddings
from starlette.requests import Request

from bahlily_chat import chat, db, embeddings, index, ingest
from bahlily_chat.errors import (
    ChatMeetingNotIngestedError,
    ChatProviderAuthError,
    ChatProviderUnavailableError,
    ChatStorageError,
    ChatUnsupportedEmbeddingProviderError,
    ChatUnsupportedProviderError,
)
from bahlily_chat.models import ChatRequest, ChatResponse, IngestRequest, IngestResponse

app = FastAPI(title="bahlily-chat", dependencies=[Depends(require_capability)])

app.add_middleware(
    CORSMiddleware,
    allow_origins=["tauri://localhost", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DEFAULT_DB = str(Path.home() / ".bahlily" / "chat.db")


@dataclasses.dataclass(frozen=True)
class ChatConfig:
    db_path: str
    dimension: int


_config: ChatConfig | None = None
_embedder: Embeddings | None = None


def configure_at_startup(
    *, db_path: str, dimension: int, embedding_provider: str, embedding_model: str
) -> None:
    global _config, _embedder
    _config = ChatConfig(db_path=db_path, dimension=dimension)
    _embedder = embeddings.get_embedder(embedding_provider, embedding_model)


_ERROR_STATUS: dict[type[Exception], int] = {
    ChatMeetingNotIngestedError: 404,
    ChatUnsupportedEmbeddingProviderError: 500,
    ChatUnsupportedProviderError: 400,
    ChatProviderAuthError: 401,
    ChatProviderUnavailableError: 502,
    ChatStorageError: 500,
}


@app.exception_handler(ChatMeetingNotIngestedError)
@app.exception_handler(ChatUnsupportedEmbeddingProviderError)
@app.exception_handler(ChatUnsupportedProviderError)
@app.exception_handler(ChatProviderAuthError)
@app.exception_handler(ChatProviderUnavailableError)
@app.exception_handler(ChatStorageError)
async def _error_handler(request: Request, exc: BahlilyError) -> JSONResponse:
    status_code = _ERROR_STATUS[type(exc)]
    return JSONResponse(status_code=status_code, content={"code": exc.code, "message": str(exc)})


def get_connection() -> Iterator[sqlite3.Connection]:
    if _config is None:
        raise RuntimeError(
            "bahlily_chat.app.configure_at_startup() must be called before serving requests"
        )
    try:
        conn = db.connect(_config.db_path, _config.dimension)
    except sqlite3.OperationalError as exc:
        raise ChatStorageError("failed to open the chat index") from exc
    try:
        yield conn
    finally:
        conn.close()


def get_embedder() -> Embeddings:
    if _embedder is None:
        raise RuntimeError(
            "bahlily_chat.app.configure_at_startup() must be called before serving requests"
        )
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
    return ingest.ingest(conn, embedder, meeting_id, request)


@app.delete("/meetings/{meeting_id}", status_code=204)
def delete_meeting(meeting_id: str, conn: ConnectionDep) -> None:
    try:
        index.delete_meeting(conn, meeting_id)
    except sqlite3.OperationalError as exc:
        raise ChatStorageError(f"failed to delete meeting {meeting_id!r}") from exc


@app.post("/chat")
def post_chat(request: ChatRequest, conn: ConnectionDep, embedder: EmbedderDep) -> ChatResponse:
    if request.meeting_id is not None:
        try:
            exists = index.meeting_exists(conn, request.meeting_id)
        except sqlite3.OperationalError as exc:
            raise ChatStorageError(f"failed to look up meeting {request.meeting_id!r}") from exc
        if not exists:
            raise ChatMeetingNotIngestedError(request.meeting_id)
    return chat.answer(conn, embedder, request)
