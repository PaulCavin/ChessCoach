"""Téléchargement des parties Chess.com par mois vers SQLite.

API publique (sans clé) : https://www.chess.com/news/view/published-data-api
  GET /pub/player/{username}/games/archives  -> {"archives": [url, ...]}
  GET /pub/player/{username}/games/{YYYY}/{MM} -> {"games": [{...}, ...]}

Usage : ``python -m chesscoach.ingest.chesscom <username> [--db PATH] [--since YYYY-MM] [--until YYYY-MM]``
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Any

from chesscoach import __version__, db
from chesscoach.ingest.pgn import Game, parse_game

API_BASE = "https://api.chess.com/pub"
USER_AGENT = f"chesscoach/{__version__} (+https://github.com/PaulCavin/ChessCoach)"

FetchJson = Callable[[str], dict[str, Any]]


def fetch_json(url: str, *, retries: int = 3, backoff: float = 2.0) -> dict[str, Any]:
    """GET JSON avec User-Agent (obligatoire, sinon 403) et retries sur 429/5xx."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(backoff * 2**attempt)
                continue
            raise
    raise RuntimeError("unreachable")


def list_archives(username: str, fetch: FetchJson = fetch_json) -> list[tuple[int, int]]:
    """Retourne les (année, mois) disponibles, triés chronologiquement."""
    data = fetch(f"{API_BASE}/player/{username}/games/archives")
    months = []
    for url in data.get("archives", []):
        year, month = url.rstrip("/").split("/")[-2:]
        months.append((int(year), int(month)))
    return sorted(months)


def fetch_month(username: str, year: int, month: int, fetch: FetchJson = fetch_json) -> list[dict[str, Any]]:
    data = fetch(f"{API_BASE}/player/{username}/games/{year}/{month:02d}")
    return data.get("games", [])


def _user_result(game_json: dict[str, Any], color: str) -> str:
    """Traduit le champ ``result`` de Chess.com ('win', 'checkmated', 'agreed', ...)."""
    raw = game_json.get(color, {}).get("result")
    if raw == "win":
        return "win"
    if raw in {"agreed", "repetition", "stalemate", "insufficient", "50move", "timevsinsufficient"}:
        return "draw"
    if raw in {"checkmated", "resigned", "timeout", "abandoned", "lose"}:
        return "loss"
    return "unknown"


def game_row(username: str, game_json: dict[str, Any], game: Game) -> dict[str, Any]:
    white = game_json.get("white", {}).get("username") or game.headers.get("White", "")
    black = game_json.get("black", {}).get("username") or game.headers.get("Black", "")
    color = "white" if white.lower() == username.lower() else "black"
    end_time = game_json.get("end_time")
    played_at = datetime.fromtimestamp(end_time, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if end_time else None

    def elo(side: str) -> int | None:
        value = game_json.get(side, {}).get("rating") or game.headers.get(f"{side.title()}Elo")
        return int(value) if value not in (None, "", "?") else None

    return {
        "id": game_json.get("url") or game.headers.get("Link") or game.headers.get("Site"),
        "username": username,
        "user_color": color,
        "white": white,
        "black": black,
        "white_elo": elo("white"),
        "black_elo": elo("black"),
        "result": game.result,
        "user_result": _user_result(game_json, color),
        "termination": game.headers.get("Termination"),
        "time_control": game_json.get("time_control") or game.headers.get("TimeControl"),
        "time_class": game_json.get("time_class"),
        "rated": int(bool(game_json["rated"])) if "rated" in game_json else None,
        "rules": game_json.get("rules"),
        "eco": game_json.get("eco") or game.headers.get("ECO"),
        "eco_url": game.headers.get("ECOUrl"),
        "end_time": end_time,
        "played_at": played_at,
        "ply_count": game.ply_count,
        "pgn": game.pgn,
    }


def store_game(conn: sqlite3.Connection, username: str, game_json: dict[str, Any]) -> bool:
    """Insère une partie et ses coups. Retourne False si déjà présente (ou sans PGN)."""
    pgn = game_json.get("pgn")
    if not pgn:
        return False
    game = parse_game(pgn)
    row = game_row(username, game_json, game)
    if not row["id"]:
        return False
    if conn.execute("SELECT 1 FROM games WHERE id = ?", (row["id"],)).fetchone():
        return False
    columns = ", ".join(row)
    placeholders = ", ".join(f":{k}" for k in row)
    conn.execute(f"INSERT INTO games ({columns}) VALUES ({placeholders})", row)
    conn.executemany(
        "INSERT INTO moves (game_id, ply, move_number, color, san, clock_seconds) VALUES (?, ?, ?, ?, ?, ?)",
        [(row["id"], m.ply, m.move_number, m.color, m.san, m.clock_seconds) for m in game.moves],
    )
    return True


def ingest_month(conn: sqlite3.Connection, username: str, year: int, month: int, fetch: FetchJson = fetch_json) -> int:
    """Télécharge et stocke un mois ; retourne le nombre de nouvelles parties."""
    games = fetch_month(username, year, month, fetch)
    inserted = sum(store_game(conn, username, g) for g in games)
    conn.execute(
        "INSERT OR REPLACE INTO archive_months (username, year, month, game_count) VALUES (?, ?, ?, ?)",
        (username, year, month, len(games)),
    )
    conn.commit()
    return inserted


def _parse_ym(value: str | None) -> tuple[int, int] | None:
    if not value:
        return None
    year, month = value.split("-")
    return int(year), int(month)


def ingest(
    conn: sqlite3.Connection,
    username: str,
    *,
    since: str | None = None,
    until: str | None = None,
    refetch_current_month: bool = True,
    fetch: FetchJson = fetch_json,
    log: Callable[[str], None] = lambda _: None,
) -> int:
    """Ingère tous les mois d'archive non encore téléchargés. Retourne le total inséré."""
    lo, hi = _parse_ym(since), _parse_ym(until)
    now = datetime.now(tz=UTC)
    done = {
        (r["year"], r["month"])
        for r in conn.execute("SELECT year, month FROM archive_months WHERE username = ?", (username,))
    }
    total = 0
    for year, month in list_archives(username, fetch):
        if (lo and (year, month) < lo) or (hi and (year, month) > hi):
            continue
        is_current = (year, month) == (now.year, now.month)
        if (year, month) in done and not (is_current and refetch_current_month):
            continue
        n = ingest_month(conn, username, year, month, fetch)
        total += n
        log(f"{year}-{month:02d} : {n} nouvelle(s) partie(s)")
    return total


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Télécharge les parties Chess.com d'un joueur vers SQLite.")
    parser.add_argument("username")
    parser.add_argument("--db", default="data/chesscoach.sqlite", help="chemin de la base SQLite")
    parser.add_argument("--since", metavar="YYYY-MM", help="premier mois à ingérer")
    parser.add_argument("--until", metavar="YYYY-MM", help="dernier mois à ingérer")
    args = parser.parse_args(list(argv) if argv is not None else None)

    conn = db.connect(args.db)
    try:
        total = ingest(conn, args.username, since=args.since, until=args.until, fetch=fetch_json, log=print)
    except urllib.error.HTTPError as exc:
        print(f"Erreur HTTP {exc.code} sur {exc.url}", file=sys.stderr)
        return 1
    count = conn.execute("SELECT count(*) FROM games WHERE username = ?", (args.username,)).fetchone()[0]
    print(f"{total} partie(s) ajoutée(s) ; {count} partie(s) au total pour {args.username} dans {args.db}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
