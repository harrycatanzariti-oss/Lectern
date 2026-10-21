"""Spaced repetition: a small SM-2 variant with four grades.

again = forgot it, hard = got it with effort, good = got it, easy = trivial.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

GRADES = ("again", "hard", "good", "easy")
MIN_EASE = 1.3
# A card counts as known once its next review is at least this far away.
MATURE_DAYS = 7


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def schedule(card: dict, grade: str, at: datetime | None = None) -> dict:
    """Return the card's new ease, interval_days, reps, lapses and due_at."""
    if grade not in GRADES:
        raise ValueError(f"grade must be one of {GRADES}")
    at = at or now()
    ease = card["ease"]
    interval = card["interval_days"]
    reps = card["reps"]
    lapses = card["lapses"]

    if grade == "again":
        lapses += 1 if reps else 0
        reps = 0
        ease = max(MIN_EASE, ease - 0.2)
        interval = 10 / (24 * 60)  # see it again in ten minutes
    else:
        if reps == 0:
            interval = {"hard": 0.5, "good": 1, "easy": 4}[grade]
        elif reps == 1:
            interval = {"hard": 2, "good": 3, "easy": 6}[grade]
        else:
            factor = {"hard": 1.2, "good": ease, "easy": ease * 1.3}[grade]
            interval = max(interval + 1, interval * factor)
        ease = max(MIN_EASE, ease + {"hard": -0.15, "good": 0, "easy": 0.15}[grade])
        reps += 1

    return {
        "ease": round(ease, 3),
        "interval_days": round(interval, 4),
        "reps": reps,
        "lapses": lapses,
        "due_at": iso(at + timedelta(days=interval)),
    }
