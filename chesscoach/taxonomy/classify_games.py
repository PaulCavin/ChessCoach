"""Batch : évals + coups -> moments critiques classés (table ``critical_moments``).

Usage : ``python -m chesscoach.taxonomy.classify_games --username Kuga06 [--db ...] [--threshold 150]``
Recalcule tout à chaque exécution (dérivé pur, quelques secondes pour 600 parties).
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections.abc import Iterable

import chess

from chesscoach import db
from chesscoach.engine.analysis import CRITICAL_CP, CriticalMoment, critical_moments, move_losses
from chesscoach.engine.analyse import load_evals
from chesscoach.taxonomy.classify import OPENING_MAX_PLY, Classification, MomentContext, classify, is_endgame


def game_phase(board_before: chess.Board) -> str:
    if board_before.ply() < OPENING_MAX_PLY:
        return "opening"
    return "endgame" if is_endgame(board_before) else "middlegame"


def classify_game(
    conn: sqlite3.Connection, game_id: str, user_color: str, *, threshold: int = CRITICAL_CP
) -> list[tuple[CriticalMoment, Classification, str]]:
    """Retourne (moment, classification, phase) pour chaque moment critique de l'utilisateur."""
    evals = load_evals(conn, game_id)
    rows = conn.execute("SELECT san, clock_seconds FROM moves WHERE game_id = ? ORDER BY ply", (game_id,)).fetchall()
    if not evals or len(evals) != len(rows) + 1:
        return []
    losses = move_losses(evals, [r["san"] for r in rows])
    out = []
    for cm in critical_moments(losses, user_color, threshold=threshold):
        board = chess.Board(cm.move.fen)
        played = board.parse_san(cm.move.san)
        ctx = MomentContext(
            board_before=board,
            played=played,
            eval_before=evals[cm.move.ply - 1],
            eval_after=evals[cm.move.ply],
            clock_seconds=rows[cm.move.ply - 1]["clock_seconds"],
        )
        out.append((cm, classify(ctx), game_phase(board)))
    return out


def store_moments(
    conn: sqlite3.Connection,
    game_id: str,
    items: list[tuple[CriticalMoment, Classification, str]],
    clocks: dict[int, float | None],
) -> None:
    conn.execute("DELETE FROM critical_moments WHERE game_id = ?", (game_id,))
    conn.executemany(
        "INSERT INTO critical_moments (game_id, ply, rank, san, fen_before, best_move, before_cp, after_cp, loss,"
        " severity, phase, clock_seconds, primary_tag, tags) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                game_id,
                cm.move.ply,
                cm.rank,
                cm.move.san,
                cm.move.fen,
                cm.move.best_move,
                cm.move.before_cp,
                cm.move.after_cp,
                cm.move.loss,
                cm.move.severity,
                phase,
                clocks.get(cm.move.ply),
                cls.primary.value,
                ",".join(t.value for t in cls.tags),
            )
            for cm, cls, phase in items
        ],
    )


def classify_all(conn: sqlite3.Connection, username: str, *, threshold: int = CRITICAL_CP, log=lambda _: None) -> int:
    games = conn.execute(
        "SELECT g.id, g.user_color FROM games g JOIN analysed_games a ON a.game_id = g.id WHERE g.username = ?",
        (username,),
    ).fetchall()
    total = 0
    for g in games:
        items = classify_game(conn, g["id"], g["user_color"], threshold=threshold)
        clocks = {
            r["ply"]: r["clock_seconds"]
            for r in conn.execute("SELECT ply, clock_seconds FROM moves WHERE game_id = ?", (g["id"],))
        }
        store_moments(conn, g["id"], items, clocks)
        total += len(items)
    conn.commit()
    log(f"{len(games)} partie(s) classées, {total} moment(s) critique(s)")
    return total


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Classe les moments critiques des parties analysées.")
    parser.add_argument("--username", required=True)
    parser.add_argument("--db", default="data/chesscoach.sqlite")
    parser.add_argument("--threshold", type=int, default=CRITICAL_CP)
    args = parser.parse_args(list(argv) if argv is not None else None)
    classify_all(db.connect(args.db), args.username, threshold=args.threshold, log=print)
    return 0


if __name__ == "__main__":
    sys.exit(main())
