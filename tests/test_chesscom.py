from __future__ import annotations

import json

import pytest

from chesscoach import db
from chesscoach.ingest import chesscom
from chesscoach.ingest.pgn import split_games

USERNAME = "coachtest"


def make_game_json(pgn: str, url: str, white: str, black: str, white_result: str, black_result: str) -> dict:
    return {
        "url": url,
        "pgn": pgn,
        "time_control": "600",
        "end_time": 1741975540,
        "rated": True,
        "time_class": "rapid",
        "rules": "chess",
        "eco": "https://www.chess.com/openings/Philidor-Defense",
        "white": {"rating": 912, "result": white_result, "username": white},
        "black": {"rating": 898, "result": black_result, "username": black},
    }


@pytest.fixture
def fake_api(sample_pgn_text):
    """Simule l'API Chess.com à partir du PGN de fixture (un mois d'archive)."""
    g1, g2 = split_games(sample_pgn_text)
    games = [
        make_game_json(
            g1, "https://www.chess.com/game/live/100000000001", USERNAME, "opponent_one", "win", "checkmated"
        ),
        make_game_json(
            g2, "https://www.chess.com/game/live/100000000002", "opponent_two", USERNAME, "win", "checkmated"
        ),
    ]
    responses = {
        f"{chesscom.API_BASE}/player/{USERNAME}/games/archives": {
            "archives": [f"{chesscom.API_BASE}/player/{USERNAME}/games/2025/03"]
        },
        f"{chesscom.API_BASE}/player/{USERNAME}/games/2025/03": {"games": games},
    }
    calls: list[str] = []

    def fetch(url: str) -> dict:
        calls.append(url)
        return json.loads(json.dumps(responses[url]))

    fetch.calls = calls
    return fetch


@pytest.fixture
def conn():
    return db.connect(":memory:")


def test_list_archives(fake_api):
    assert chesscom.list_archives(USERNAME, fake_api) == [(2025, 3)]


def test_ingest_stores_games_and_moves(conn, fake_api):
    total = chesscom.ingest(conn, USERNAME, fetch=fake_api)
    assert total == 2
    assert conn.execute("SELECT count(*) FROM games").fetchone()[0] == 2
    assert conn.execute("SELECT count(*) FROM moves").fetchone()[0] == 13 + 7

    g1 = conn.execute("SELECT * FROM games WHERE id LIKE '%0001'").fetchone()
    assert g1["user_color"] == "white"
    assert g1["user_result"] == "win"
    assert g1["white_elo"] == 912 and g1["black_elo"] == 898
    assert g1["time_class"] == "rapid" and g1["time_control"] == "600"
    assert g1["rated"] == 1
    assert g1["eco"].endswith("Philidor-Defense")
    assert g1["played_at"] == "2025-03-14T18:05:40Z"
    assert g1["ply_count"] == 13
    assert g1["pgn"].startswith("[Event")

    g2 = conn.execute("SELECT * FROM games WHERE id LIKE '%0002'").fetchone()
    assert g2["user_color"] == "black"
    assert g2["user_result"] == "loss"

    moves = conn.execute(
        "SELECT ply, move_number, color, san, clock_seconds FROM moves WHERE game_id = ? ORDER BY ply", (g1["id"],)
    ).fetchall()
    assert tuple(moves[0]) == (1, 1, "white", "e4", 598.7)
    assert tuple(moves[1]) == (2, 1, "black", "e5", 597.1)
    assert tuple(moves[-1]) == (13, 7, "white", "Nd5#", 548.4)


def test_ingest_is_idempotent(conn, fake_api):
    chesscom.ingest(conn, USERNAME, fetch=fake_api)
    calls_after_first = len(fake_api.calls)
    assert chesscom.ingest(conn, USERNAME, fetch=fake_api) == 0
    # Le mois est marqué comme téléchargé : seul l'index des archives est redemandé.
    assert len(fake_api.calls) == calls_after_first + 1
    assert conn.execute("SELECT count(*) FROM games").fetchone()[0] == 2
    month = conn.execute("SELECT * FROM archive_months").fetchone()
    assert (month["year"], month["month"], month["game_count"]) == (2025, 3, 2)


def test_ingest_respects_since_until(conn, fake_api):
    assert chesscom.ingest(conn, USERNAME, since="2025-04", fetch=fake_api) == 0
    assert chesscom.ingest(conn, USERNAME, until="2025-02", fetch=fake_api) == 0
    assert chesscom.ingest(conn, USERNAME, since="2025-03", until="2025-03", fetch=fake_api) == 2


def test_games_without_pgn_are_skipped(conn):
    assert chesscom.store_game(conn, USERNAME, {"url": "x", "white": {}, "black": {}}) is False


def test_cli_main(tmp_path, fake_api, monkeypatch, capsys):
    monkeypatch.setattr(chesscom, "fetch_json", fake_api)
    db_path = tmp_path / "coach.sqlite"
    assert chesscom.main([USERNAME, "--db", str(db_path)]) == 0
    out = capsys.readouterr().out
    assert "2025-03 : 2 nouvelle(s) partie(s)" in out
    assert "2 partie(s) au total" in out
    assert db.connect(db_path).execute("SELECT count(*) FROM games").fetchone()[0] == 2
