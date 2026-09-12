from __future__ import annotations

import io

import chess.pgn

from chesscoach import db
from chesscoach.engine.analyse import store_evals
from chesscoach.engine.analysis import PositionEval
from chesscoach.ingest.chesscom import store_game
from chesscoach.ingest.pgn import split_games
from chesscoach.report.aggregate import build_report
from chesscoach.report.render import render
from chesscoach.taxonomy.classify_games import classify_all


def _fake_evals(pgn: str, blunder_ply: int) -> list[PositionEval]:
    """Éval nulle partout, mat annoncé pour les blancs dans les positions d'index >= blunder_ply,
    c'est-à-dire juste après le coup noir numéro blunder_ply."""
    game = chess.pgn.read_game(io.StringIO(pgn))
    board = game.board()
    moves = list(game.mainline_moves())
    evals = []
    for i in range(len(moves) + 1):
        if i == len(moves):
            evals.append(PositionEval(board.fen(), None, None, 1, None, "", terminal_winner=True))
            break
        mate = 2 if i >= blunder_ply else None
        best = moves[i].uci()  # "meilleur coup" = coup de la partie (évals fabriquées)
        evals.append(PositionEval(board.fen(), 0 if mate is None else None, mate, 1, best, best))
        board.push(moves[i])
    return evals


def test_report_on_fixture(sample_pgn_text):
    conn = db.connect(":memory:")
    g1, g2 = split_games(sample_pgn_text)
    # L'utilisateur est "coachtest" : gagne g1 (blancs), perd g2 (noirs, mat du berger).
    store_game(
        conn,
        "coachtest",
        {
            "url": "https://x/1",
            "pgn": g1,
            "time_class": "rapid",
            "time_control": "600",
            "rules": "chess",
            "end_time": 1741975540,
            "eco": "https://www.chess.com/openings/Philidor-Defense",
            "white": {"username": "coachtest", "result": "win", "rating": 912},
            "black": {"username": "opponent_one", "result": "checkmated"},
        },
    )
    store_game(
        conn,
        "coachtest",
        {
            "url": "https://x/2",
            "pgn": g2,
            "time_class": "rapid",
            "time_control": "600",
            "rules": "chess",
            "end_time": 1742030000,
            "eco": "https://www.chess.com/openings/Wayward-Queen",
            "white": {"username": "opponent_two", "result": "win"},
            "black": {"username": "coachtest", "result": "checkmated", "rating": 905},
        },
    )
    store_evals(conn, "https://x/1", _fake_evals(g1, 10), "fake", 1)
    store_evals(conn, "https://x/2", _fake_evals(g2, 6), "fake", 1)  # 3... Nf6?? (ply 6) permet Dxf7#
    classify_all(conn, "coachtest")

    r = build_report(conn, "coachtest", time_class="rapid")
    assert r.overview.games == 2 and r.overview.wins == 1 and r.overview.losses == 1
    assert r.overview.elo_min == 905 and r.overview.elo_max == 912
    assert r.phases["opening"].moves == 7 + 3  # coups de l'utilisateur : 7 en g1, 3 en g2
    assert r.phases["opening"].blunders == 1
    assert r.total_moments == 1
    assert r.tags["missed_mate"].count == 0
    tagged = [t for t, s in r.tags.items() if s.count]
    assert tagged == ["calculation_error"]  # ... Nf6 pend le mat en f7 : capture-échec -> tactique
    ex = r.tags["calculation_error"].examples[0]
    assert (ex.san, ex.ply, ex.loss) == ("Nf6", 6, 1000)
    assert ex.best_move_san == "Nf6"  # évals fabriquées : le "meilleur coup" est le coup de la partie
    assert r.clock["> 5 min"].moves == 10
    assert [m[0] for m in r.monthly] == ["2025-03"]

    text = render(r)
    assert "# Rapport ChessCoach — coachtest (rapid)" in text
    assert "**2 parties analysées**" in text
    assert "| Erreur de calcul | 1 | 100 % |" in text
    assert ex.fen.startswith("r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b") and f"`{ex.fen}`" in text
    assert "| Philidor Defense | blancs | 1 |" not in text  # < 5 parties : non listée
