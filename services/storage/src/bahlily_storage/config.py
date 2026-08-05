from __future__ import annotations

import os

from bahlily_storage.errors import (
    StorageEmbeddingDimInvalidError,
    StorageEmbeddingDimNotConfiguredError,
)


def embedding_dim() -> int:
    raw = os.environ.get("BAHLILY_STORAGE_EMBEDDING_DIM")
    if raw is None:
        raise StorageEmbeddingDimNotConfiguredError()
    try:
        value = int(raw)
    except ValueError as exc:
        raise StorageEmbeddingDimInvalidError(raw) from exc
    if value <= 0:
        raise StorageEmbeddingDimInvalidError(raw)
    return value
