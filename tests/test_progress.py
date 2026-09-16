from __future__ import annotations

import sqlite3

from chesscoach import db
from chesscoach.memory.fsrs import load_card
from chesscoach.memory.progress import apply_retirements, rebuild_schedule, tag_progress

TAG = "hanging_piece"


def _base(tmp_path) -> sqlite3.Connection:
    conn = db.connect(tmp_path / "pr.sqlite")
    for i in range(1, 31):  # 30 parties analysées, la n° 30 étant la plus récente
        conn.execute(
            "INSERT INTO games (id, url, username, user_color, white, black, result, user_result, ply_count, pgn,"
            " end_time, rules, game_number) VALUES (?, ?, 'u', 'white', 'u', 'o', '1-0', 'win', 2, 'p', ?, 'chess', ?)",
            (i, f"u{i}", i, i),
        )
        conn.execute("INSERT INTO analysed_games (game_id, engine, depth) VALUES (?, 'sf', 14)", (i,))
    conn.commit()
    return conn


def _moment(conn, game_id, ply=1, tag=TAG):
    conn.execute(
        "INSERT INTO critical_moments (game_id, ply, rank, san, fen_before, best_move, before_cp, after_cp, loss,"
        " severity, phase, primary_tag, tags) VALUES (?, ?, 1, 'e4', 'f', 'e2e4', 0, -200, 200, 'mistake',"
        " 'middlegame', ?, ?)",
        (game_id, ply, tag, tag),
    )
    conn.commit()


def _event(conn, game_id, verdict, ts, confidence=50, tag=TAG):
    conn.execute(
        "INSERT INTO learner_events (ts, username, game_id, ply, primary_tag, tags, user_move, confidence, verdict,"
        " loss, kind) VALUES (?, 'u', ?, 1, ?, ?, 'e4', ?, ?, 200, 'answer')",
        (ts, game_id, tag, tag, confidence, verdict),
    )
    conn.commit()


def test_rebuild_schedule_is_deterministic_and_replayable(tmp_path):
    conn = _base(tmp_path)
    _moment(conn, 1)
    _event(conn, 1, "played", "2026-01-01T10:00:00Z")
    _event(conn, 1, "best", "2026-01-05T10:00:00Z")
    first = rebuild_schedule(conn, "u")
    again = rebuild_schedule(conn, "u")
    assert first[TAG] == again[TAG]
    card = load_card(conn, "u", TAG)
    assert card.reps == 2 and card.lapses == 1 and card.state == "review"
    assert conn.execute("SELECT count(*) FROM tag_schedule").fetchone()[0] == 1


def test_retirement_requires_success_and_decline_in_real_games(tmp_path):
    conn = _base(tmp_path)
    # motif fréquent dans les vieilles parties (1 à 10), absent des 20 récentes
    for gid in range(1, 11):
        _moment(conn, gid)
    for i, gid in enumerate(range(1, 6)):
        _event(conn, gid, "best", f"2026-02-0{i + 1}T10:00:00Z", confidence=85)
    prog = tag_progress(conn, "u", TAG)
    assert prog.reviews == 5 and prog.success_rate == 1.0
    assert prog.recent_per_game == 0.0 and prog.baseline_per_game == 1.0 and prog.declining
    rebuild_schedule(conn, "u")
    assert apply_retirements(conn, "u") == [TAG]
    assert load_card(conn, "u", TAG).state == "retired"
    assert apply_retirements(conn, "u") == []  # déjà retiré : pas de second retrait


def test_no_retirement_when_pattern_still_present(tmp_path):
    conn = _base(tmp_path)
    for gid in range(1, 31):  # présent partout : pas de recul
        _moment(conn, gid)
    for i in range(5):
        _event(conn, i + 1, "best", f"2026-02-0{i + 1}T10:00:00Z", confidence=85)
    prog = tag_progress(conn, "u", TAG)
    assert prog.success_rate == 1.0 and not prog.declining and not prog.can_retire
    rebuild_schedule(conn, "u")
    assert apply_retirements(conn, "u") == []


def test_puzzle_attempts_feed_the_schedule(tmp_path):
    conn = _base(tmp_path)
    _moment(conn, 1)
    _event(conn, 1, "played", "2026-03-01T10:00:00Z")
    conn.execute(
        "INSERT INTO puzzles (id, fen, moves, rating, themes, tags) VALUES ('p1', 'f', 'e2e4', 900, 'x', ?)", (TAG,)
    )
    conn.execute(
        "INSERT INTO puzzle_attempts (ts, username, puzzle_id, tag, solved, first_try)"
        " VALUES ('2026-03-05T10:00:00Z', 'u', 'p1', ?, 1, 1)",
        (TAG,),
    )
    conn.commit()
    cards = rebuild_schedule(conn, "u")
    assert cards[TAG].reps == 2
    assert tag_progress(conn, "u", TAG).reviews == 2


def test_progress_page_shows_sparkline_and_state(tmp_path):
    from datetime import date

    from chesscoach.report.progress import build, sparkline, weeks

    conn = _base(tmp_path)
    # parties datées : 2 semaines de suite, motif présent la 1re, absent la 2e
    conn.execute("UPDATE games SET played_at = '2026-01-05T10:00:00Z' WHERE id <= 2")
    conn.execute("UPDATE games SET played_at = '2026-01-12T10:00:00Z' WHERE id IN (3, 4)")
    conn.commit()
    _moment(conn, 1)
    _moment(conn, 2)
    _event(conn, 1, "best", "2026-01-13T10:00:00Z", confidence=90)
    ws = weeks(conn, "u", 2, today=date(2026, 1, 16))
    assert [w.games for w in ws] == [2, 2]
    assert ws[0].per_tag == {TAG: 2} and ws[1].per_tag == {}
    page = build(conn, "u", 2, today=date(2026, 1, 16))
    assert "Pièce pendue" in page and "<svg" in page and "en cours" in page  # 1 révision = état learning
    assert "polyline" in sparkline([1.0, 0.0]) and "polyline" not in sparkline([None, None])
