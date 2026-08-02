from __future__ import annotations

import math

_MATCH_THRESHOLD = 0.75


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise ValueError(f"embedding dimension mismatch: {len(a)} != {len(b)}")
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def best_match(embedding: list[float], profiles: list[tuple[str, list[float]]]) -> str | None:
    best_id: str | None = None
    best_score = _MATCH_THRESHOLD
    for profile_id, candidate in profiles:
        score = cosine_similarity(embedding, candidate)
        if score >= best_score:
            best_score = score
            best_id = profile_id
    return best_id
