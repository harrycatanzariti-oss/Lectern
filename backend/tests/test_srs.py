from datetime import datetime, timezone

import pytest

from lectern import srs

AT = datetime(2026, 1, 1, tzinfo=timezone.utc)
NEW = {"ease": 2.5, "interval_days": 0, "reps": 0, "lapses": 0}


def test_first_good_is_one_day():
    s = srs.schedule(NEW, "good", AT)
    assert s["interval_days"] == 1 and s["reps"] == 1 and s["due_at"] == "2026-01-02T00:00:00Z"


def test_intervals_grow_with_good_answers():
    card, intervals = dict(NEW), []
    for _ in range(5):
        card = {**card, **srs.schedule(card, "good", AT)}
        intervals.append(card["interval_days"])
    assert intervals == sorted(intervals) and intervals[-1] > 30


def test_again_resets_and_counts_a_lapse():
    card = {**NEW, **srs.schedule(NEW, "good", AT)}
    card = {**card, **srs.schedule(card, "again", AT)}
    assert card["reps"] == 0 and card["lapses"] == 1 and card["interval_days"] < 0.01
    assert card["ease"] == pytest.approx(2.3)


def test_ease_has_a_floor():
    card = dict(NEW)
    for _ in range(20):
        card = {**card, **srs.schedule(card, "again", AT)}
    assert card["ease"] == srs.MIN_EASE


def test_bad_grade():
    with pytest.raises(ValueError):
        srs.schedule(NEW, "meh", AT)
