"""Agrégations pures sur la base (aucun LLM). Chaque fonction retourne des données simples,
``render.py`` les met en forme."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field

import chess

from chesscoach.engine.analyse import load_evals
from chesscoach.engine.analysis import BLUNDER_CP, move_losses
from chesscoach.taxonomy.classify import OPENING_MAX_PLY, is_endgame
from chesscoach.taxonomy.tags import Tag

PHASES = ("opening", "middlegame", "endgame")
CLOCK_BUCKETS: tuple[tuple[str, float, float], ...] = (
    ("> 5 min", 300, float("inf")),
    ("2 à 5 min", 120, 300),
    ("1 à 2 min", 60, 120),
    ("< 1 min", 0, 60),
)


@dataclass
class Overview:
    games: int = 0
    wins: int = 0
    losses: int = 0
    draws: int = 0
    elo_min: int | None = None
    elo_max: int | None = None
    elo_last: int | None = None
    first_game: str | None = None
    last_game: str | None = None

    @property
    def score_pct(self) -> float:
        return 100 * (self.wins + 0.5 * self.draws) / self.games if self.games else 0.0


@dataclass
class PhaseStats:
    moves: int = 0
    total_loss: int = 0
    blunders: int = 0

    @property
    def avg_loss(self) -> float:
        return self.total_loss / self.moves if self.moves else 0.0

    @property
    def blunders_per_100(self) -> float:
        return 100 * self.blunders / self.moves if self.moves else 0.0


@dataclass
class Example:
    game_id: str
    played_at: str | None
    ply: int
    san: str
    best_move_san: str
    loss: int
    fen: str
    phase: str


@dataclass
class TagStats:
    count: int = 0
    total_loss: int = 0
    by_phase: dict[str, int] = field(default_factory=lambda: dict.fromkeys(PHASES, 0))
    examples: list[Example] = field(default_factory=list)


@dataclass
class OpeningStats:
    eco: str
    color: str
    games: int = 0
    wins: int = 0
    draws: int = 0
    opening_loss: int = 0
    opening_moves: int = 0

    @property
    def score_pct(self) -> float:
        return 100 * (self.wins + 0.5 * self.draws) / self.games if self.games else 0.0

    @property
    def avg_opening_loss(self) -> float:
        return self.opening_loss / self.opening_moves if self.opening_moves else 0.0


@dataclass
class Report:
    username: str
    filters: str
    overview: Overview
    phases: dict[str, PhaseStats]
    tags: dict[str, TagStats]
    time_pressure_moments: int
    total_moments: int
    clock: dict[str, PhaseStats]
    openings: list[OpeningStats]
    monthly: list[tuple[str, int, float]]  # (mois, parties, perte moyenne/coup)


def _game_filter(time_class: str | None, time_control: str | None) -> tuple[str, list[str]]:
    sql, params = "", []
    if time_class:
        sql += " AND g.time_class = ?"
        params.append(time_class)
    if time_control:
        sql += " AND g.time_control = ?"
        params.append(time_control)
    return sql, params


def phase_of(board: chess.Board) -> str:
    if board.ply() < OPENING_MAX_PLY:
        return "opening"
    return "endgame" if is_endgame(board) else "middlegame"


def build_report(
    conn: sqlite3.Connection,
    username: str,
    *,
    time_class: str | None = None,
    time_control: str | None = None,
    examples_per_tag: int = 3,
) -> Report:
    where, params = _game_filter(time_class, time_control)
    games = conn.execute(
        f"""SELECT g.* FROM games g JOIN analysed_games a ON a.game_id = g.id
            WHERE g.username = ? AND g.rules = 'chess'{where} ORDER BY g.end_time""",
        [username, *params],
    ).fetchall()

    overview = Overview(games=len(games))
    phases = {p: PhaseStats() for p in PHASES}
    clock = {label: PhaseStats() for label, _, _ in CLOCK_BUCKETS}
    openings: dict[tuple[str, str], OpeningStats] = {}
    monthly_acc: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])  # parties, coups, perte

    for g in games:
        overview.wins += g["user_result"] == "win"
        overview.losses += g["user_result"] == "loss"
        overview.draws += g["user_result"] == "draw"
        elo = g["white_elo"] if g["user_color"] == "white" else g["black_elo"]
        if elo:
            overview.elo_min = min(overview.elo_min or elo, elo)
            overview.elo_max = max(overview.elo_max or elo, elo)
            overview.elo_last = elo
        overview.first_game = overview.first_game or g["played_at"]
        overview.last_game = g["played_at"]

        evals = load_evals(conn, g["id"])
        rows = conn.execute(
            "SELECT san, clock_seconds FROM moves WHERE game_id = ? ORDER BY ply", (g["id"],)
        ).fetchall()
        if len(evals) != len(rows) + 1:
            continue
        losses = move_losses(evals, [r["san"] for r in rows])
        eco = _eco_name(g["eco"])
        op = openings.setdefault((eco, g["user_color"]), OpeningStats(eco=eco, color=g["user_color"]))
        op.games += 1
        op.wins += g["user_result"] == "win"
        op.draws += g["user_result"] == "draw"
        month = (g["played_at"] or "")[:7]
        monthly_acc[month][0] += 1

        for m in losses:
            if m.color != g["user_color"]:
                continue
            ph = phase_of(chess.Board(m.fen))
            _add(phases[ph], m.loss)
            monthly_acc[month][1] += 1
            monthly_acc[month][2] += m.loss
            if ph == "opening":
                op.opening_loss += m.loss
                op.opening_moves += 1
            secs = rows[m.ply - 1]["clock_seconds"]
            if secs is not None:
                for label, lo, hi in CLOCK_BUCKETS:
                    if lo <= secs < hi:
                        _add(clock[label], m.loss)
                        break

    tags = {t.value: TagStats() for t in Tag}
    moments = conn.execute(
        f"""SELECT cm.*, g.played_at FROM critical_moments cm JOIN games g ON g.id = cm.game_id
            WHERE g.username = ? AND g.rules = 'chess'{where} ORDER BY cm.loss DESC""",
        [username, *params],
    ).fetchall()
    time_pressure = 0
    for r in moments:
        ts = tags[r["primary_tag"]]
        ts.count += 1
        ts.total_loss += r["loss"]
        ts.by_phase[r["phase"]] += 1
        if Tag.TIME_PRESSURE.value in r["tags"].split(",")[1:]:
            time_pressure += 1
        if len(ts.examples) < examples_per_tag:
            board = chess.Board(r["fen_before"])
            best = chess.Move.from_uci(r["best_move"]) if r["best_move"] else None
            ts.examples.append(
                Example(
                    game_id=r["game_id"],
                    played_at=r["played_at"],
                    ply=r["ply"],
                    san=r["san"],
                    best_move_san=board.san(best) if best and best in board.legal_moves else (r["best_move"] or "?"),
                    loss=r["loss"],
                    fen=r["fen_before"],
                    phase=r["phase"],
                )
            )

    filters = " ".join(x for x in (time_class, time_control and f"({time_control})") if x) or "toutes cadences"
    return Report(
        username=username,
        filters=filters,
        overview=overview,
        phases=phases,
        tags=tags,
        time_pressure_moments=time_pressure,
        total_moments=len(moments),
        clock=clock,
        openings=sorted(openings.values(), key=lambda o: -o.games),
        monthly=[(m, v[0], v[2] / v[1] if v[1] else 0.0) for m, v in sorted(monthly_acc.items())],
    )


def _add(stats: PhaseStats, loss: int) -> None:
    stats.moves += 1
    stats.total_loss += loss
    stats.blunders += loss >= BLUNDER_CP


def _eco_name(eco: str | None) -> str:
    """Chess.com met l'URL de l'ouverture dans le champ eco : on garde le nom lisible."""
    if not eco:
        return "inconnue"
    name = eco.rstrip("/").split("/")[-1]
    return name.replace("-", " ")
