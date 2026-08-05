from __future__ import annotations

import pytest

from bahlily_storage.config import embedding_dim
from bahlily_storage.errors import (
    StorageEmbeddingDimInvalidError,
    StorageEmbeddingDimNotConfiguredError,
)


def test_embedding_dim_raises_when_env_var_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BAHLILY_STORAGE_EMBEDDING_DIM", raising=False)
    with pytest.raises(StorageEmbeddingDimNotConfiguredError):
        embedding_dim()


def test_embedding_dim_returns_int_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BAHLILY_STORAGE_EMBEDDING_DIM", "512")
    assert embedding_dim() == 512


def test_embedding_dim_raises_when_env_var_is_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BAHLILY_STORAGE_EMBEDDING_DIM", "0")
    with pytest.raises(StorageEmbeddingDimInvalidError):
        embedding_dim()


def test_embedding_dim_raises_when_env_var_is_negative(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BAHLILY_STORAGE_EMBEDDING_DIM", "-3")
    with pytest.raises(StorageEmbeddingDimInvalidError):
        embedding_dim()


def test_embedding_dim_raises_when_env_var_is_non_numeric(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BAHLILY_STORAGE_EMBEDDING_DIM", "abc")
    with pytest.raises(StorageEmbeddingDimInvalidError):
        embedding_dim()
