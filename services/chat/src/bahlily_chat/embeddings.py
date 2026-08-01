from __future__ import annotations

from langchain_core.embeddings import Embeddings
from langchain_ollama import OllamaEmbeddings
from langchain_openai import OpenAIEmbeddings

from bahlily_chat.errors import ChatUnsupportedEmbeddingProviderError

_PROVIDERS: dict[str, type[Embeddings]] = {
    "openai": OpenAIEmbeddings,
    "ollama": OllamaEmbeddings,
}


def get_embedder(provider: str, model: str) -> Embeddings:
    try:
        embedding_cls = _PROVIDERS[provider]
    except KeyError as exc:
        raise ChatUnsupportedEmbeddingProviderError(
            f"unsupported embedding provider: {provider}"
        ) from exc
    return embedding_cls(model=model)  # type: ignore[call-arg]
