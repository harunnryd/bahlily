from __future__ import annotations

import pytest

from bahlily_storage.speaker_matching import best_match, cosine_similarity


def test_cosine_similarity_of_identical_vectors_is_one() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)


def test_cosine_similarity_of_orthogonal_vectors_is_zero() -> None:
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_similarity_of_opposite_vectors_is_negative_one() -> None:
    assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)


def test_cosine_similarity_rejects_mismatched_dimensions() -> None:
    with pytest.raises(ValueError, match="dimension mismatch"):
        cosine_similarity([1.0, 0.0], [1.0])


def test_cosine_similarity_of_a_zero_vector_is_zero_not_a_division_error() -> None:
    assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_best_match_returns_the_closest_profile_above_threshold() -> None:
    target = [1.0, 0.0]
    profiles = [("far", [0.0, 1.0]), ("close", [0.99, 0.01]), ("closer", [1.0, 0.0])]
    assert best_match(target, profiles) == "closer"


def test_best_match_returns_none_when_nothing_clears_the_threshold() -> None:
    target = [1.0, 0.0]
    profiles = [("far", [0.0, 1.0]), ("orthogonal-ish", [0.1, 0.9])]
    assert best_match(target, profiles) is None


def test_best_match_returns_none_for_an_empty_profile_list() -> None:
    assert best_match([1.0, 0.0], []) is None
