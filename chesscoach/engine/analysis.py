"""Éval par coup et moments critiques — calcul pur, testable sans Stockfish.

Conventions (D-005) :
- ``PositionEval`` = position *avant* le coup ``ply`` ; la liste d'une partie a
  ``ply_count + 1`` entrées (la dernière est la position finale).
- Scores stockés du point de vue des blancs ; ``to_cp`` borne les mats à ±MATE_CP.
- La perte d'un coup = (éval avant − éval après) du point de vue du joueur qui
  joue, bornée à 0 (on ne récompense pas un coup « meilleur que le meilleur »).
"""

from __future__ import annotations

from dataclasses import dataclass

MATE_CP = 1000  # borne des mats, comme Lichess
INACCURACY_CP = 50
MISTAKE_CP = 100
CRITICAL_CP = 100  # seuil « moment critique » (D-005, validé à 100 cp)
BLUNDER_CP = 300


@dataclass(frozen=True)
class PositionEval:
    fen: str
    score_cp: int | None
    mate_in: int | None  # +n : blancs matent en n ; -n : noirs matent en n
    depth: int
    best_move: str | None
    best_pv: str
    terminal_winner: bool | None = None  # position finale : True = blancs ont maté

    def to_cp(self) -> int:
        """Score borné (point de vue blancs)."""
        if self.terminal_winner is not None:
            return MATE_CP if self.terminal_winner else -MATE_CP
        if self.mate_in is not None:
            return MATE_CP if self.mate_in > 0 else -MATE_CP
        assert self.score_cp is not None
        return max(-MATE_CP, min(MATE_CP, self.score_cp))


@dataclass(frozen=True)
class MoveLoss:
    ply: int
    color: str  # 'white' | 'black' : qui a joué
    san: str
    before_cp: int  # éval avant le coup, point de vue du joueur
    after_cp: int  # éval après le coup, point de vue du joueur
    loss: int  # >= 0
    best_move: str | None  # UCI du coup moteur dans la position avant
    fen: str  # position avant le coup

    @property
    def severity(self) -> str | None:
        if self.loss >= BLUNDER_CP:
            return "blunder"
        if self.loss >= MISTAKE_CP:
            return "mistake"
        if self.loss >= INACCURACY_CP:
            return "inaccuracy"
        return None


@dataclass(frozen=True)
class CriticalMoment:
    move: MoveLoss
    rank: int  # 1 = plus grosse perte de la partie


def move_losses(evals: list[PositionEval], sans: list[str]) -> list[MoveLoss]:
    """``evals`` a ``len(sans) + 1`` entrées. Retourne une perte par coup joué."""
    if len(evals) != len(sans) + 1:
        raise ValueError(f"{len(evals)} évals pour {len(sans)} coups : attendu len(coups) + 1")
    losses = []
    for i, san in enumerate(sans):
        ply = i + 1
        sign = 1 if ply % 2 == 1 else -1
        before = sign * evals[i].to_cp()
        after = sign * evals[i + 1].to_cp()
        losses.append(
            MoveLoss(
                ply=ply,
                color="white" if sign == 1 else "black",
                san=san,
                before_cp=before,
                after_cp=after,
                loss=max(0, before - after),
                best_move=evals[i].best_move,
                fen=evals[i].fen,
            )
        )
    return losses


def critical_moments(
    losses: list[MoveLoss], user_color: str, *, threshold: int = CRITICAL_CP, max_moments: int = 4
) -> list[CriticalMoment]:
    """Coups de l'utilisateur perdant >= threshold, triés par perte décroissante, au plus max_moments."""
    candidates = [m for m in losses if m.color == user_color and m.loss >= threshold]
    candidates.sort(key=lambda m: (-m.loss, m.ply))
    return [CriticalMoment(move=m, rank=i + 1) for i, m in enumerate(candidates[:max_moments])]
