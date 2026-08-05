from __future__ import annotations

import os

from bahlily_storage.errors import StorageEmbeddingDimNotConfiguredError


def embedding_dim() -> int:
    raw = os.environ.get("BAHLILY_STORAGE_EMBEDDING_DIM")
    if raw is None:
        raise StorageEmbeddingDimNotConfiguredError()
    return int(raw)
