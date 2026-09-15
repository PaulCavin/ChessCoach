from __future__ import annotations

import json
import threading
import urllib.request
from pathlib import Path

from chesscoach import db
from chesscoach.cli.serve import App, serve
from chesscoach.engine.analyse import store_evals
from chesscoach.ingest.chesscom import renumber_games, store_game
from chesscoach.ingest.pgn import split_games
from chesscoach.memory.learner import Answer, record_answer, sync_markdown
from chesscoach.taxonomy.classify_games import classify_all
from tests.test_report import _fake_evals


def _setup(db_path):
    conn = db.connect(db_path)
    g2 = split_games((Path(__file__).parent / "fixtures/sample_chesscom.pgn").read_text(encoding="utf-8"))[1]
    gid = store_game(
        conn,
        "coachtest",
        {
            "url": "https://x/2",
            "pgn": g2,
            "rules": "chess",
            "time_class": "rapid",
            "time_control": "600",
            "end_time": 1742030000,
            "white": {"username": "opponent_two", "result": "win"},
            "black": {"username": "coachtest", "result": "checkmated", "rating": 905},
        },
    )
    renumber_games(conn, "coachtest")
    store_evals(conn, gid, _fake_evals(g2, 6), "fake", 1)
    classify_all(conn, "coachtest")
    return conn, gid


def test_record_answer_and_markdown_preserve_notes(tmp_path):
    conn, gid = _setup(tmp_path / "m.sqlite")
    root = tmp_path / "learner"
    record_answer(conn, Answer("coachtest", gid, 6, "g6", "protéger f7", 70, "other"))
    files = sync_markdown(conn, "coachtest", gid, root)
    tag_note = root / "tags/calculation_error.md"
    assert tag_note in files and (root / "profile.md") in files
    text = tag_note.read_text(encoding="utf-8")
    assert (
        text.startswith("---\ntag: calculation_error")
        and "occurrences: 1" in text
        and "| g6 | 70 | ? non évalué | protéger f7 |" in text
    )
    assert "## Notes" in text
    # l'utilisateur écrit dans Notes ; une nouvelle synchro doit la conserver
    tag_note.write_text(text + "\nJe pends souvent f7 après ...Cf6 trop tôt.\n", encoding="utf-8")
    record_answer(conn, Answer("coachtest", gid, 6, "Nf6", None, 30, "played"))
    sync_markdown(conn, "coachtest", gid, root)
    text2 = tag_note.read_text(encoding="utf-8")
    assert "occurrences: 2" in text2 and "Je pends souvent f7" in text2 and text2.count("## Notes") == 1
    sessions = list((root / "sessions").glob("*_g1.md"))
    assert len(sessions) == 1 and "Ton essai : **Nf6** → ✖ coup de la partie" in sessions[0].read_text(encoding="utf-8")


def test_record_answer_rejects_unknown_moment(tmp_path):
    conn, gid = _setup(tmp_path / "m.sqlite")
    try:
        record_answer(conn, Answer("coachtest", gid, 3, "e5", None, None, "other"))
    except ValueError as exc:
        assert "moment critique" in str(exc)
    else:
        raise AssertionError("attendu ValueError")


def test_server_serves_pages_and_records_answers(tmp_path):
    db_path = tmp_path / "m.sqlite"
    _setup(db_path)
    app = App(str(db_path), "coachtest", tmp_path / "learner")
    server = serve(app, port=0)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{port}"
        index = urllib.request.urlopen(base + "/").read().decode()
        assert "/game/1" in index
        page = urllib.request.urlopen(base + "/game/1").read().decode()
        assert '"served": true' in page and "Nf6" in page
        req = urllib.request.Request(
            base + "/api/answer",
            method="POST",
            headers={"Content-Type": "application/json"},
            data=json.dumps(
                {"game_number": 1, "ply": 6, "san": "Nf6", "plan": "", "confidence": 55, "verdict": "played"}
            ).encode(),
        )
        res = json.load(urllib.request.urlopen(req))
        assert res["ok"] and any(f.endswith("calculation_error.md") for f in res["files"])
        bad = urllib.request.Request(
            base + "/api/answer", method="POST", data=b'{"game_number": 1, "ply": 2, "san": "e5", "verdict": "other"}'
        )
        try:
            urllib.request.urlopen(bad)
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
        else:
            raise AssertionError("attendu 400")
    finally:
        server.shutdown()
