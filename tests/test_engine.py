from __future__ import annotations

import pytest

from chesscoach import db
from chesscoach.engine import (
    MATE_CP,
    CriticalMoment,
    MoveLoss,
    PositionEval,
    critical_moments,
    default_binary,
    move_losses,
)
from chesscoach.engine.analysis import CRITICAL_CP
from chesscoach.ingest.pgn import parse_games


def ev(cp=None, mate=None, best="e2e4", winner=None):
    return PositionEval(
        fen="fen", score_cp=cp, mate_in=mate, depth=1, best_move=best, best_pv=best, terminal_winner=winner
    )


def test_to_cp_clamps_and_handles_mates():
    assert ev(cp=37).to_cp() == 37
    assert ev(cp=5000).to_cp() == MATE_CP
    assert ev(mate=3).to_cp() == MATE_CP
    assert ev(mate=-1).to_cp() == -MATE_CP
    assert ev(winner=True).to_cp() == MATE_CP
    assert ev(winner=False).to_cp() == -MATE_CP


def test_move_losses_are_from_mover_point_of_view():
    # Blancs jouent (0 -> +50 : gain, perte 0), noirs jouent (+50 -> +400 : perte 350 pour les noirs).
    evals = [ev(cp=0), ev(cp=50), ev(cp=400)]
    losses = move_losses(evals, ["e4", "f6"])
    assert [m.loss for m in losses] == [0, 350]
    assert losses[1].color == "black" and losses[1].before_cp == -50 and losses[1].after_cp == -400
    assert losses[1].severity == "blunder"
    assert losses[0].severity is None


def test_move_losses_length_mismatch():
    with pytest.raises(ValueError):
        move_losses([ev(cp=0)], ["e4", "e5"])


def test_critical_moments_filters_user_color_and_ranks():
    def loss(ply, color, cp):
        return MoveLoss(ply=ply, color=color, san="x", before_cp=0, after_cp=-cp, loss=cp, best_move=None, fen="f")

    losses = [
        loss(1, "white", 500),
        loss(2, "black", 200),
        loss(3, "white", 149),
        loss(4, "black", 150),
        loss(6, "black", 400),
        loss(8, "black", 999),
        loss(10, "black", 998),
        loss(12, "black", 997),
    ]
    cms = critical_moments(losses, "black")
    assert [c.move.ply for c in cms] == [8, 10, 12, 6]
    assert [c.rank for c in cms] == [1, 2, 3, 4]
    assert critical_moments(losses, "white", threshold=CRITICAL_CP) == [CriticalMoment(move=losses[0], rank=1)]


needs_stockfish = pytest.mark.skipif(default_binary() is None, reason="Stockfish absent")


@needs_stockfish
def test_analyse_fixture_game_roundtrip(sample_pgn_text):
    from chesscoach.engine import Stockfish
    from chesscoach.engine.analyse import analyse_pgn, load_evals, store_evals

    game = parse_games(sample_pgn_text)[0]  # mat de Légal : 5... Bxd1?? puis 7. Nd5#
    with Stockfish() as sf:
        evals = analyse_pgn(game.pgn, sf, depth=10)
    assert len(evals) == game.ply_count + 1
    assert evals[-1].terminal_winner is True and evals[-1].best_move is None
    losses = move_losses(evals, [m.san for m in game.moves])
    bxd1 = losses[9]
    assert bxd1.san == "Bxd1" and bxd1.color == "black" and bxd1.loss >= 500
    assert losses[10].best_move == "c4f7"  # 6. Bxf7+ est forcé

    conn = db.connect(":memory:")
    conn.execute(
        "INSERT INTO games (id, url, username, user_color, white, black, result, user_result, ply_count, pgn)"
        " VALUES (7, 'u/1', 'u', 'white', 'a', 'b', '1-0', 'win', ?, ?)",
        (game.ply_count, game.pgn),
    )
    store_evals(conn, 7, evals, "sf", 10)
    assert load_evals(conn, 7) == evals
    assert conn.execute("SELECT depth FROM analysed_games WHERE game_id = 7").fetchone()[0] == 10


def test_incompatible_old_database_is_refused(tmp_path):
    import sqlite3

    path = tmp_path / "old.sqlite"
    raw = sqlite3.connect(path)
    raw.executescript("CREATE TABLE schema_version (version INTEGER NOT NULL); INSERT INTO schema_version VALUES (1);")
    raw.commit()
    raw.close()
    with pytest.raises(RuntimeError, match="incompatible"):
        db.connect(path)


def test_current_database_reopens_and_keeps_version(tmp_path):
    path = tmp_path / "cur.sqlite"
    db.connect(path).close()
    conn = db.connect(path)
    assert conn.execute("SELECT version FROM schema_version").fetchone()[0] == db.SCHEMA_VERSION
    assert conn.execute("SELECT count(*) FROM evals").fetchone()[0] == 0
