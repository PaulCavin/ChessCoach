"""Bilan visuel par partie (HTML autonome, échiquiers SVG python-chess, courbe d'éval).
``python -m chesscoach.report.html --username Kuga06 --games 10 --out reports/html``"""

from __future__ import annotations

import argparse
import html
import sqlite3
import sys
from pathlib import Path

import chess
import chess.svg

from chesscoach import db
from chesscoach.agents.critic import abstention
from chesscoach.agents.facts import build_facts
from chesscoach.engine.analyse import load_evals
from chesscoach.engine.analysis import move_losses
from chesscoach.report.render import TAG_LABEL

CSS = """
body{font-family:system-ui,sans-serif;background:#1b1b1b;color:#eee;margin:0;padding:16px;max-width:900px;margin:auto}
a{color:#9ad}h1,h2{font-weight:600}.card{background:#262522;border-radius:12px;padding:16px;margin:16px 0}
.row{display:flex;flex-wrap:wrap;gap:16px;align-items:flex-start}.board{flex:0 0 360px;max-width:100%}
.txt{flex:1 1 300px}.badge{display:inline-block;border-radius:8px;padding:2px 8px;font-weight:700}
.blunder{background:#c0392b}.mistake{background:#e67e22}.inaccuracy{background:#f1c40f;color:#222}
.eval{font-size:1.4em;font-weight:700}.pill{background:#3a3a3a;border-radius:8px;padding:2px 8px;margin-right:6px}
svg.curve{width:100%;height:90px;background:#111;border-radius:8px}table{border-collapse:collapse}td,th{padding:4px 10px;text-align:left}
.legend span{margin-right:12px}.good{color:#7bd38a}.bad{color:#ff7b6b}
"""


def eval_curve(evals, user_white: bool) -> str:
    pts = []
    n = len(evals)
    for i, e in enumerate(evals):
        cp = e.to_cp() if user_white else -e.to_cp()
        y = 45 - max(-45, min(45, cp / 1000 * 45))
        pts.append(f"{i / max(1, n - 1) * 100:.1f},{y:.1f}")
    return (
        f'<svg class="curve" viewBox="0 0 100 90" preserveAspectRatio="none">'
        f'<line x1="0" y1="45" x2="100" y2="45" stroke="#555" stroke-width="0.3"/>'
        f'<polyline points="{" ".join(pts)}" fill="none" stroke="#7bd38a" stroke-width="0.8"/></svg>'
    )


def board_svg(fen: str, played: chess.Move, best: chess.Move, flip: bool) -> str:
    board = chess.Board(fen)
    arrows = [
        chess.svg.Arrow(played.from_square, played.to_square, color="#d33"),
        chess.svg.Arrow(best.from_square, best.to_square, color="#3a3"),
    ]
    return chess.svg.board(
        board,
        arrows=arrows,
        orientation=chess.BLACK if flip else chess.WHITE,
        size=360,
        lastmove=None,
        colors={"square light": "#eeeed2", "square dark": "#769656"},
    )


def game_page(conn: sqlite3.Connection, game: sqlite3.Row) -> str:
    evals = load_evals(conn, game["id"])
    sans = [r["san"] for r in conn.execute("SELECT san FROM moves WHERE game_id = ? ORDER BY ply", (game["id"],))]
    losses = move_losses(evals, sans)
    user_white = game["user_color"] == "white"
    moments = conn.execute("SELECT * FROM critical_moments WHERE game_id = ? ORDER BY ply", (game["id"],)).fetchall()
    mine = [m for m in losses if m.color == game["user_color"]]
    sev = {"blunder": 0, "mistake": 0, "inaccuracy": 0}
    for m in mine:
        if m.severity:
            sev[m.severity] += 1
    out = [
        f"<!doctype html><meta charset=utf-8><title>Partie n° {game['game_number']}</title><style>{CSS}</style>",
        "<p><a href='index.html'>← toutes les parties</a></p>",
        f"<h1>Partie n° {game['game_number']} — {html.escape(game['white'])} vs {html.escape(game['black'])}</h1>",
        f"<p><span class=pill>{game['played_at'][:10]}</span><span class=pill>{game['time_class']} {game['time_control']}</span>"
        f"<span class=pill>{'blancs' if user_white else 'noirs'}</span><span class=pill>résultat : {game['user_result']}</span>"
        f"<a href='{game['url']}'>voir sur Chess.com</a></p>",
        "<div class=card>",
        eval_curve(evals, user_white),
        f"<p class=legend><span class='badge blunder'>{sev['blunder']} gaffes</span> <span class='badge mistake'>{sev['mistake']} erreurs</span> "
        f"<span class='badge inaccuracy'>{sev['inaccuracy']} imprécisions</span> — perte moyenne par coup : {sum(m.loss for m in mine) / max(1, len(mine)):.0f} cp</p></div>",
        "<h2>Moments critiques</h2>",
    ]
    for cm in moments:
        mf = build_facts(conn, game["id"], cm["ply"])
        board = chess.Board(cm["fen_before"])
        played = board.parse_san(cm["san"])
        best = chess.Move.from_uci(cm["best_move"])
        move_no = (cm["ply"] + 1) // 2
        dots = "." if cm["ply"] % 2 else "..."
        out.append("<div class=card><div class=row>")
        out.append(f"<div class=board>{board_svg(cm['fen_before'], played, best, not user_white)}</div>")
        out.append("<div class=txt>")
        out.append(
            f"<p><span class='badge {cm['severity']}'>{cm['severity']}</span> <b>{move_no}{dots}{cm['san']}</b> "
            f"<span class=eval>{cm['before_cp'] / 100:+.2f} → {cm['after_cp'] / 100:+.2f}</span></p>"
        )
        out.append(
            f"<p><span class=pill>{TAG_LABEL[cm['primary_tag']]}</span>"
            + (f"<span class=pill>{TAG_LABEL['time_pressure']}</span>" if "time_pressure" in cm["tags"] else "")
            + f"<span class=pill>{int(cm['clock_seconds'])} s</span></p>"
            if cm["clock_seconds"]
            else "</p>"
        )
        out.append(
            f"<p><span class=bad>■</span> joué {cm['san']} &nbsp; <span class=good>■</span> meilleur {html.escape(mf.best_san)}</p>"
        )
        out.append(f"<p>{html.escape(abstention(mf))}</p>")
        out.append(
            "<details><summary>faits vérifiés</summary><ul>"
            + "".join(f"<li>{html.escape(f.text)}</li>" for f in mf.facts)
            + "</ul></details>"
        )
        out.append("</div></div></div>")
    return "\n".join(out)


def index_page(games: list[sqlite3.Row], username: str) -> str:
    rows = "".join(
        f"<tr><td><a href='game_{g['game_number']}.html'>n° {g['game_number']}</a></td><td>{g['played_at'][:10]}</td>"
        f"<td>{'blancs' if g['user_color'] == 'white' else 'noirs'}</td><td>{html.escape(g['black'] if g['user_color'] == 'white' else g['white'])}</td>"
        f"<td class={'good' if g['user_result'] == 'win' else 'bad' if g['user_result'] == 'loss' else ''}>{g['user_result']}</td><td>{g['n_moments']}</td></tr>"
        for g in games
    )
    return (
        f"<!doctype html><meta charset=utf-8><title>ChessCoach — {username}</title><style>{CSS}</style>"
        f"<h1>Bilans visuels — {html.escape(username)}</h1><div class=card><table><tr><th>Partie</th><th>Date</th><th>Couleur</th>"
        f"<th>Adversaire</th><th>Résultat</th><th>Moments critiques</th></tr>{rows}</table></div>"
    )


def build(conn: sqlite3.Connection, username: str, out_dir: Path, n_games: int) -> list[int]:
    games = conn.execute(
        """SELECT g.*, (SELECT count(*) FROM critical_moments cm WHERE cm.game_id = g.id) AS n_moments
           FROM games g JOIN analysed_games a ON a.game_id = g.id WHERE g.username = ? ORDER BY g.end_time DESC LIMIT ?""",
        (username, n_games),
    ).fetchall()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(index_page(games, username), encoding="utf-8")
    for g in games:
        (out_dir / f"game_{g['game_number']}.html").write_text(game_page(conn, g), encoding="utf-8")
    return [g["game_number"] for g in games]


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--username", required=True)
    p.add_argument("--db", default="data/chesscoach.sqlite")
    p.add_argument("--games", type=int, default=10)
    p.add_argument("--out", default="reports/html")
    a = p.parse_args(argv)
    nums = build(db.connect(a.db), a.username, Path(a.out), a.games)
    print(f"{len(nums)} page(s) écrites dans {a.out}/ (index.html)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
