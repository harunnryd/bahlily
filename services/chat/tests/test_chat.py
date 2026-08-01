from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.embeddings import Embeddings

from bahlily_chat import db, index
from bahlily_chat.chat import answer
from bahlily_chat.errors import ChatProviderUnavailableError, ChatUnsupportedProviderError
from bahlily_chat.models import ChatRequest, ChatTurn


class FakeEmbeddings(Embeddings):
    """Deterministic fake: each known text maps to a fixed 4-dim vector."""

    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self._vectors = vectors

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vectors[t] for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vectors[text]


@pytest.fixture
def conn(tmp_path: Path) -> object:
    c = db.connect(str(tmp_path / "test.db"), dimension=4)
    index.upsert_meeting(
        c,
        "m1",
        [
            (1, "We decided to ship on Friday.", "Alice", 0.0, 2.0, [0.1, 0.1, 0.1, 0.1]),
            (2, "Unrelated chatter about lunch.", "Bob", 2.0, 4.0, [0.9, 0.9, 0.9, 0.9]),
        ],
    )
    return c


def _fake_llm_response(content: str) -> MagicMock:
    response = MagicMock()
    response.content = content
    return response


def test_answer_includes_retrieved_citations(conn: object) -> None:
    embedder = FakeEmbeddings({"When do we ship?": [0.11, 0.11, 0.11, 0.11]})
    request = ChatRequest(
        question="When do we ship?", meeting_id="m1", provider="openai", model="gpt-4o-mini"
    )

    with patch("bahlily_chat.chat.init_chat_model") as mock_init:
        mock_init.return_value.invoke.return_value = _fake_llm_response(
            "You decided to ship on Friday."
        )
        result = answer(conn, embedder, request)

    assert result.answer == "You decided to ship on Friday."
    assert result.citations[0].segment_id == 1
    assert result.citations[0].text == "We decided to ship on Friday."
    mock_init.assert_called_once_with("openai:gpt-4o-mini", timeout=30, max_retries=2)


def test_answer_passes_history_and_question_to_llm(conn: object) -> None:
    embedder = FakeEmbeddings({"Follow-up question": [0.11, 0.11, 0.11, 0.11]})
    request = ChatRequest(
        question="Follow-up question",
        meeting_id="m1",
        provider="openai",
        model="gpt-4o-mini",
        history=[
            ChatTurn(role="user", content="Earlier question"),
            ChatTurn(role="assistant", content="Earlier answer"),
        ],
    )

    with patch("bahlily_chat.chat.init_chat_model") as mock_init:
        mock_model = mock_init.return_value
        mock_model.invoke.return_value = _fake_llm_response("Some answer")
        answer(conn, embedder, request)

    messages = mock_model.invoke.call_args[0][0]
    contents = [m.content for m in messages]
    assert "Earlier question" in contents
    assert "Earlier answer" in contents
    assert "Follow-up question" in contents


def test_answer_unsupported_provider_raises(conn: object) -> None:
    embedder = FakeEmbeddings({"question": [0.1, 0.1, 0.1, 0.1]})
    request = ChatRequest(question="question", provider="not-a-real-provider", model="x")

    with patch("bahlily_chat.chat.init_chat_model", side_effect=ValueError("bad provider")):
        with pytest.raises(ChatUnsupportedProviderError):
            answer(conn, embedder, request)


def test_answer_provider_call_failure_is_classified(conn: object) -> None:
    embedder = FakeEmbeddings({"question": [0.1, 0.1, 0.1, 0.1]})
    request = ChatRequest(question="question", provider="openai", model="gpt-4o-mini")

    with patch("bahlily_chat.chat.init_chat_model") as mock_init:
        mock_init.return_value.invoke.side_effect = RuntimeError("timed out")
        with pytest.raises(ChatProviderUnavailableError):
            answer(conn, embedder, request)


def test_answer_global_query_with_no_matches_still_answers(tmp_path: Path) -> None:
    empty_conn = db.connect(str(tmp_path / "empty.db"), dimension=4)
    embedder = FakeEmbeddings({"anything": [0.1, 0.1, 0.1, 0.1]})
    request = ChatRequest(question="anything", provider="openai", model="gpt-4o-mini")

    with patch("bahlily_chat.chat.init_chat_model") as mock_init:
        mock_init.return_value.invoke.return_value = _fake_llm_response(
            "I don't have any meetings yet."
        )
        result = answer(empty_conn, embedder, request)

    assert result.answer == "I don't have any meetings yet."
    assert result.citations == []
