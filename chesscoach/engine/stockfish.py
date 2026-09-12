"""Wrapper minimal autour de Stockfish via python-chess (UCI)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import chess
import chess.engine

from chesscoach.engine.analysis import PositionEval

ENV_VAR = "CHESSCOACH_STOCKFISH"


def default_binary() -> str | None:
    """Binaire Stockfish : variable d'environnement, puis ./bin/, puis le PATH."""
    candidates = [os.environ.get(ENV_VAR), "bin/stockfish-bin", "bin/stockfish", shutil.which("stockfish")]
    for c in candidates:
        if c and Path(c).is_file():
            return str(c)
    return None


class Stockfish:
    """Utilisation : ``with Stockfish() as sf: sf.evaluate(board, depth=14)``."""

    def __init__(self, binary: str | None = None, *, threads: int = 1, hash_mb: int = 64):
        self.binary = binary or default_binary()
        if not self.binary:
            raise FileNotFoundError(f"Stockfish introuvable : définir {ENV_VAR} ou placer le binaire dans bin/.")
        self.threads, self.hash_mb = threads, hash_mb
        self._engine: chess.engine.SimpleEngine | None = None

    def __enter__(self) -> Stockfish:
        self._engine = chess.engine.SimpleEngine.popen_uci(self.binary)
        self._engine.configure({"Threads": self.threads, "Hash": self.hash_mb})
        return self

    def __exit__(self, *exc: object) -> None:
        if self._engine:
            self._engine.quit()
            self._engine = None

    @property
    def name(self) -> str:
        assert self._engine is not None
        return self._engine.id.get("name", "stockfish")

    def evaluate(self, board: chess.Board, depth: int) -> PositionEval:
        """Éval de la position (point de vue blancs) + meilleur coup. Positions terminales gérées."""
        assert self._engine is not None, "utiliser dans un bloc with"
        fen = board.fen()
        if board.is_game_over():
            outcome = board.outcome()
            if outcome is not None and outcome.winner is not None:
                return PositionEval(
                    fen=fen,
                    score_cp=None,
                    mate_in=None,
                    depth=depth,
                    best_move=None,
                    best_pv="",
                    terminal_winner=outcome.winner,
                )
            return PositionEval(fen=fen, score_cp=0, mate_in=None, depth=depth, best_move=None, best_pv="")
        info = self._engine.analyse(board, chess.engine.Limit(depth=depth))
        score = info["score"].white()
        pv = info.get("pv", [])
        return PositionEval(
            fen=fen,
            score_cp=score.score() if not score.is_mate() else None,
            mate_in=score.mate() if score.is_mate() else None,
            depth=info.get("depth", depth),
            best_move=pv[0].uci() if pv else None,
            best_pv=" ".join(m.uci() for m in pv),
        )
