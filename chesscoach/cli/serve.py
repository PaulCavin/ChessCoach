"""Serveur local (stdlib) : sert les bilans HTML et enregistre les réponses de l'apprenant.

``python -m chesscoach.cli.serve --username Kuga06 [--port 8765] [--games 10]``
Routes : GET /            index des parties
         GET /game/<n>    bilan de la partie n° n
         GET /progress    progression par tag (FSRS + motif dans les parties réelles)
         GET /puzzle[/<tag>]  puzzles Lichess jouables (tag dû par défaut)
         POST /api/answer {game_number, ply, san, plan, confidence, verdict, kind}
         POST /api/puzzle {puzzle_id, tag, solved, first_try}
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from chesscoach import db
from chesscoach.memory.fsrs import load_card
from chesscoach.memory.learner import Answer, record_answer, sync_markdown
from chesscoach.memory.progress import rebuild_schedule
from chesscoach.puzzles.select import record_attempt
from chesscoach.report.html import game_page, index_page
from chesscoach.report.progress import build as progress_page
from chesscoach.report.puzzle import build as puzzle_page


class App:
    def __init__(self, db_path: str, username: str, memory_root: Path, n_games: int = 10):
        self.db_path, self.username, self.memory_root, self.n_games = db_path, username, memory_root, n_games
        self.lock = threading.Lock()

    def conn(self) -> sqlite3.Connection:
        return db.connect(self.db_path)

    def index(self) -> str:
        conn = self.conn()
        games = conn.execute(
            """SELECT g.*, (SELECT group_concat(severity) FROM (SELECT severity FROM critical_moments cm WHERE cm.game_id = g.id ORDER BY ply)) AS sevs
               FROM games g JOIN analysed_games a ON a.game_id = g.id WHERE g.username = ? ORDER BY g.end_time DESC LIMIT ?""",
            (self.username, self.n_games),
        ).fetchall()
        return index_page(games, self.username, served=True)

    def game(self, number: int) -> str | None:
        conn = self.conn()
        g = conn.execute(
            "SELECT * FROM games WHERE username = ? AND game_number = ?", (self.username, number)
        ).fetchone()
        if g is None or conn.execute("SELECT 1 FROM analysed_games WHERE game_id = ?", (g["id"],)).fetchone() is None:
            return None
        return game_page(conn, g, served=True)

    def puzzles(self, tag: str | None) -> str:
        return puzzle_page(self.conn(), self.username, tag)

    def puzzle_result(self, payload: dict) -> dict:
        conn = self.conn()
        tag = str(payload["tag"])
        with self.lock:
            record_attempt(
                conn,
                self.username,
                str(payload["puzzle_id"]),
                tag,
                solved=bool(payload.get("solved")),
                first_try=bool(payload.get("first_try")),
            )
            rebuild_schedule(conn, self.username)
        card = load_card(conn, self.username, tag)
        return {"ok": True, "due": card.due.strftime("%Y-%m-%d") if card and card.due else None}

    def answer(self, payload: dict) -> dict:
        conn = self.conn()
        g = conn.execute(
            "SELECT id FROM games WHERE username = ? AND game_number = ?", (self.username, int(payload["game_number"]))
        ).fetchone()
        if g is None:
            raise ValueError("partie inconnue")
        a = Answer(
            self.username,
            g["id"],
            int(payload["ply"]),
            str(payload["san"]),
            payload.get("plan"),
            payload.get("confidence"),
            str(payload["verdict"]),
            str(payload.get("kind", "answer")),
        )
        with self.lock:
            event_id = record_answer(conn, a)
            files = sync_markdown(conn, self.username, g["id"], self.memory_root)
        return {"ok": True, "event_id": event_id, "files": [str(f) for f in files]}


MANIFEST = """{"name": "ChessCoach", "short_name": "ChessCoach", "start_url": "/", "display": "standalone",
"background_color": "#141412", "theme_color": "#141412", "lang": "fr",
"icons": [{"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any"}]}"""
SERVICE_WORKER = "self.addEventListener('fetch', () => {});"  # requis pour « Ajouter à l'écran d'accueil »
ICON = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="12" fill="#769656"/>'
    '<rect x="8" y="8" width="24" height="24" fill="#eeeed2"/><rect x="32" y="32" width="24" height="24" fill="#eeeed2"/>'
    '<text x="32" y="44" font-size="30" text-anchor="middle" fill="#1b1b1b">♞</text></svg>'
)


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: str, ctype: str = "text/html; charset=utf-8") -> None:
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            if self.path in ("/", "/index.html"):
                return self._send(200, app.index())
            if self.path in ("/progress", "/progress.html"):
                return self._send(200, progress_page(app.conn(), app.username))
            if self.path == "/puzzle" or self.path.startswith("/puzzle/"):
                tag = self.path[8:] or None
                return self._send(200, app.puzzles(tag))
            if self.path == "/manifest.webmanifest":
                return self._send(200, MANIFEST, "application/manifest+json")
            if self.path == "/sw.js":
                return self._send(200, SERVICE_WORKER, "application/javascript")
            if self.path == "/icon.svg":
                return self._send(200, ICON, "image/svg+xml")
            if self.path == "/api/ping":
                return self._send(200, '{"ok": true}', "application/json")
            if self.path.startswith("/game/"):
                try:
                    number = int(self.path[6:].split(".")[0])
                except ValueError:
                    return self._send(404, "partie invalide")
                page = app.game(number)
                return self._send(200, page) if page else self._send(404, "partie non analysée")
            self._send(404, "introuvable")

        def do_POST(self) -> None:
            if self.path not in ("/api/answer", "/api/puzzle"):
                return self._send(404, "introuvable")
            length = int(self.headers.get("Content-Length", "0"))
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
                result = app.answer(payload) if self.path == "/api/answer" else app.puzzle_result(payload)
            except (ValueError, KeyError, TypeError) as exc:
                return self._send(400, json.dumps({"ok": False, "error": str(exc)}), "application/json")
            self._send(200, json.dumps(result), "application/json")

        def log_message(self, fmt, *args):  # silence
            pass

    return Handler


def serve(app: App, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), make_handler(app))
    return server


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--username", required=True)
    p.add_argument("--db", default="data/chesscoach.sqlite")
    p.add_argument("--memory", default="memory/learner")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--games", type=int, default=10)
    a = p.parse_args(argv)
    app = App(a.db, a.username, Path(a.memory), a.games)
    server = serve(app, port=a.port)
    print(f"ChessCoach : http://127.0.0.1:{a.port}/  (Ctrl+C pour arrêter) — mémoire : {a.memory}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
