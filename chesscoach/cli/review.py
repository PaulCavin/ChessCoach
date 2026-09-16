"""Plan de révision du jour : tags dus (FSRS), puzzles proposés, tags acquis.

``python -m chesscoach.cli.review --username Kuga06``
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime

from chesscoach import db
from chesscoach.memory.fsrs import due_tags, load_card
from chesscoach.memory.progress import apply_retirements, rebuild_schedule, tag_progress
from chesscoach.puzzles.select import pick
from chesscoach.report.render import TAG_LABEL
from chesscoach.taxonomy.tags import Tag


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--username", required=True)
    p.add_argument("--db", default="data/chesscoach.sqlite")
    p.add_argument("--puzzles", type=int, default=2, help="puzzles proposés par tag dû")
    a = p.parse_args(argv)
    conn = db.connect(a.db)
    rebuild_schedule(conn, a.username)
    retired = apply_retirements(conn, a.username)
    now = datetime.now(tz=UTC)

    due = due_tags(conn, a.username, now)
    if not due:
        print("Aucun tag à réviser aujourd'hui.")
    for tag, card in due:
        prog = tag_progress(conn, a.username, tag)
        rate = f"{prog.success_rate * 100:.0f} %" if prog.success_rate is not None else "—"
        late = (now - card.due).days if card.due else 0
        print(
            f"\n▶ {TAG_LABEL[tag]} ({tag}) — dû depuis {late} j · réussite {rate} · "
            f"stabilité {card.stability:.1f} j · difficulté {card.difficulty:.1f}"
        )
        for pz in pick(conn, a.username, tag, n=a.puzzles):
            print(f"    puzzle {pz['id']} (cote {pz['rating']}) https://lichess.org/training/{pz['id']}")
        if not conn.execute("SELECT 1 FROM puzzles LIMIT 1").fetchone():
            print("    (aucun puzzle en base : python -m chesscoach.puzzles.lichess --csv lichess_db_puzzle.csv)")

    upcoming = []
    for tag in Tag:
        card = load_card(conn, a.username, tag.value)
        if card and card.due and card.state != "retired" and card.due > now:
            upcoming.append((card.due, tag.value))
    if upcoming:
        print("\nÀ venir :")
        for when, tag in sorted(upcoming)[:5]:
            print(f"    {when.strftime('%Y-%m-%d')}  {TAG_LABEL[tag]}")
    if retired:
        print("\nTags acquis (réussite ≥ 80 % et motif en recul) : " + ", ".join(TAG_LABEL[t] for t in retired))
    return 0


if __name__ == "__main__":
    sys.exit(main())
