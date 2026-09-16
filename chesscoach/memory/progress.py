"""Rejoue l'historique dans FSRS et décide la sortie d'un tag (D-013). Calcul pur, sans LLM.

Sortie d'un tag (règle du brief) : le taux de réussite monte **ET** le motif recule dans les parties
réelles. Les deux conditions sont mesurées, jamais estimées.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from chesscoach.memory.fsrs import Card, grade_from, load_card, retire, review, save_card
from chesscoach.taxonomy.tags import Tag

MIN_REVIEWS_TO_RETIRE = 5
SUCCESS_RATE_TO_RETIRE = 0.8
RECENT_GAMES = 20  # fenêtre « parties récentes » pour mesurer le recul du motif


@dataclass(frozen=True)
class TagProgress:
    tag: str
    reviews: int
    success_rate: float | None  # part de verdicts « meilleur coup » (réponses + exercices + puzzles)
    recent_per_game: float | None  # occurrences par partie sur les RECENT_GAMES dernières parties analysées
    baseline_per_game: float | None  # idem sur les parties analysées précédentes
    declining: bool
    can_retire: bool


def _reviews(conn: sqlite3.Connection, username: str) -> list[tuple[str, str, int, int | None]]:
    """(ts, tag, grade, ...) fusionnant moments critiques et puzzles, par ordre chronologique."""
    rows = [
        (r["ts"], r["primary_tag"], grade_from(r["verdict"], r["confidence"]), r["confidence"])
        for r in conn.execute(
            "SELECT ts, primary_tag, verdict, confidence FROM learner_events WHERE username = ?", (username,)
        )
    ]
    rows += [
        (r["ts"], r["tag"], 3 if r["first_try"] else (2 if r["solved"] else 1), None)
        for r in conn.execute("SELECT ts, tag, solved, first_try FROM puzzle_attempts WHERE username = ?", (username,))
    ]
    rows.sort(key=lambda t: t[0])
    return rows


def rebuild_schedule(conn: sqlite3.Connection, username: str) -> dict[str, Card]:
    """Recalcule tout `tag_schedule` depuis l'historique. Idempotent : même entrée, même sortie."""
    conn.execute("DELETE FROM tag_schedule WHERE username = ?", (username,))
    cards: dict[str, Card] = {}
    for ts, tag, grade, _conf in _reviews(conn, username):
        now = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        cards[tag] = review(cards.get(tag), grade, now)
    for tag, card in cards.items():
        save_card(conn, username, tag, card)
    conn.commit()
    return cards


def tag_progress(conn: sqlite3.Connection, username: str, tag: str) -> TagProgress:
    ev = conn.execute(
        "SELECT verdict FROM learner_events WHERE username = ? AND primary_tag = ?", (username, tag)
    ).fetchall()
    pz = conn.execute(
        "SELECT first_try FROM puzzle_attempts WHERE username = ? AND tag = ?", (username, tag)
    ).fetchall()
    total = len(ev) + len(pz)
    ok = sum(1 for r in ev if r["verdict"] == "best") + sum(1 for r in pz if r["first_try"])
    rate = ok / total if total else None

    games = conn.execute(
        """SELECT g.id FROM games g JOIN analysed_games a ON a.game_id = g.id
           WHERE g.username = ? ORDER BY g.end_time DESC""",
        (username,),
    ).fetchall()
    ids = [r["id"] for r in games]
    recent, older = ids[:RECENT_GAMES], ids[RECENT_GAMES:]

    def per_game(subset: list[int]) -> float | None:
        if not subset:
            return None
        marks = ",".join("?" * len(subset))
        n = conn.execute(
            f"SELECT count(*) FROM critical_moments WHERE primary_tag = ? AND game_id IN ({marks})", (tag, *subset)
        ).fetchone()[0]
        return n / len(subset)

    recent_rate, baseline = per_game(recent), per_game(older)
    declining = bool(recent_rate is not None and baseline is not None and recent_rate < baseline)
    can_retire = bool(
        total >= MIN_REVIEWS_TO_RETIRE and rate is not None and rate >= SUCCESS_RATE_TO_RETIRE and declining
    )
    return TagProgress(tag, total, rate, recent_rate, baseline, declining, can_retire)


def apply_retirements(conn: sqlite3.Connection, username: str) -> list[str]:
    """Retire les tags remplissant les deux conditions. Retourne les tags retirés."""
    retired = []
    for tag in Tag:
        card = load_card(conn, username, tag.value)
        if card is None or card.state == "retired":
            continue
        if tag_progress(conn, username, tag.value).can_retire:
            save_card(conn, username, tag.value, retire(card))
            retired.append(tag.value)
    return retired
