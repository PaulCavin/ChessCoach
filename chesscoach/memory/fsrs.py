"""Planificateur FSRS appliqué aux tags de la taxonomie (D-013).

FSRS (Free Spaced Repetition Scheduler), paramètres par défaut de FSRS-5. Ici l'« item » n'est pas
une carte mais un **tag d'erreur** : chaque réponse à un moment critique ou chaque puzzle du tag est
une révision. Calcul pur, déterministe, sans réseau ni LLM : ``review()`` est une fonction.
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

# Paramètres par défaut FSRS-5 (w0..w18).
DEFAULT_W: tuple[float, ...] = (
    0.40255,
    1.18385,
    3.173,
    15.69105,
    7.1949,
    0.5345,
    1.4604,
    0.0046,
    1.54575,
    0.1192,
    1.01925,
    1.9395,
    0.11,
    0.29605,
    2.2698,
    0.2315,
    2.9898,
    0.51655,
    0.6621,
)
DECAY = -0.5
FACTOR = 0.9 ** (1 / DECAY) - 1  # ≈ 19/81
DESIRED_RETENTION = 0.9
MIN_INTERVAL_DAYS = 1
MAX_INTERVAL_DAYS = 365

AGAIN, HARD, GOOD, EASY = 1, 2, 3, 4


@dataclass(frozen=True)
class Card:
    """État d'un tag. ``last_review``/``due`` en UTC ; ``state`` : learning | review | retired."""

    stability: float
    difficulty: float
    reps: int = 0
    lapses: int = 0
    last_review: datetime | None = None
    due: datetime | None = None
    state: str = "learning"


def grade_from(verdict: str, confidence: int | None) -> int:
    """Traduction déterministe d'un verdict d'oracle en note FSRS (D-013).

    best + confiance ≥ 80 -> Easy ; best -> Good ; other (coup légal non évalué) -> Hard ;
    played (l'erreur de la partie rejouée) -> Again.
    """
    if verdict == "best":
        return EASY if (confidence is not None and confidence >= 80) else GOOD
    if verdict == "other":
        return HARD
    if verdict == "played":
        return AGAIN
    raise ValueError(f"verdict inconnu : {verdict}")


def retrievability(elapsed_days: float, stability: float) -> float:
    return (1 + FACTOR * max(0.0, elapsed_days) / max(stability, 1e-6)) ** DECAY


def _clamp_d(d: float) -> float:
    return min(10.0, max(1.0, d))


def _initial(grade: int, w: tuple[float, ...]) -> tuple[float, float]:
    stability = max(w[grade - 1], 0.1)
    difficulty = _clamp_d(w[4] - math.exp(w[5] * (grade - 1)) + 1)
    return stability, difficulty


def _next_difficulty(d: float, grade: int, w: tuple[float, ...]) -> float:
    delta = d - w[6] * (grade - 3)
    target = _clamp_d(w[4] - math.exp(w[5] * (EASY - 1)) + 1)  # D0(Easy), cible de réversion
    return _clamp_d(w[7] * target + (1 - w[7]) * delta)


def _stability_recall(s: float, d: float, r: float, grade: int, w: tuple[float, ...]) -> float:
    hard = w[15] if grade == HARD else 1.0
    easy = w[16] if grade == EASY else 1.0
    growth = 1 + math.exp(w[8]) * (11 - d) * (s ** -w[9]) * (math.exp(w[10] * (1 - r)) - 1) * hard * easy
    return max(0.1, s * growth)


def _stability_forget(s: float, d: float, r: float, w: tuple[float, ...]) -> float:
    return max(0.1, min(s, w[11] * (d ** -w[12]) * (((s + 1) ** w[13]) - 1) * math.exp(w[14] * (1 - r))))


def interval_days(stability: float, retention: float = DESIRED_RETENTION) -> int:
    raw = stability / FACTOR * (retention ** (1 / DECAY) - 1)
    return int(min(MAX_INTERVAL_DAYS, max(MIN_INTERVAL_DAYS, round(raw))))


def review(card: Card | None, grade: int, now: datetime, w: tuple[float, ...] = DEFAULT_W) -> Card:
    """Applique une révision. ``card`` None = première rencontre du tag."""
    if grade not in (AGAIN, HARD, GOOD, EASY):
        raise ValueError(f"note FSRS invalide : {grade}")
    if card is None or card.last_review is None:
        stability, difficulty = _initial(grade, w)
        lapses = 1 if grade == AGAIN else 0
        reps = 1
    else:
        elapsed = (now - card.last_review).total_seconds() / 86400
        r = retrievability(elapsed, card.stability)
        difficulty = _next_difficulty(card.difficulty, grade, w)
        if grade == AGAIN:
            stability = _stability_forget(card.stability, difficulty, r, w)
            lapses = card.lapses + 1
        else:
            stability = _stability_recall(card.stability, difficulty, r, grade, w)
            lapses = card.lapses
        reps = card.reps + 1
    due = now + timedelta(days=interval_days(stability))
    state = "learning" if (grade == AGAIN or reps < 2) else "review"
    return Card(
        stability=stability, difficulty=difficulty, reps=reps, lapses=lapses, last_review=now, due=due, state=state
    )


def retire(card: Card) -> Card:
    return replace(card, state="retired")


# --- persistance -------------------------------------------------------------


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def load_card(conn: sqlite3.Connection, username: str, tag: str) -> Card | None:
    row = conn.execute("SELECT * FROM tag_schedule WHERE username = ? AND tag = ?", (username, tag)).fetchone()
    if row is None:
        return None
    return Card(
        stability=row["stability"],
        difficulty=row["difficulty"],
        reps=row["reps"],
        lapses=row["lapses"],
        last_review=_parse(row["last_review"]),
        due=_parse(row["due"]),
        state=row["state"],
    )


def save_card(conn: sqlite3.Connection, username: str, tag: str, card: Card) -> None:
    assert card.last_review and card.due
    conn.execute(
        "INSERT OR REPLACE INTO tag_schedule (username, tag, stability, difficulty, reps, lapses, last_review, due,"
        " state) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            username,
            tag,
            card.stability,
            card.difficulty,
            card.reps,
            card.lapses,
            _iso(card.last_review),
            _iso(card.due),
            card.state,
        ),
    )
    conn.commit()


def due_tags(conn: sqlite3.Connection, username: str, now: datetime | None = None) -> list[tuple[str, Card]]:
    """Tags à réviser (échéance passée), le plus en retard d'abord. Les tags retirés sont exclus."""
    now = now or datetime.now(tz=UTC)
    out = []
    for row in conn.execute("SELECT tag FROM tag_schedule WHERE username = ? AND state != 'retired'", (username,)):
        card = load_card(conn, username, row["tag"])
        if card and card.due and card.due <= now:
            out.append((row["tag"], card))
    out.sort(key=lambda kv: kv[1].due or now)
    return out
