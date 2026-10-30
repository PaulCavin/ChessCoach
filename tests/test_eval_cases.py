"""Rejoue les vérifications programmatiques des cas d'évaluation (D-008). Aucun LLM."""

from __future__ import annotations

import json
from pathlib import Path

import chess
import pytest

CASES = sorted((Path(__file__).parent.parent / "chesscoach/eval/cases").glob("*.json"))


def run_check(check: str, case: dict) -> str:
    """Retourne 'accept' si l'affirmation est couverte par l'oracle, 'reject' sinon."""
    board = chess.Board(case["fen_before"])
    eng = case["engine"]
    if check == "style_judgement":
        return "reject"
    if check.startswith("score_before_cp =="):
        return "accept" if eng["score_before_cp"] == int(check.split("==")[1]) else "reject"
    if check.startswith("after_played_mate_in =="):
        return "accept" if eng["after_played_mate_in"] == int(check.split("==")[1]) else "reject"
    if check.startswith("best_move =="):
        return "accept" if eng["best_move"] == check.split("==")[1].strip() else "reject"
    if check.startswith("attacks:"):
        src, dst = check.split(":")[1].split("->")
        return "accept" if chess.parse_square(dst) in board.attacks(chess.parse_square(src)) else "reject"
    if check.startswith("gives_check:"):
        return "accept" if board.gives_check(chess.Move.from_uci(check.split(":")[1])) else "reject"
    if check.startswith("opponent_can_capture:"):
        square, _, move = check.split(":")[1].partition(" after ")
        board.push(chess.Move.from_uci(move.strip()))
        target = chess.parse_square(square.strip())
        return "accept" if any(m.to_square == target for m in board.legal_moves) else "reject"
    raise ValueError(f"vérification inconnue : {check}")


@pytest.mark.parametrize("path", CASES, ids=[p.stem for p in CASES])
def test_eval_case_claims(path):
    case = json.loads(path.read_text(encoding="utf-8"))
    board = chess.Board(case["fen_before"])
    assert board.parse_san(case["played"]) in board.legal_moves
    assert chess.Move.from_uci(case["engine"]["best_move"]) in board.legal_moves
    for claim in case["claims"]:
        assert run_check(claim["check"], case) == claim["expected"], claim["text"]
