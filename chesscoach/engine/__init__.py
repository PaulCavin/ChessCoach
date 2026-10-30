"""Oracle : wrapper Stockfish, évaluation par coup, moments critiques. Aucun LLM ici."""

from chesscoach.engine.analysis import (
    BLUNDER_CP,
    CRITICAL_CP,
    INACCURACY_CP,
    MATE_CP,
    MISTAKE_CP,
    CriticalMoment,
    MoveLoss,
    PositionEval,
    critical_moments,
    move_losses,
)
from chesscoach.engine.stockfish import Stockfish, default_binary

__all__ = [
    "BLUNDER_CP",
    "CRITICAL_CP",
    "INACCURACY_CP",
    "MATE_CP",
    "MISTAKE_CP",
    "CriticalMoment",
    "MoveLoss",
    "PositionEval",
    "Stockfish",
    "critical_moments",
    "default_binary",
    "move_losses",
]
