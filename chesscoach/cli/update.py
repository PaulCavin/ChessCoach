"""Une seule commande pour tout mettre à jour : ingestion -> analyse des nouvelles parties -> classification
-> pages HTML -> progression. Idempotent : ne refait que ce qui manque.

``python -m chesscoach.cli.update --username Kuga06 [--time-class rapid --time-control 600] [--all]``
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from chesscoach import db
from chesscoach.engine.analyse import analyse_games, select_games
from chesscoach.ingest.chesscom import ingest
from chesscoach.report.html import build as build_html
from chesscoach.report.progress import build as build_progress
from chesscoach.taxonomy.classify_games import classify_all


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Met à jour le corpus et les bilans en une commande.")
    p.add_argument("--username", required=True)
    p.add_argument("--db", default="data/chesscoach.sqlite")
    p.add_argument("--time-class", default="rapid")
    p.add_argument("--time-control", default="600")
    p.add_argument("--all", action="store_true", help="analyser toutes les cadences")
    p.add_argument("--depth", type=int, default=14)
    p.add_argument("--workers", type=int, default=None, help="défaut : nproc - 1")
    p.add_argument("--limit", type=int, default=None, help="au plus N parties analysées (utile sur téléphone)")
    p.add_argument("--out", default="reports/html")
    p.add_argument("--no-report", action="store_true")
    a = p.parse_args(argv)
    t0 = time.time()
    conn = db.connect(a.db)

    print("1/4 ingestion Chess.com…", flush=True)
    try:
        added = ingest(conn, a.username, log=lambda m: print("   ", m))
    except (OSError, ValueError) as exc:  # réseau absent ou réponse illisible : on continue hors ligne
        print(f"    ingestion impossible ({exc.__class__.__name__}) : on continue hors ligne")
        added = 0
    print(f"    {added} nouvelle(s) partie(s)")

    print("2/4 analyse Stockfish…", flush=True)
    tc, tcl = (None, None) if a.all else (a.time_class, a.time_control)
    items = select_games(conn, a.username, time_class=tc, time_control=tcl, limit=a.limit)
    import os

    workers = a.workers or max(1, (os.cpu_count() or 2) - 1)
    n = analyse_games(conn, items, depth=a.depth, workers=workers, log=lambda m: print("   ", m))
    print(f"    {n} partie(s) analysée(s)")

    print("3/4 classification…", flush=True)
    classify_all(conn, a.username, log=lambda m: print("   ", m))

    if not a.no_report:
        print("4/4 bilans…", flush=True)
        out = Path(a.out)
        nums = build_html(conn, a.username, out, 15)
        (out / "progress.html").write_text(build_progress(conn, a.username), encoding="utf-8")
        print(f"    {len(nums)} bilan(s) dans {out}/ · dernière partie : n° {nums[0] if nums else '—'}")
    print(f"terminé en {time.time() - t0:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
