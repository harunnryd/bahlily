from __future__ import annotations

import pytest
from langchain_ollama import OllamaEmbeddings
from langchain_openai import OpenAIEmbeddings

from bahlily_chat.embeddings import get_embedder
from bahlily_chat.errors import ChatUnsupportedEmbeddingProviderError


def test_get_embedder_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    embedder = get_embedder("openai", "text-embedding-3-small")
    assert isinstance(embedder, OpenAIEmbeddings)
    assert embedder.model == "text-embedding-3-small"


def test_get_embedder_ollama() -> None:
    embedder = get_embedder("ollama", "nomic-embed-text")
    assert isinstance(embedder, OllamaEmbeddings)
    assert embedder.model == "nomic-embed-text"


def test_get_embedder_unsupported_provider_raises() -> None:
    with pytest.raises(ChatUnsupportedEmbeddingProviderError):
        get_embedder("anthropic", "some-model")
