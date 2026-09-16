"""Sélection de puzzles par tag, autour de la cote de l'apprenant, en évitant les déjà vus."""

from __future__ import annotations

import sqlite3

DEFAULT_SPREAD = 300


def user_rating(conn: sqlite3.Connection, username: str) -> int | None:
    row = conn.execute(
        """SELECT CASE WHEN user_color = 'white' THEN white_elo ELSE black_elo END AS elo
           FROM games WHERE username = ? AND rules = 'chess' ORDER BY end_time DESC LIMIT 1""",
        (username,),
    ).fetchone()
    return row["elo"] if row else None


def pick(
    conn: sqlite3.Connection,
    username: str,
    tag: str,
    *,
    n: int = 2,
    rating: int | None = None,
    spread: int = DEFAULT_SPREAD,
) -> list[sqlite3.Row]:
    """n puzzles du tag, cote proche de l'apprenant, jamais déjà tentés ; les plus populaires d'abord."""
    target = rating if rating is not None else (user_rating(conn, username) or 900)
    return conn.execute(
        """SELECT p.* FROM puzzles p
           WHERE (',' || p.tags || ',') LIKE ('%,' || ? || ',%')
             AND p.rating BETWEEN ? AND ?
             AND p.id NOT IN (SELECT puzzle_id FROM puzzle_attempts WHERE username = ?)
           ORDER BY abs(p.rating - ?) ASC, p.popularity DESC LIMIT ?""",
        (tag, target - spread, target + spread, username, target, n),
    ).fetchall()


def record_attempt(
    conn: sqlite3.Connection, username: str, puzzle_id: str, tag: str, *, solved: bool, first_try: bool
) -> int:
    cur = conn.execute(
        "INSERT INTO puzzle_attempts (username, puzzle_id, tag, solved, first_try) VALUES (?, ?, ?, ?, ?)",
        (username, puzzle_id, tag, int(solved), int(first_try and solved)),
    )
    conn.commit()
    return cur.lastrowid
