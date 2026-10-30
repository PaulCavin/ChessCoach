"""Parseur PGN minimal et sans dépendance pour l'ingestion.

Il extrait les en-têtes, les coups en SAN et les horloges ``[%clk]``. Il ne
vérifie pas la légalité des coups : c'est le rôle de python-chess dans
``engine/`` (phase 1), qui recalcule les FEN à partir du PGN brut stocké.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_HEADER_RE = re.compile(r'^\[(\w+)\s+"((?:[^"\\]|\\.)*)"\]\s*$')
_CLK_RE = re.compile(r"\[%clk\s+(\d+):(\d{1,2}):(\d{1,2}(?:\.\d+)?)\]")
_TOKEN_RE = re.compile(
    r"""
    (?P<comment>\{[^}]*\})
  | (?P<open>\()
  | (?P<close>\))
  | (?P<result>1-0|0-1|1/2-1/2|\*)(?=\s|$)
  | (?P<movenum>\d+\.(?:\.\.)?)
  | (?P<nag>\$\d+)
  | (?P<san>[^\s{}()]+)
    """,
    re.VERBOSE,
)
RESULTS = {"1-0", "0-1", "1/2-1/2", "*"}


@dataclass
class Move:
    ply: int
    san: str
    clock_seconds: float | None = None

    @property
    def move_number(self) -> int:
        return (self.ply + 1) // 2

    @property
    def color(self) -> str:
        return "white" if self.ply % 2 == 1 else "black"


@dataclass
class Game:
    headers: dict[str, str] = field(default_factory=dict)
    moves: list[Move] = field(default_factory=list)
    result: str = "*"
    pgn: str = ""

    @property
    def ply_count(self) -> int:
        return len(self.moves)


def parse_clock(comment: str) -> float | None:
    """``"[%clk 0:09:58.5]"`` -> 598.5 ; None si pas d'horloge."""
    m = _CLK_RE.search(comment)
    if not m:
        return None
    hours, minutes, seconds = m.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def split_games(text: str) -> list[str]:
    """Découpe un fichier PGN multi-parties en blocs (une partie = en-têtes + coups)."""
    blocks: list[str] = []
    current: list[str] = []
    in_moves = False
    for line in text.splitlines():
        is_header = line.startswith("[") and _HEADER_RE.match(line) is not None
        if is_header and in_moves:
            blocks.append("\n".join(current).strip())
            current, in_moves = [], False
        elif not is_header and line.strip():
            in_moves = True
        current.append(line)
    tail = "\n".join(current).strip()
    if tail:
        blocks.append(tail)
    return blocks


def parse_game(text: str) -> Game:
    """Parse une seule partie. Les variantes ``( ... )`` sont ignorées."""
    game = Game(pgn=text.strip())
    movetext_lines: list[str] = []
    for line in text.splitlines():
        m = _HEADER_RE.match(line)
        if m and not movetext_lines:
            game.headers[m.group(1)] = m.group(2).replace('\\"', '"')
        else:
            movetext_lines.append(line)

    depth = 0
    ply = 0
    for tok in _TOKEN_RE.finditer("\n".join(movetext_lines)):
        kind = tok.lastgroup
        if kind == "open":
            depth += 1
        elif kind == "close":
            depth = max(0, depth - 1)
        elif depth:
            continue
        elif kind == "comment":
            if game.moves:
                clock = parse_clock(tok.group())
                if clock is not None:
                    game.moves[-1].clock_seconds = clock
        elif kind == "result":
            game.result = tok.group()
            break
        elif kind == "san":
            ply += 1
            game.moves.append(Move(ply=ply, san=tok.group()))

    if game.result == "*" and game.headers.get("Result") in RESULTS:
        game.result = game.headers["Result"]
    return game


def parse_games(text: str) -> list[Game]:
    return [parse_game(block) for block in split_games(text)]
