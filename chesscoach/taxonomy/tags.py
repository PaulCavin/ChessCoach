"""Taxonomie d'erreurs — figée en phase 0 (docs/decisions.md, D-001).

Ajouter un tag = nouvelle décision documentée. Les valeurs sont stockées telles
quelles en SQLite et dans la mémoire d'apprenant, donc ne jamais les renommer.
"""

from __future__ import annotations

from enum import StrEnum


class Tag(StrEnum):
    HANGING_PIECE = "hanging_piece"
    MISSED_MATE = "missed_mate"
    IGNORED_THREAT = "ignored_threat"
    UNNECESSARY_EXCHANGE = "unnecessary_exchange"
    KING_SAFETY = "king_safety"
    PASSIVE_PIECE = "passive_piece"
    OPENING_PRINCIPLE = "opening_principle"
    ENDGAME_TECHNIQUE = "endgame_technique"
    CALCULATION_ERROR = "calculation_error"
    TIME_PRESSURE = "time_pressure"


TAGS: tuple[Tag, ...] = tuple(Tag)

# Correspondance vers les thèmes de la base de puzzles Lichess (colonne Themes).
# Un tag sans thème Lichess exploitable est servi par la position rejouée.
LICHESS_THEMES: dict[Tag, tuple[str, ...]] = {
    Tag.HANGING_PIECE: ("hangingPiece",),
    Tag.MISSED_MATE: ("mate", "mateIn1", "mateIn2", "mateIn3"),
    Tag.IGNORED_THREAT: ("defensiveMove",),
    Tag.UNNECESSARY_EXCHANGE: ("exchange",),
    Tag.KING_SAFETY: ("kingsideAttack", "queensideAttack", "exposedKing"),
    Tag.PASSIVE_PIECE: ("trappedPiece",),
    Tag.OPENING_PRINCIPLE: ("opening",),
    Tag.ENDGAME_TECHNIQUE: ("endgame", "pawnEndgame", "rookEndgame"),
    Tag.CALCULATION_ERROR: ("crushing", "advantage"),
    Tag.TIME_PRESSURE: (),
}
