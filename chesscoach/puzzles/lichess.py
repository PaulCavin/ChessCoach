"""Import filtré de la base de puzzles Lichess (CC0) vers SQLite (D-014).

Le fichier officiel ``lichess_db_puzzle.csv.zst`` fait ~900 Mo décompressé ; on n'en garde que les
lignes dont un thème correspond à un tag de notre taxonomie **et** dont la cote est dans la plage de
l'apprenant, ce qui ramène la table à quelques dizaines de Mo.

``python -m chesscoach.puzzles.lichess --csv lichess_db_puzzle.csv --min-rating 600 --max-rating 1300``
La source peut être un CSV décompressé, un fichier .zst, l'URL officielle (téléchargement en flux,
interrompu dès que les quotas sont atteints) ou stdin (``--csv -``). Les .zst demandent le module
``zstandard``.
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path

from chesscoach import db
from chesscoach.taxonomy.tags import LICHESS_THEMES, Tag

HEADER = (
    "PuzzleId",
    "FEN",
    "Moves",
    "Rating",
    "RatingDeviation",
    "Popularity",
    "NbPlays",
    "Themes",
    "GameUrl",
    "OpeningTags",
)
THEME_TO_TAGS: dict[str, list[str]] = {}
for _tag, _themes in LICHESS_THEMES.items():
    for _t in _themes:
        THEME_TO_TAGS.setdefault(_t, []).append(_tag.value)


def tags_for(themes: str) -> list[str]:
    """Tags ChessCoach correspondant aux thèmes Lichess d'une ligne (ordre de la taxonomie)."""
    found = {t for theme in themes.split() for t in THEME_TO_TAGS.get(theme, [])}
    return [t.value for t in Tag if t.value in found]


LICHESS_URL = "https://database.lichess.org/lichess_db_puzzle.csv.zst"


def open_csv(path: str) -> Iterator[str]:
    """Lignes du CSV, quelle que soit la source (fichier, .zst, URL, stdin)."""
    if path == "-":
        yield from sys.stdin
        return
    if path.startswith(("http://", "https://")):
        import urllib.request

        with urllib.request.urlopen(path, timeout=60) as resp:
            yield from _zst_lines(resp)
        return
    p = Path(path)
    if p.suffix == ".zst":
        with p.open("rb") as fh:
            yield from _zst_lines(fh)
        return
    with p.open(encoding="utf-8") as fh:
        yield from fh


def _zst_lines(binary) -> Iterator[str]:  # pragma: no cover - dépend d'un fichier/flux .zst
    import io

    try:
        import zstandard
    except ImportError as exc:
        raise RuntimeError(
            "source .zst : installer zstandard (pip install zstandard) ou décompresser avec unzstd"
        ) from exc
    with zstandard.ZstdDecompressor().stream_reader(binary) as reader:
        yield from io.TextIOWrapper(reader, encoding="utf-8")


def import_puzzles(
    conn: sqlite3.Connection,
    lines: Iterable[str],
    *,
    min_rating: int = 0,
    max_rating: int = 4000,
    limit_per_tag: int | None = None,
) -> dict[str, int]:
    """Insère les puzzles retenus. Retourne le nombre de puzzles par tag.

    ``limit_per_tag`` écarte une ligne dont **tous** les tags ont atteint le quota ; un puzzle qui
    porte plusieurs tags peut donc faire légèrement dépasser le quota d'un tag déjà servi, ce qui est
    préférable à écarter un puzzle pour un tag encore vide.
    """
    counts: dict[str, int] = {}
    reader = csv.reader(lines)
    first = next(reader, None)
    if first is None:
        return counts
    if first[0] != "PuzzleId":  # fichier sans en-tête : première ligne = donnée
        reader = (row for row in [first, *reader])
    quota_tags = {t for tags in THEME_TO_TAGS.values() for t in tags}
    rows = []
    for row in reader:
        if limit_per_tag is not None and all(counts.get(t, 0) >= limit_per_tag for t in quota_tags):
            break  # quotas atteints pour tous les tags servis par des thèmes : inutile de lire la suite
        if len(row) < 8:
            continue
        rating = int(row[3]) if row[3].isdigit() else 0
        if not (min_rating <= rating <= max_rating):
            continue
        tags = tags_for(row[7])
        if not tags:
            continue
        if limit_per_tag is not None and all(counts.get(t, 0) >= limit_per_tag for t in tags):
            continue
        for t in tags:
            counts[t] = counts.get(t, 0) + 1
        rows.append(
            (
                row[0],
                row[1],
                row[2],
                rating,
                int(row[5] or 0),
                int(row[6] or 0),
                row[7],
                ",".join(tags),
                row[8] if len(row) > 8 else None,
            )
        )
        if len(rows) >= 5000:
            _flush(conn, rows)
            rows = []
    _flush(conn, rows)
    conn.commit()
    return counts


def _flush(conn: sqlite3.Connection, rows: list[tuple]) -> None:
    if rows:
        conn.executemany(
            "INSERT OR REPLACE INTO puzzles (id, fen, moves, rating, popularity, nb_plays, themes, tags, game_url)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Importe les puzzles Lichess filtrés par thème et par cote.")
    p.add_argument("--csv", default=LICHESS_URL, help="fichier CSV, .zst, URL (défaut : base officielle) ou -")
    p.add_argument("--db", default="data/chesscoach.sqlite")
    p.add_argument("--min-rating", type=int, default=600)
    p.add_argument("--max-rating", type=int, default=1400)
    p.add_argument("--limit-per-tag", type=int, default=2000)
    a = p.parse_args(argv)
    conn = db.connect(a.db)
    counts = import_puzzles(
        conn, open_csv(a.csv), min_rating=a.min_rating, max_rating=a.max_rating, limit_per_tag=a.limit_per_tag
    )
    total = conn.execute("SELECT count(*) FROM puzzles").fetchone()[0]
    for tag, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"{tag:<22} {n}")
    print(f"{total} puzzle(s) en base.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
