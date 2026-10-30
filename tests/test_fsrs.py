from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from chesscoach.memory.fsrs import (
    AGAIN,
    EASY,
    GOOD,
    HARD,
    Card,
    grade_from,
    interval_days,
    retrievability,
    review,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def test_grade_mapping_is_deterministic():
    assert grade_from("best", 90) == EASY
    assert grade_from("best", 40) == GOOD and grade_from("best", None) == GOOD
    assert grade_from("other", 50) == HARD
    assert grade_from("played", 99) == AGAIN
    with pytest.raises(ValueError):
        grade_from("inconnu", None)


def test_first_review_sets_initial_state():
    card = review(None, GOOD, T0)
    assert card.reps == 1 and card.lapses == 0 and card.state == "learning"
    assert card.stability > 0 and 1 <= card.difficulty <= 10
    assert card.due == T0 + timedelta(days=interval_days(card.stability))
    assert review(None, EASY, T0).stability > card.stability > review(None, AGAIN, T0).stability


def test_good_reviews_grow_stability_and_again_resets_it():
    c1 = review(None, GOOD, T0)
    c2 = review(c1, GOOD, c1.due)
    assert c2.stability > c1.stability and c2.state == "review" and c2.reps == 2
    c3 = review(c2, AGAIN, c2.due)
    assert c3.stability < c2.stability and c3.lapses == 1 and c3.state == "learning"
    assert c3.difficulty > c2.difficulty  # une erreur rend le tag plus difficile


def test_retrievability_decays_and_interval_is_bounded():
    assert retrievability(0, 10) == pytest.approx(1.0)
    assert 0 < retrievability(30, 10) < retrievability(5, 10) < 1
    assert interval_days(0.01) == 1
    assert interval_days(10_000) == 365


def test_review_rejects_invalid_grade():
    with pytest.raises(ValueError):
        review(Card(stability=1, difficulty=5, last_review=T0, due=T0), 7, T0)
