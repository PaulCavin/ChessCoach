from chesscoach import db
from chesscoach.cli import update
from chesscoach.ingest import chesscom


def test_update_runs_end_to_end_without_engine_or_network(tmp_path, monkeypatch, capsys):
    """Réseau coupé, Stockfish absent : la commande doit terminer proprement avec ce qu'elle a."""
    db_path = tmp_path / "u.sqlite"
    db.connect(db_path).close()
    monkeypatch.setattr(chesscom, "fetch_json", lambda url, **k: (_ for _ in ()).throw(OSError("hors ligne")))
    monkeypatch.setattr(update, "ingest", lambda conn, u, log: (_ for _ in ()).throw(OSError("hors ligne")))
    assert update.main(["--username", "coachtest", "--db", str(db_path), "--out", str(tmp_path / "html")]) == 0
    out = capsys.readouterr().out
    assert "hors ligne" in out and "0 partie(s) analysée(s)" in out and "terminé" in out
    assert (tmp_path / "html" / "index.html").exists() and (tmp_path / "html" / "progress.html").exists()
