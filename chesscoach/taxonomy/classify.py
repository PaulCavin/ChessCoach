"""Classification déterministe d'un moment critique dans la taxonomie (D-006).

Entrée : la position avant le coup, le coup joué, les évals moteur (avant, après,
et meilleure réponse adverse) et l'horloge. Sortie : un tag principal + un
éventuel tag secondaire ``time_pressure``. Aucun LLM, aucune heuristique
floue : chaque règle est un calcul python-chess ou une comparaison d'évals.

Ordre de priorité (la première règle qui s'applique gagne) :
missed_mate > hanging_piece > ignored_threat > unnecessary_exchange >
king_safety > endgame_technique > opening_principle > passive_piece >
calculation_error.
"""

from __future__ import annotations

from dataclasses import dataclass

import chess

from chesscoach.engine.analysis import MATE_CP, PositionEval
from chesscoach.taxonomy.tags import Tag

PIECE_VALUE = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}
OPENING_MAX_PLY = 20  # 10 coups
TIME_PRESSURE_SECONDS = 60
ENDGAME_MAX_MATERIAL = 13  # matériel hors pions et roi, par camp (ex. D+B ou T+T+B)


@dataclass(frozen=True)
class MomentContext:
    board_before: chess.Board  # position avant le coup de l'utilisateur
    played: chess.Move
    eval_before: PositionEval  # position avant le coup
    eval_after: PositionEval  # position après le coup (meilleure réponse adverse = best_move)
    clock_seconds: float | None  # horloge de l'utilisateur après le coup


@dataclass(frozen=True)
class Classification:
    primary: Tag
    secondary: tuple[Tag, ...] = ()

    @property
    def tags(self) -> tuple[Tag, ...]:
        return (self.primary, *self.secondary)


def material(board: chess.Board, color: chess.Color) -> int:
    return sum(
        PIECE_VALUE[p] * len(board.pieces(p, color)) for p in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN)
    )


def is_endgame(board: chess.Board) -> bool:
    return max(material(board, chess.WHITE), material(board, chess.BLACK)) <= ENDGAME_MAX_MATERIAL


def _reply(ctx: MomentContext) -> chess.Move | None:
    """Meilleure réponse adverse (UCI stockée) sur la position après le coup."""
    if not ctx.eval_after.best_move:
        return None
    move = chess.Move.from_uci(ctx.eval_after.best_move)
    board = ctx.board_before.copy()
    board.push(ctx.played)
    return move if move in board.legal_moves else None


def _wins_material(board: chess.Board, capture: chess.Move) -> bool:
    """La capture gagne du matériel : pièce prise non défendue, ou prise par une pièce de moindre valeur."""
    victim = board.piece_at(capture.to_square)
    attacker = board.piece_at(capture.from_square)
    if victim is None or attacker is None:
        return False
    if PIECE_VALUE[attacker.piece_type] < PIECE_VALUE[victim.piece_type]:
        return True
    return not board.is_attacked_by(victim.color, capture.to_square)


def rule_missed_mate(ctx: MomentContext) -> bool:
    """Mat forcé disponible avant le coup, plus après."""
    us = ctx.board_before.turn
    before = ctx.eval_before.mate_in
    after = ctx.eval_after
    had_mate = before is not None and (before > 0) == us
    still_mate = after.mate_in is not None and (after.mate_in > 0) == us
    return had_mate and not still_mate and after.terminal_winner is None


def rule_hanging_piece(ctx: MomentContext) -> bool:
    """La meilleure réponse adverse capture gratuitement une pièce (hors pion) rendue prenable par le coup."""
    reply = _reply(ctx)
    if reply is None:
        return False
    after = ctx.board_before.copy()
    after.push(ctx.played)
    victim = after.piece_at(reply.to_square)
    if victim is None or victim.piece_type == chess.PAWN or not after.is_capture(reply):
        return False
    if reply.to_square == ctx.played.to_square and ctx.board_before.is_capture(ctx.played):
        return False  # reprise après une capture : c'est un échange, pas une pièce pendue
    if not _wins_material(after, reply):
        return False
    # La même capture n'était pas déjà disponible avant : c'est le coup qui pend la pièce.
    return not _same_capture_available_before(ctx, reply)


def _same_capture_available_before(ctx: MomentContext, reply: chess.Move) -> bool:
    before = ctx.board_before.copy()
    before.turn = not before.turn  # coup nul : l'adversaire joue tout de suite
    before.ep_square = None
    try:
        target = ctx.board_before.piece_at(reply.to_square)
        if target is None:
            return False
        for m in before.legal_moves:
            if m.to_square == reply.to_square and before.is_capture(m) and _wins_material(before, m):
                return True
    except (ValueError, AssertionError):
        return False
    return False


def rule_ignored_threat(ctx: MomentContext) -> bool:
    """Une capture gagnante adverse existait déjà avant le coup ; le coup ne l'a pas parée."""
    reply = _reply(ctx)
    if reply is None:
        return False
    after = ctx.board_before.copy()
    after.push(ctx.played)
    if not after.is_capture(reply) or not _wins_material(after, reply):
        return False
    return _same_capture_available_before(ctx, reply)


def rule_unnecessary_exchange(ctx: MomentContext) -> bool:
    """Le coup est une capture, l'adversaire reprend sur la même case, sans gain de matériel."""
    if not ctx.board_before.is_capture(ctx.played):
        return False
    reply = _reply(ctx)
    if reply is None or reply.to_square != ctx.played.to_square:
        return False
    victim = ctx.board_before.piece_at(ctx.played.to_square)
    attacker = ctx.board_before.piece_at(ctx.played.from_square)
    if victim is None or attacker is None:
        return False
    return PIECE_VALUE[victim.piece_type] <= PIECE_VALUE[attacker.piece_type]


def rule_king_safety(ctx: MomentContext) -> bool:
    """La meilleure réponse adverse est un échec sans capture (attaque sur le roi, pas une tactique de
    matériel), ou le coup avance un pion du bouclier (colonne du roi ± 1) alors que le roi ne peut plus roquer."""
    reply = _reply(ctx)
    after = ctx.board_before.copy()
    after.push(ctx.played)
    if reply is not None and after.gives_check(reply) and not after.is_capture(reply):
        return True
    board = ctx.board_before
    piece = board.piece_at(ctx.played.from_square)
    king = board.king(board.turn)
    if piece is None or piece.piece_type != chess.PAWN or king is None or board.has_castling_rights(board.turn):
        return False
    return abs(chess.square_file(ctx.played.from_square) - chess.square_file(king)) <= 1 and chess.square_rank(
        king
    ) in (0, 7)


def rule_endgame(ctx: MomentContext) -> bool:
    return is_endgame(ctx.board_before)


def rule_opening_principle(ctx: MomentContext) -> bool:
    """Dans les 10 premiers coups : le moteur développe (pièce de la rangée initiale ou roque), pas l'utilisateur."""
    if ctx.board_before.ply() >= OPENING_MAX_PLY or not ctx.eval_before.best_move:
        return False
    best = chess.Move.from_uci(ctx.eval_before.best_move)
    return _is_developing(ctx.board_before, best) and not _is_developing(ctx.board_before, ctx.played)


def _is_developing(board: chess.Board, move: chess.Move) -> bool:
    if board.is_castling(move):
        return True
    piece = board.piece_at(move.from_square)
    if piece is None or piece.piece_type in (chess.PAWN, chess.KING, chess.QUEEN):
        return False
    home_rank = 0 if piece.color == chess.WHITE else 7
    return chess.square_rank(move.from_square) == home_rank


def rule_passive_piece(ctx: MomentContext) -> bool:
    """Aucune tactique en jeu (ni capture ni échec dans le coup joué, le meilleur coup ou la réponse) :
    le moteur déplace une pièce vers l'avant, l'utilisateur joue un pion ou recule une pièce."""
    if not ctx.eval_before.best_move:
        return False
    best = chess.Move.from_uci(ctx.eval_before.best_move)
    board = ctx.board_before
    reply = _reply(ctx)
    after = board.copy()
    after.push(ctx.played)
    tactical = (
        board.is_capture(best)
        or board.gives_check(best)
        or board.is_capture(ctx.played)
        or board.gives_check(ctx.played)
        or (reply is not None and (after.is_capture(reply) or after.gives_check(reply)))
    )
    if tactical:
        return False
    forward = 1 if board.turn == chess.WHITE else -1
    best_piece = board.piece_at(best.from_square)
    played_piece = board.piece_at(ctx.played.from_square)
    if best_piece is None or played_piece is None or best_piece.piece_type == chess.PAWN:
        return False
    best_advances = (chess.square_rank(best.to_square) - chess.square_rank(best.from_square)) * forward > 0
    played_retreats = (
        chess.square_rank(ctx.played.to_square) - chess.square_rank(ctx.played.from_square)
    ) * forward < 0
    return best_advances and (played_piece.piece_type == chess.PAWN or played_retreats)


RULES: tuple[tuple[Tag, object], ...] = (
    (Tag.MISSED_MATE, rule_missed_mate),
    (Tag.HANGING_PIECE, rule_hanging_piece),
    (Tag.IGNORED_THREAT, rule_ignored_threat),
    (Tag.UNNECESSARY_EXCHANGE, rule_unnecessary_exchange),
    (Tag.KING_SAFETY, rule_king_safety),
    (Tag.ENDGAME_TECHNIQUE, rule_endgame),
    (Tag.OPENING_PRINCIPLE, rule_opening_principle),
    (Tag.PASSIVE_PIECE, rule_passive_piece),
)


def classify(ctx: MomentContext) -> Classification:
    primary = Tag.CALCULATION_ERROR
    for tag, rule in RULES:
        if rule(ctx):
            primary = tag
            break
    secondary: tuple[Tag, ...] = ()
    if ctx.clock_seconds is not None and ctx.clock_seconds < TIME_PRESSURE_SECONDS:
        secondary = (Tag.TIME_PRESSURE,)
    return Classification(primary=primary, secondary=secondary)


def mate_score_for(color: chess.Color) -> int:
    return MATE_CP if color == chess.WHITE else -MATE_CP
