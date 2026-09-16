from __future__ import annotations

from pathlib import Path

from chesscoach import db
from chesscoach.puzzles.lichess import import_puzzles, open_csv, tags_for
from chesscoach.puzzles.select import pick, record_attempt, user_rating

CSV = Path(__file__).parent / "fixtures/puzzles_sample.csv"


def _conn_with_puzzles(tmp_path, **kw):
    conn = db.connect(tmp_path / "p.sqlite")
    counts = import_puzzles(conn, open_csv(str(CSV)), **kw)
    return conn, counts


def test_tags_for_maps_lichess_themes():
    assert tags_for("hangingPiece mate mateIn2 short") == ["hanging_piece", "missed_mate"]
    assert tags_for("endgame rookEndgame") == ["endgame_technique"]
    assert tags_for("zugzwang quietMove") == []  # aucun tag : le puzzle est écarté


def test_import_filters_by_theme_and_rating(tmp_path):
    conn, counts = _conn_with_puzzles(tmp_path, min_rating=600, max_rating=1400)
    ids = {r["id"] for r in conn.execute("SELECT id FROM puzzles")}
    assert "00sHx" not in ids  # cote 1760 hors plage
    assert "00zzz" not in ids  # aucun thème connu
    assert {"00sO1", "00sVx", "00sYh", "00sn2"} <= ids
    assert counts["endgame_technique"] == 1 and counts["missed_mate"] == 1
    row = conn.execute("SELECT * FROM puzzles WHERE id = '00sVx'").fetchone()
    assert row["tags"] == "hanging_piece,missed_mate" and row["rating"] == 720
    assert row["moves"].split()[0] == "d6h6"


def test_import_is_idempotent_and_respects_limit(tmp_path):
    conn, _ = _conn_with_puzzles(tmp_path)
    before = conn.execute("SELECT count(*) FROM puzzles").fetchone()[0]
    import_puzzles(conn, open_csv(str(CSV)))
    assert conn.execute("SELECT count(*) FROM puzzles").fetchone()[0] == before
    conn2 = db.connect(tmp_path / "p2.sqlite")
    counts = import_puzzles(conn2, open_csv(str(CSV)), limit_per_tag=1)
    assert conn2.execute("SELECT count(*) FROM puzzles").fetchone()[0] < before
    # un puzzle multi-tags peut faire dépasser d'une unité un tag déjà servi (cf. docstring)
    assert all(n <= 2 for n in counts.values()) and counts["endgame_technique"] == 1


def test_pick_prefers_close_rating_and_skips_attempted(tmp_path):
    conn, _ = _conn_with_puzzles(tmp_path)
    picked = pick(conn, "coachtest", "missed_mate", n=2, rating=700)
    assert [p["id"] for p in picked] == ["00sVx"]
    record_attempt(conn, "coachtest", "00sVx", "missed_mate", solved=True, first_try=True)
    assert pick(conn, "coachtest", "missed_mate", n=2, rating=700) == []
    assert conn.execute("SELECT first_try FROM puzzle_attempts").fetchone()[0] == 1
    # un puzzle non résolu ne compte pas comme réussi du premier coup
    record_attempt(conn, "coachtest", "00sO1", "calculation_error", solved=False, first_try=True)
    assert conn.execute("SELECT first_try FROM puzzle_attempts WHERE puzzle_id = '00sO1'").fetchone()[0] == 0


def test_user_rating_reads_last_game(tmp_path):
    conn, _ = _conn_with_puzzles(tmp_path)
    assert user_rating(conn, "inconnu") is None
    conn.execute(
        "INSERT INTO games (id, url, username, user_color, white, black, result, user_result, ply_count, pgn, end_time,"
        " rules, black_elo) VALUES (1, 'u', 'coachtest', 'black', 'a', 'coachtest', '1-0', 'loss', 2, 'p', 10, 'chess', 880)"
    )
    assert user_rating(conn, "coachtest") == 880
