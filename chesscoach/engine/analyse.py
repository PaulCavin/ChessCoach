"""Analyse des parties en base : une éval Stockfish par position -> table ``evals``.

Usage : ``python -m chesscoach.engine.analyse --username Kuga06 [--time-class rapid --time-control 600]
         [--depth 14] [--workers 4] [--limit 50] [--db data/chesscoach.sqlite]``
"""

from __future__ import annotations

import argparse
import io
import multiprocessing
import sqlite3
import sys
import time
from collections.abc import Iterable

import chess
import chess.pgn

from chesscoach import db
from chesscoach.engine.analysis import PositionEval
from chesscoach.engine.stockfish import Stockfish

DEFAULT_DEPTH = 14


def analyse_pgn(pgn: str, engine: Stockfish, depth: int) -> list[PositionEval]:
    """Une éval par position, de la position initiale à la position finale incluse."""
    game = chess.pgn.read_game(io.StringIO(pgn))
    if game is None:
        raise ValueError("PGN illisible")
    board = game.board()
    evals = [engine.evaluate(board, depth)]
    for move in game.mainline_moves():
        board.push(move)
        evals.append(engine.evaluate(board, depth))
    return evals


def select_games(
    conn: sqlite3.Connection,
    username: str,
    *,
    time_class: str | None = None,
    time_control: str | None = None,
    limit: int | None = None,
) -> list[tuple[int, str]]:
    """(id, pgn) des parties standard non encore analysées, les plus récentes d'abord."""
    sql = """
        SELECT g.id, g.pgn FROM games g
        LEFT JOIN analysed_games a ON a.game_id = g.id
        WHERE g.username = ? AND g.rules = 'chess' AND a.game_id IS NULL
    """
    params: list[object] = [username]
    if time_class:
        sql += " AND g.time_class = ?"
        params.append(time_class)
    if time_control:
        sql += " AND g.time_control = ?"
        params.append(time_control)
    sql += " ORDER BY g.end_time DESC"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    return [(r["id"], r["pgn"]) for r in conn.execute(sql, params)]


def store_evals(
    conn: sqlite3.Connection, game_id: int, evals: list[PositionEval], engine_name: str, depth: int
) -> None:
    conn.executemany(
        "INSERT OR REPLACE INTO evals (game_id, ply, fen, score_cp, mate_in, best_move, best_pv, depth)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (game_id, i + 1, e.fen, e.score_cp, _stored_mate(e), e.best_move, e.best_pv, e.depth)
            for i, e in enumerate(evals)
        ],
    )
    conn.execute(
        "INSERT OR REPLACE INTO analysed_games (game_id, engine, depth) VALUES (?, ?, ?)",
        (game_id, engine_name, depth),
    )
    conn.commit()


def _stored_mate(e: PositionEval) -> int | None:
    """Position finale matée : mate_in = 0 signé par le vainqueur (+0 impossible -> on garde le signe via score)."""
    if e.terminal_winner is not None:
        return 0
    return e.mate_in


def load_evals(conn: sqlite3.Connection, game_id: int) -> list[PositionEval]:
    """Relit les évals d'une partie dans l'ordre des plies (inverse de store_evals)."""
    rows = conn.execute("SELECT * FROM evals WHERE game_id = ? ORDER BY ply", (game_id,)).fetchall()
    result = []
    for r in rows:
        winner = None
        if r["mate_in"] == 0:
            winner = chess.Board(r["fen"]).outcome().winner  # position finale matée
        result.append(
            PositionEval(
                fen=r["fen"],
                score_cp=r["score_cp"],
                mate_in=None if winner is not None else r["mate_in"],
                depth=r["depth"],
                best_move=r["best_move"],
                best_pv=r["best_pv"] or "",
                terminal_winner=winner,
            )
        )
    return result


# --- exécution parallèle : un moteur par processus, écriture SQLite dans le parent ---

_worker_engine: Stockfish | None = None
_worker_depth = DEFAULT_DEPTH


def _worker_init(binary: str | None, depth: int) -> None:
    global _worker_engine, _worker_depth
    _worker_engine = Stockfish(binary).__enter__()
    _worker_depth = depth


def _worker_run(item: tuple[int, str]) -> tuple[int, list[PositionEval], str]:
    assert _worker_engine is not None
    game_id, pgn = item
    return game_id, analyse_pgn(pgn, _worker_engine, _worker_depth), _worker_engine.name


def analyse_games(
    conn: sqlite3.Connection,
    items: list[tuple[int, str]],
    *,
    depth: int = DEFAULT_DEPTH,
    workers: int = 1,
    binary: str | None = None,
    log=lambda _: None,
) -> int:
    if not items:
        return 0
    start = time.time()
    done = 0
    if workers <= 1:
        with Stockfish(binary) as sf:
            for game_id, pgn in items:
                store_evals(conn, game_id, analyse_pgn(pgn, sf, depth), sf.name, depth)
                done += 1
                log(f"[{done}/{len(items)}] partie #{game_id} ({time.time() - start:.0f}s)")
        return done
    ctx = multiprocessing.get_context("spawn")
    with ctx.Pool(workers, initializer=_worker_init, initargs=(binary, depth)) as pool:
        for game_id, evals, name in pool.imap_unordered(_worker_run, items):
            store_evals(conn, game_id, evals, name, depth)
            done += 1
            log(f"[{done}/{len(items)}] partie #{game_id} ({time.time() - start:.0f}s)")
    return done


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyse Stockfish des parties en base (table evals).")
    parser.add_argument("--username", required=True)
    parser.add_argument("--db", default="data/chesscoach.sqlite")
    parser.add_argument("--time-class")
    parser.add_argument("--time-control")
    parser.add_argument("--depth", type=int, default=DEFAULT_DEPTH)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--stockfish", help="chemin du binaire (sinon $CHESSCOACH_STOCKFISH, bin/, PATH)")
    args = parser.parse_args(list(argv) if argv is not None else None)

    conn = db.connect(args.db)
    items = select_games(
        conn, args.username, time_class=args.time_class, time_control=args.time_control, limit=args.limit
    )
    print(f"{len(items)} partie(s) à analyser (profondeur {args.depth}, {args.workers} processus)")
    n = analyse_games(conn, items, depth=args.depth, workers=args.workers, binary=args.stockfish, log=print)
    print(f"{n} partie(s) analysée(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
