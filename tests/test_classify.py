from __future__ import annotations

import chess

from chesscoach.engine.analysis import PositionEval
from chesscoach.taxonomy import Tag
from chesscoach.taxonomy.classify import MomentContext, classify, is_endgame


def ev(fen, best=None, cp=0, mate=None, winner=None):
    return PositionEval(
        fen=fen,
        score_cp=cp if mate is None else None,
        mate_in=mate,
        depth=1,
        best_move=best,
        best_pv=best or "",
        terminal_winner=winner,
    )


def ctx(
    fen,
    played_san,
    best_before=None,
    best_reply=None,
    *,
    cp_before=0,
    cp_after=0,
    mate_before=None,
    mate_after=None,
    clock=300.0,
):
    board = chess.Board(fen)
    played = board.parse_san(played_san)
    after = board.copy()
    after.push(played)
    return MomentContext(
        board_before=board,
        played=played,
        eval_before=ev(fen, best_before, cp_before, mate_before),
        eval_after=ev(after.fen(), best_reply, cp_after, mate_after),
        clock_seconds=clock,
    )


def test_hanging_piece_when_move_puts_knight_en_prise():
    # Cavalier blanc en f3 va en g5 où le pion h6 le prend gratuitement.
    fen = "rnbqkb1r/pppp1pp1/5n1p/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 0 4"
    c = ctx(fen, "Ng5", best_before="b1c3", best_reply="h6g5")
    assert classify(c).primary == Tag.HANGING_PIECE


def test_ignored_threat_when_capture_was_already_available():
    # Le fou blanc en c4 est déjà attaqué par le pion d5 ; les blancs jouent a3, ...dxc4 gagne le fou.
    fen = "rnbqkbnr/ppp2ppp/8/3pp3/2B1P3/8/PPPP1PPP/RNBQK1NR w KQkq - 0 3"
    c = ctx(fen, "a3", best_before="c4b3", best_reply="d5c4")
    assert classify(c).primary == Tag.IGNORED_THREAT


def test_missed_mate():
    fen = "6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1"  # Ta8# disponible
    c = ctx(fen, "Rb1", best_before="a1a8", best_reply="g8f8", mate_before=1, cp_after=500)
    assert classify(c).primary == Tag.MISSED_MATE


def test_unnecessary_exchange():
    # Fxc6 bxc6 : fou contre cavalier, reprise sur la même case.
    fen = "r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4"
    c = ctx(fen, "Bxc6", best_before="e1g1", best_reply="b7c6")
    assert classify(c).primary == Tag.UNNECESSARY_EXCHANGE


def test_king_safety_rules():
    castled = "r1bq1rk1/pppp1ppp/2n2n2/2b1p3/2B1P3/2N2N2/PPPP1PPP/R1BQ1RK1 w - - 0 6"
    c = ctx(castled, "h3", best_before="d2d3", best_reply="d7d6")  # pion du bouclier, roi roqué
    assert classify(c).primary == Tag.KING_SAFETY
    uncastled = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2"
    c = ctx(uncastled, "d3", best_before="g1f3", best_reply="g8f6")  # pion central, roque encore possible
    assert classify(c).primary != Tag.KING_SAFETY
    c = ctx(uncastled, "f3", best_before="g1f3", best_reply="d8h4")  # ... Dh4+ : échec sans capture
    assert classify(c).primary == Tag.KING_SAFETY


def test_endgame_technique_and_is_endgame():
    fen = "8/5k2/8/8/8/8/4K3/4R3 w - - 0 1"
    assert is_endgame(chess.Board(fen))
    assert not is_endgame(chess.Board())
    c = ctx(fen, "Ke3", best_before="e1f1", best_reply="f7e7")
    assert classify(c).primary == Tag.ENDGAME_TECHNIQUE


def test_opening_principle_when_engine_develops_and_user_does_not():
    fen = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2"
    c = ctx(fen, "a3", best_before="g1f3", best_reply="g8f6")
    assert classify(c).primary == Tag.OPENING_PRINCIPLE
    c = ctx(fen, "Nf3", best_before="b1c3", best_reply="g8f6")  # les deux développent : pas ce tag
    assert classify(c).primary == Tag.CALCULATION_ERROR


def test_passive_piece_when_user_retreats_without_tactics():
    # Milieu de partie calme, coup 20 : le moteur avance le cavalier, l'utilisateur recule le sien.
    fen = "r2q1rk1/ppp2ppp/2n1bn2/3p4/3P4/2N1BN2/PPP2PPP/R2Q1RK1 w - - 0 20"
    c = ctx(fen, "Nb1", best_before="f3e5", best_reply="a7a6")
    assert classify(c).primary == Tag.PASSIVE_PIECE


def test_calculation_error_is_the_fallback_and_time_pressure_is_secondary():
    fen = "r2q1rk1/ppp2ppp/2n1bn2/3p4/3P4/2N1BN2/PPP2PPP/R2Q1RK1 w - - 0 20"
    c = ctx(fen, "Rb1", best_before="a2a3", best_reply="a7a6", clock=12.0)
    result = classify(c)
    assert result.primary == Tag.CALCULATION_ERROR
    assert result.tags == (Tag.CALCULATION_ERROR, Tag.TIME_PRESSURE)


def test_classify_game_end_to_end_without_engine(sample_pgn_text):
    """Évals fabriquées à la main sur le mat de Légal : 5... Bxd1?? est une gaffe tactique (la réponse 6. Bxf7+
    est une capture avec échec, donc ni pièce pendue ni sécurité du roi) -> calculation_error."""
    import chess.pgn
    import io
    from chesscoach import db
    from chesscoach.engine.analyse import store_evals
    from chesscoach.engine.analysis import PositionEval
    from chesscoach.ingest.chesscom import store_game
    from chesscoach.taxonomy.classify_games import classify_all

    conn = db.connect(":memory:")
    from chesscoach.ingest.pgn import split_games

    pgn = split_games(sample_pgn_text)[0]
    game_id = store_game(
        conn,
        "opponent_one",
        {
            "url": "g1",
            "pgn": pgn,
            "white": {"username": "coachtest"},
            "black": {"username": "opponent_one", "result": "checkmated"},
        },
    )
    game = chess.pgn.read_game(io.StringIO(pgn))
    board = game.board()
    moves = list(game.mainline_moves())
    # Éval plate jusqu'à 5... Bxd1, puis mat annoncé pour les blancs.
    evals = []
    for i in range(len(moves) + 1):
        if i == len(moves):
            evals.append(PositionEval(board.fen(), None, None, 1, None, "", terminal_winner=True))
        else:
            mate = 2 if i >= 10 else None
            best = moves[i].uci() if i >= 10 else None
            evals.append(PositionEval(board.fen(), 0 if mate is None else None, mate, 1, best, best or ""))
            board.push(moves[i])
    store_evals(conn, game_id, evals, "fake", 1)
    assert classify_all(conn, "opponent_one") == 1
    row = conn.execute("SELECT * FROM critical_moments").fetchone()
    assert (row["ply"], row["san"], row["rank"], row["phase"]) == (10, "Bxd1", 1, "opening")
    assert row["loss"] == 1000 and row["severity"] == "blunder"
    assert row["primary_tag"] == "calculation_error" and row["tags"] == "calculation_error"
    assert row["clock_seconds"] == 568.6
