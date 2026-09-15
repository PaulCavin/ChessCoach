"""Faits vérifiables sur un moment critique, calculés par python-chess + evals. Seule source du LLM."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

import chess

from chesscoach.engine.analyse import load_evals


@dataclass
class Fact:
    id: str
    text: str


@dataclass
class MomentFacts:
    game_number: int
    ply: int
    user_color: str
    fen_before: str
    played_san: str
    best_san: str
    facts: list[Fact] = field(default_factory=list)
    best_line_san: str = ""
    played_line_san: str = ""

    def as_prompt_text(self) -> str:
        return "\n".join(f"[{f.id}] {f.text}" for f in self.facts)


def _cp_text(cp: int | None, mate: int | None, pov_white: bool) -> str:
    if mate is not None:
        who = "les blancs" if mate > 0 else "les noirs"
        return f"mat en {abs(mate)} pour {who}"
    assert cp is not None
    value = cp if pov_white else -cp
    return f"{value / 100:+.2f} pour toi"


def _line_san(board: chess.Board, uci_line: str, max_plies: int = 6) -> str:
    b = board.copy()
    out = []
    for uci in uci_line.split()[:max_plies]:
        m = chess.Move.from_uci(uci)
        if m not in b.legal_moves:
            break
        prefix = f"{b.fullmove_number}." if b.turn == chess.WHITE else (f"{b.fullmove_number}..." if not out else "")
        out.append(f"{prefix}{b.san(m)}")
        b.push(m)
    return " ".join(out)


def build_facts(conn: sqlite3.Connection, game_id: int, ply: int) -> MomentFacts:
    g = conn.execute("SELECT game_number, user_color FROM games WHERE id = ?", (game_id,)).fetchone()
    cm = conn.execute("SELECT * FROM critical_moments WHERE game_id = ? AND ply = ?", (game_id, ply)).fetchone()
    evals = load_evals(conn, game_id)
    before, after = evals[ply - 1], evals[ply]
    board = chess.Board(before.fen)
    pov = g["user_color"] == "white"
    played = board.parse_san(cm["san"])
    best = chess.Move.from_uci(before.best_move)
    mf = MomentFacts(g["game_number"], ply, g["user_color"], before.fen, cm["san"], board.san(best))
    facts = mf.facts
    facts.append(Fact("eval_before", f"Éval avant ton coup : {_cp_text(before.score_cp, before.mate_in, pov)}."))
    facts.append(
        Fact("eval_after", f"Éval après ton coup {cm['san']} : {_cp_text(after.score_cp, after.mate_in, pov)}.")
    )
    facts.append(Fact("best_move", f"Meilleur coup selon Stockfish : {board.san(best)}."))
    mf.best_line_san = _line_san(board, before.best_pv)
    facts.append(Fact("best_line", f"Ligne après le meilleur coup : {mf.best_line_san}."))
    b2 = board.copy()
    b2.push(played)
    mf.played_line_san = _line_san(b2, after.best_pv)
    if mf.played_line_san:
        facts.append(Fact("played_line", f"Meilleure réponse adverse après {cm['san']} : {mf.played_line_san}."))
    # Faits tactiques python-chess
    if board.is_capture(played):
        facts.append(Fact("played_is_capture", f"{cm['san']} est une capture."))
    if board.is_capture(best):
        facts.append(Fact("best_is_capture", f"{board.san(best)} est une capture."))
    if board.gives_check(played):
        facts.append(Fact("played_gives_check", f"{cm['san']} donne échec."))
    if board.gives_check(best):
        facts.append(Fact("best_gives_check", f"{board.san(best)} donne échec."))
    reply = chess.Move.from_uci(after.best_move) if after.best_move else None
    if reply and reply in b2.legal_moves:
        rs = b2.san(reply)
        if b2.is_capture(reply):
            victim = b2.piece_at(reply.to_square)
            name = chess.piece_name(victim.piece_type) if victim else "pièce"
            facts.append(
                Fact(
                    "reply_captures",
                    f"Après {cm['san']}, l'adversaire peut jouer {rs} et prendre {FR[name]} en {chess.square_name(reply.to_square)}.",
                )
            )
        if b2.gives_check(reply):
            facts.append(Fact("reply_gives_check", f"Après {cm['san']}, {rs} donne échec."))
    # Pièces de l'utilisateur non défendues et attaquées après le coup
    us = chess.WHITE if pov else chess.BLACK
    hanging = []
    for sq in chess.SQUARES:
        p = b2.piece_at(sq)
        if p and p.color == us and p.piece_type != chess.KING:
            if b2.is_attacked_by(not us, sq) and not b2.is_attacked_by(us, sq):
                hanging.append(f"{FR[chess.piece_name(p.piece_type)]} en {chess.square_name(sq)}")
    if hanging:
        facts.append(Fact("hanging_after", f"Après {cm['san']}, non défendu(e) et attaqué(e) : {', '.join(hanging)}."))
    if cm["clock_seconds"] is not None:
        facts.append(Fact("clock", f"Il te restait {int(cm['clock_seconds'])} s après ce coup."))
    facts.append(Fact("tag", f"Type d'erreur détecté : {cm['primary_tag']}."))
    return mf


FR = {
    "pawn": "le pion",
    "knight": "le cavalier",
    "bishop": "le fou",
    "rook": "la tour",
    "queen": "la dame",
    "king": "le roi",
}
